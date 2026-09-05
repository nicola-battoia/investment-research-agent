# Backend chat-turn workflow

Follow this path to understand one new message. It reflects the working tree
reviewed on 2026-09-05. For service boundaries, see
[architecture](../docs/architecture.md); for exact defaults and operator overrides,
see [configuration](../docs/configuration.md).

## 1. Send button to HTTP request

```text
ChatComposer.onSubmit
  → ChatConversation.handleSubmit
  → useChat.sendMessage
  → DefaultChatTransport
  → POST /chat/stream
  → stream_chat
  → ChatTurnOrchestrator.prepare
  → chat_turn_events / ChatTurnOrchestrator.complete
  → DocumentAssistant.run / PydanticAI Agent.run
```

[ChatComposer](../frontend/src/components/chat/chat-composer.tsx) submits the form.
[ChatConversation](../frontend/src/components/chat/chat-conversation.tsx) manages
drafts and in-flight state with the AI SDK. The
[chat transport](../frontend/src/lib/chat-transport.ts) fetches the current
Supabase access token and sends only the newest user message:

```json
{
  "id": "<thread UUID>",
  "message": {
    "id": "<client-generated message ID>",
    "role": "user",
    "parts": [{ "type": "text", "text": "What drove Services growth?" }]
  }
}
```

The token is in `Authorization: Bearer <token>`. Ordinary thread CRUD uses
`api.ts` / `http.ts`; this request uses the dedicated SSE transport. History
comes from the database, not a browser-supplied message array.

[app/chat/messages.py](app/chat/messages.py) accepts exactly one nonempty text
part, limits message text to 10,000 characters by default, and validates the
thread UUID and client message ID.

## 2. Authenticate and prepare

[app/auth/dependencies.py](app/auth/dependencies.py) verifies the token through
Supabase Auth and constructs user-scoped and admin clients using the shared
HTTP transport.

[app/api/chat.py](app/api/chat.py) creates a per-turn trace and an orchestrator
using the shared Azure service and assistant from FastAPI application state.
[prepare](app/chat/orchestrator.py) then:

1. Verifies thread ownership and loads messages/citations through
   [database/chats.py](app/database/chats.py).
2. Checks contiguous message positions.
3. Detects an already completed client message ID. The same text replays its
   assistant result; a changed question with the same ID raises a conflict.
4. Records the expected next position for the atomic commit.

These operations occur before the SSE response opens and before any model call.
Missing/invalid authentication returns 401; forbidden and missing threads return
403 and 404. Upstream auth/database timeouts return 503.

## 3. Start the assistant task

[main.py](app/main.py) constructs the shared Azure client and assistant once per
application instance. Its lifespan closes owned Azure and Supabase HTTP clients.
Optional Azure Monitor export is configured at application creation.

[chat/streaming.py](app/chat/streaming.py) opens the response with
`data-turn-status` (`Preparing response…`) and starts
`orchestrator.complete(turn)` as an async task. It sends 15-second status
heartbeats, checks disconnects and applies a 180-second completion deadline.
Authentication and `prepare` happen before that deadline starts.

On a new turn, `complete` creates a retriever, keyword extractor, evidence
registry, counters, model settings and grounding validator. A cached turn skips
the model and reuses its stored answer.

[assistant/history.py](app/assistant/history.py) selects up to five complete
prior user/assistant pairs and 20,000 characters. It removes old source labels;
previous citations are never automatically current-turn evidence.

## 4. Run the model/tool loop

[DocumentAssistant](app/assistant/agent.py) registers:

- Instructions from [policy.py](app/assistant/policy.py), plus the current Spain time.
- Strict native structured output using `DraftGroundedAnswer`.
- Three tools: `search_filings`, `read_chunk`, `read_surrounding_chunks`.
- Lifecycle trace hooks and a deterministic grounding output validator.

The shared [Azure service](app/services/azure_openai_service.py) sends requests to
the configured Azure deployment. [AzureResponsesModel](app/services/azure_responses_model.py)
serializes the request for a local character-based input-token estimate before a
call. The estimate is not a provider token count or a guaranteed upper bound.

The agent can inspect a tool result and make another request before returning
its final answer. Defaults allow ten model requests, eight total tool calls,
five searches and two surrounding reads; tools are sequential, with a 120-second
per-tool timeout and one configured tool/output retry. Search and read calls
all consume the shared tool allowance. Token ceilings differ between Python
defaults and the environment example; use the configuration table.

Passive lifecycle hooks record model/tool activity. They do not send intermediate
model output to the browser.

## 5. Search, read and register evidence

| Tool | Behavior |
| --- | --- |
| `search_filings(query, filters)` | Requires explicit filing filters or `corpus_wide=true`; returns ranked previews and separate bridge previews |
| `read_chunk(S#)` | Returns the full registered passage and marks it read |
| `read_surrounding_chunks(S#)` | Fetches up to two immediate neighbors, registers and marks those neighbors read; does not mark the anchor read |

The [tool definitions](app/assistant/tools.py) reject unknown source labels and
exhausted bounds. Each new evidence passage gets a turn-local `S1`, `S2`, etc.
Search previews include up to 400 characters plus a truncation ellipsis; they
do not mark a passage read.

[DocumentRetriever](app/retrieval/retriever.py) concurrently runs query embedding
plus semantic RPC, and typed keyword extraction plus lexical RPC. The same
filters reach both queries. It fuses rankings at semantic/lexical weights 20:1
with `k=60`, then hydrates the final ten passages.

When two retained chunks are in the same document and section, two positions
apart, the missing middle chunk can be returned as bridge context. It remains
separate from ranked evidence and must still be read before citation.
Ordinary neighbors are fetched only by the surrounding-chunks tool.

## 6. Validate the answer

[GroundingValidator](app/grounding/validator.py) checks the selected response
status and citations against this turn's evidence:

- `conversational` and `out_of_scope`: no searches, citations or source markers;
  at most 1,000 characters.
- `supported`: at least one search and citation.
- `insufficient_evidence`: at least one search, no citations, exact fixed wording.
- `investment_advice_refused`: required refusal sentence; additional factual
  context requires citations.

Each inline `[S<number>]` must match one structured reference. Sources must have
been retrieved and read. Each 20–500-character excerpt must match source fragments
in order, allowing normalized whitespace/case, ellipses, and boundary punctuation.
The validator builds full-passage text highlights or table-cell highlights.

One output retry can correct validation problems. Exhausted retries raise
`GroundingFailureError` and the stream emits `grounding_failed`.
Citation checks do not establish claim entailment or verify arithmetic; those
remain model-policy and answer-evaluation responsibilities.

## 7. Commit, then deliver

The orchestrator builds UI parts and calls `complete_chat_turn`, defined in
[migration 0007](app/alembic/versions/20260821_0007_complete_chat_turn.py). The
function locks the owned thread, checks the expected position, and atomically
writes both messages, citation rows, assistant usage, timestamps and the
first-question title.

After the commit, SSE sends:

```text
start
text-start → text-delta (160-character pieces) → text-end
source-url and data-citation parts
finish
[DONE]
```

This is delivery of already validated final text, not live model-token streaming.
Citation data includes source IDs, accession, filing/report dates, section/offsets,
excerpt and optional text/table display payload. The frontend turns source markers
into conversation-wide numbered buttons and opens a source panel.

## 8. Failure, cancellation and retry

Before SSE, errors use HTTP responses. Once SSE opens, its status can remain
200 even when the run fails. The failure protocol is a transient
`data-turn-error` with `code`, `message`, `retryable`, followed by `error`
and `[DONE]`.

Codes include `turn_timeout`, `turn_conflict`, `thread_missing`,
`grounding_failed`, `database_unavailable`, `assistant_rate_limited`,
`assistant_unavailable`, specific assistant-budget limits, and `turn_failed`.

Cancelling before commit prevents a partial turn. A commit may already have
succeeded when the client disconnects or a response is lost. The browser reloads
the thread after stream errors to reconcile persisted results; retrying a completed
client ID replays the stored response. The explicit Stop path restores the draft
but has a reconciliation gap described in the [audit](../docs/repository-audit.md).

## 9. Diagnostics and inspection

[AssistantTrace](app/assistant/tracing.py) records stages across preparation,
model/tool calls, retrieval, grounding, persistence and stream delivery.
Production summary logs retain bounded scalar metadata, not user/thread IDs,
prompts, answers or exception messages. Full local traces are content-rich.
The default production event cap is 4 KiB.

[telemetry.py](app/telemetry.py) adds optional Azure Monitor spans around the
assistant run and AI calls. The parent `chat research turn` span carries
`app.trace_id`; it does not cover pre-stream authentication/preparation or final
database persistence/SSE delivery. Azure content capture is independently opt-in.

Use [the evaluation guide](evaluation/README.md) to choose between a full assistant
run, one real search-tool dispatch with a simulated planner, or independent
retrieval-branch inspection. These harnesses do not persist chat turns.
