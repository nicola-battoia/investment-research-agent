# Backend chat-turn workflow

This is the actual backend path for one new frontend chat message, from
`POST /chat/stream` through a validated, stored response. It describes the
current implementation rather than an intended design. File links and the
short excerpts below are the authoritative starting points for each step.

## 1. Exact frontend-to-agent call chain

The frontend does **not** import or call
[`app/assistant/agent.py`](app/assistant/agent.py). The browser can only make an
HTTP request. The following handoffs connect the Send button to the agent:

```text
ChatComposer.onSubmit
  -> ChatConversation.handleSubmit
  -> AI SDK useChat.sendMessage
  -> DefaultChatTransport POST /chat/stream
  -> FastAPI stream_chat
  -> chat_turn_events creates orchestrator.complete task
  -> ChatTurnOrchestrator.complete calls DocumentAssistant.run
  -> DocumentAssistant.run calls its PydanticAI Agent.run
  -> PydanticAI calls the OpenAI Responses API and executes tool calls
```

### 1.1 Send button to `useChat.sendMessage`

[`frontend/src/components/chat/chat-composer.tsx`](../frontend/src/components/chat/chat-composer.tsx)
owns the `<form>`. Clicking Send, or pressing Enter without Shift, submits that
form and calls the `onSubmit` callback supplied by `ChatConversation`:

```tsx
// frontend/src/components/chat/chat-composer.tsx
function handleSubmit(event: FormEvent<HTMLFormElement>) {
  event.preventDefault()
  if (!input.trim() || isRunning) return
  onSubmit()
}

return <form onSubmit={handleSubmit}>...</form>
```

[`frontend/src/components/chat/chat-conversation.tsx`](../frontend/src/components/chat/chat-conversation.tsx)
passes its local `handleSubmit` function. That function clears the input and
calls `sendMessage`, which comes from the AI SDK's `useChat` hook:

```tsx
// frontend/src/components/chat/chat-conversation.tsx
const { messages, sendMessage, status, stop } = useChat<ChatMessage>({
  id: threadId,
  messages: initialMessages,
  transport,
  ...
})

function handleSubmit() {
  const message = input.trim()
  if (!message || isRunning) return
  ...
  void sendMessage({ text: message })
}
```

At this point no backend Python function has been called yet. `sendMessage`
adds a user `UIMessage` to the frontend state and asks the configured transport
to send it.

### 1.2 The transport creates the HTTP request

`transport` is created by
[`frontend/src/lib/chat-transport.ts`](../frontend/src/lib/chat-transport.ts).
It uses `VITE_API_BASE_URL` and posts only the thread id and newest user
message—not the complete frontend message array—to `/chat/stream`:

```ts
return new DefaultChatTransport<ChatMessage>({
  api: `${env.apiBaseUrl}/chat/stream`,
  fetch: authenticatedChatFetch,
  prepareSendMessagesRequest: ({ id, messages }) => {
    const message = messages.at(-1)
    if (!message) throw new Error('A chat message is required')
    return { body: { id, message } }
  },
})
```

`authenticatedChatFetch` gets the current Supabase access token and adds it to
the request:

```ts
const headers = new Headers(init?.headers)
headers.set('Authorization', `Bearer ${accessToken}`)
const response = await fetch(input, { ...init, headers })
```

The JSON body has this effective shape (the AI SDK creates the message id):

```json
{
  "id": "<thread UUID>",
  "message": {
    "id": "<client message id>",
    "role": "user",
    "parts": [{ "type": "text", "text": "What drove revenue growth?" }]
  }
}
```

This streaming call does not use the ordinary `api.post` helper from
`frontend/src/lib/api.ts`; it uses `DefaultChatTransport` because the response
is an AI SDK-compatible Server-Sent Event stream.

### 1.3 FastAPI maps the URL to `stream_chat`

The backend route is assembled in two pieces:

```py
# app/api/chat.py
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/stream")
async def stream_chat(...): ...

# app/main.py
application.include_router(chat_router)
```

Together they produce `POST /chat/stream`. Before `stream_chat` runs, FastAPI:

1. validates the body using `ChatStreamRequest` from
   [`app/chat/messages.py`](app/chat/messages.py);
2. resolves `ChatContext = Depends(get_authenticated_context)`;
3. verifies the bearer token with Supabase and creates a user-scoped Supabase
   client whose database access is subject to RLS.

```py
# app/chat/messages.py
class ChatStreamRequest(ApiModel):
    id: UUID
    message: UserUIMessage

# app/auth/dependencies.py
access_token = credentials.credentials
client = await create_user_supabase_client(app_settings, access_token)
response = await client.auth.get_user(access_token)
return AuthenticatedContext(user=response.user, supabase=client)
```

The route then obtains the already-created assistant from FastAPI application
state, puts it into a per-request orchestrator, prepares the turn, and returns
the SSE response:

```py
# app/api/chat.py
orchestrator = ChatTurnOrchestrator(
    settings=request.app.state.settings,
    supabase=context.supabase,
    openai_client=request.app.state.openai_client,
    assistant=request.app.state.document_assistant,
)
prepared = await orchestrator.prepare(
    thread_id=payload.id,
    user_id=UUID(context.user.id),
    user_message=to_internal_user_message(payload.message),
)
return StreamingResponse(
    chat_turn_events(request=request, orchestrator=orchestrator, turn=prepared, ...),
    media_type="text/event-stream",
    ...,
)
```

`to_internal_user_message` extracts the one text part. Consequently, the exact
string eventually passed to the agent is `payload.message.parts[0].text`:

```py
return InternalUserMessage(
    client_id=message.id,
    content=message.parts[0].text,
    message_data=...,
)
```

## 2. The turn is authorized and its prior conversation is loaded

[`ChatTurnOrchestrator.prepare`](app/chat/orchestrator.py) loads the requested
thread before any model call. `load_thread` verifies that the thread belongs to
the authenticated user, then loads messages and citations ordered by position.
The orchestrator checks that positions are contiguous and detects a retry of an
already completed client message. A retry returns the stored assistant result;
it does not call the model again.

```py
# app/chat/orchestrator.py
_thread, messages, citations = await chats.load_thread(
    self._supabase, self._settings, thread_id, user_id
)
_validate_positions(messages)
cached_assistant = _find_cached_assistant(
    stored_messages_to_ui(messages, citations),
    user_message.client_id, user_message.content,
)
return PreparedChatTurn(..., expected_position=len(messages),
                        history_rows=tuple(messages),
                        cached_assistant=cached_assistant)
```

Only the last three *complete* earlier user/assistant pairs, up to 20,000
characters, are given to the agent. Old `[S...]` markers are removed, so prior
turn citations never become evidence for the current turn:

```py
# app/assistant/history.py
MAX_HISTORY_TURNS = 3
MAX_HISTORY_CHARACTERS = 20_000
...
_remove_old_source_ids(user.content)
_remove_old_source_ids(assistant.content)
```

## 3. Where `agent.py` is created and called

There are two distinct lifetimes: the reusable agent definition is created once
when the backend process starts, while retrieval and evidence state are created
fresh for every user message.

### 3.1 Backend startup creates the shared `DocumentAssistant`

Importing [`app/main.py`](app/main.py) executes `app = create_app(settings)`.
`create_app` creates one shared OpenAI client and passes it into
`create_document_assistant` from
[`app/assistant/agent.py`](app/assistant/agent.py). The resulting
`DocumentAssistant` is stored at `application.state.document_assistant`:

```py
# app/main.py
shared_openai_client = openai_client or AsyncOpenAI(...)
shared_assistant = document_assistant or create_document_assistant(
    app_settings,
    shared_openai_client,
)
...
application.state.openai_client = shared_openai_client
application.state.document_assistant = shared_assistant
```

`create_document_assistant` wraps that OpenAI client in PydanticAI's OpenAI
Responses model and constructs `DocumentAssistant`:

```py
# app/assistant/agent.py
model = OpenAIResponsesModel(
    settings.openai_assistant_model,
    provider=OpenAIProvider(openai_client=openai_client),
)
return DocumentAssistant(model)
```

The `DocumentAssistant` constructor creates the actual PydanticAI `Agent` and
registers its instructions, tools, structured output, and output validator. It
is safe to reuse this definition because request-specific mutable state is not
stored on it:

```py
self._agent = Agent(
    model,
    name="document_copilot",
    deps_type=AssistantDeps,
    output_type=NativeOutput(DraftGroundedAnswer, ...),
    instructions=ASSISTANT_INSTRUCTIONS,
    tools=[search_filings, read_chunk, read_surrounding_chunks],
    retries={"tools": 1, "output": 1},
    tool_timeout=60,
)
```

### 3.2 Consuming the SSE response starts the turn task

`stream_chat` does not call the agent directly. Its `StreamingResponse` consumes
the async generator in [`app/chat/streaming.py`](app/chat/streaming.py). That
generator first sends `Researching filings…`, then starts
`orchestrator.complete(turn)` as an asynchronous task:

```py
# app/chat/streaming.py
async def chat_turn_events(...):
    yield _status_event()
    task = asyncio.create_task(orchestrator.complete(turn))
    ...
```

This task boundary lets the stream send a heartbeat every 15 seconds, detect a
browser disconnect, enforce the whole-turn timeout, and cancel the ongoing turn
when necessary.

### 3.3 `ChatTurnOrchestrator.complete` calls `DocumentAssistant.run`

[`complete`](app/chat/orchestrator.py) first returns a stored result immediately
when this client message id has already completed. Otherwise it constructs a
fresh retriever, evidence store, counters, model settings, and grounding
validator for this one message:

```py
# app/chat/orchestrator.py
retriever = DocumentRetriever(self._supabase, self._openai_client,
    OpenAIKeywordExtractor(self._openai_client,
        model=self._settings.openai_keyword_model),
    embedding_model=self._settings.openai_embedding_model,
    embedding_dimensions=self._settings.openai_embedding_dimensions)
deps = AssistantDeps(user_id=turn.user_id, thread_id=turn.thread_id,
    retriever=retriever, grounding_validator=GroundingValidator(),
    model_settings=AssistantModelSettings.from_app_settings(self._settings))
result = await self._assistant.run(turn.user_message.content, deps,
    stored_messages_to_history(list(turn.history_rows)))
```

`self._assistant` is the same `request.app.state.document_assistant` passed from
the route into the orchestrator. Therefore the line above is the direct call
from the chat request workflow into `app/assistant/agent.py`.

Its three arguments are:

- `question`: the new frontend text;
- `deps`: fresh current-turn retrieval, evidence, counters, validation, and
  model settings;
- `history`: a bounded conversion of earlier stored user/assistant messages.

### 3.4 `DocumentAssistant.run` starts the actual model/tool loop

Finally, [`DocumentAssistant.run`](app/assistant/agent.py) validates the question
and calls `self._agent.run(...)`. This is the point where PydanticAI sends the
request through `OpenAIResponsesModel` to the OpenAI Responses API:

```py
# app/assistant/agent.py
result = await self._agent.run(
    question,
    deps=deps,
    message_history=build_message_history(history),
    model_settings=deps.model_settings.to_pydantic_ai(),
    usage_limits=UsageLimits(
        request_limit=12,
        tool_calls_limit=12,
        output_tokens_limit=6_000,
        per_request_input_tokens_limit=64_000,
    ),
    event_stream_handler=event_stream_handler,
)
```

The orchestrator does not pass an `event_stream_handler`, so it is `None` here.
The agent instead registers passive PydanticAI lifecycle hooks. Those hooks record
the complete semantic request/response boundary and tool validation/execution events
without changing them. PydanticAI performs the model/tool loop: it sends the
instructions, history, question, tool schemas, and structured output schema;
executes a local Python tool when the model requests one; sends that tool result
back to the model; and repeats until the model returns the final structured answer
or a limit/error stops the run. The browser does not call these tools and does not
see their intermediate events.

The agent identity, output contract, and tool list are defined in
[`app/assistant/agent.py`](app/assistant/agent.py):

```py
self._agent = Agent(
    model,
    name="document_copilot",
    deps_type=AssistantDeps,
    output_type=NativeOutput(DraftGroundedAnswer, name="grounded_document_answer",
                             strict=True),
    instructions=ASSISTANT_INSTRUCTIONS,
    tools=[search_filings, read_chunk, read_surrounding_chunks],
    retries={"tools": 1, "output": 1},
    tool_timeout=60,
)
```

Its system instructions in [`app/assistant/policy.py`](app/assistant/policy.py)
make it an SEC-filing research assistant with two no-retrieval conversation
paths. Greetings, identity, capabilities, scope, and question-formulation help
use `conversational`; unrelated requests use `out_of_scope`. Company or filing
facts must search current-turn evidence first, and a passage must be read before
it is cited. Every path returns structured `status`, `answer`, and `citations`.

This is an iterative tool-using model run, not a fixed retrieval pipeline. The
model can inspect a tool result and call another tool before producing its final
structured output. Hard bounds prevent unbounded iteration:

```py
# app/assistant/agent.py
usage_limits=UsageLimits(
    request_limit=8, tool_calls_limit=12, output_tokens_limit=6_000,
    per_request_input_tokens_limit=64_000,
)

# app/assistant/tools.py
MAX_SEARCH_CALLS = 3
MAX_SURROUNDING_CALLS = 3
```

Tool calls are deliberately sequential (`parallel_tool_calls=False`). Invalid
tool arguments and an exhausted per-tool limit return `ModelRetry`, giving the
model one configured tool retry, rather than exposing arbitrary database access.

## 4. `search_filings`: what it returns and how it retrieves

The model may call `search_filings(query, filters)`. It accepts a focused query
plus an explicit search scope. Every call must include at least one company,
ticker, filing type, report/fiscal year, or filing-date filter, unless the model
deliberately sets `corpus_wide=true`. Corpus-wide scope cannot be combined with
filing filters. At most three searches are allowed, and one search requests 50
candidates and returns at most 10 fused ranked passages:

```py
# app/assistant/tools.py
result = await ctx.deps.retriever.search(
    query, filters.to_retrieval_filters(),
    limit=SEARCH_RESULT_LIMIT, candidate_limit=SEARCH_CANDIDATE_LIMIT,
)
ranked = tuple(ctx.deps.evidence.preview(item) for item in result.passages)
context = tuple(ctx.deps.evidence.preview(item)
                for item in result.context_passages)
return SearchToolResult(query=query, lexical_query=result.keywords.search_text,
                        ranked_passages=ranked, context_passages=context)
```

`preview` is metadata plus no more than 600 characters of normalized text, not a
full chunk. It registers a per-turn source ID (`S1`, `S2`, ...) so later calls
cannot use a UUID or evidence from a different turn:

```py
# app/assistant/evidence.py
if len(text) > PREVIEW_CHARACTERS:
    text = text[:PREVIEW_CHARACTERS].rstrip() + "…"
return PassagePreview(source_id=self.source_id_for(passage), ..., preview=text)
```

### Hybrid retrieval

[`DocumentRetriever.candidate_details`](app/retrieval/retriever.py) runs two
branches concurrently:

```py
async def semantic_branch():
    embedding = await self._embed_query(query)
    return await semantic_search(self._supabase, embedding, active_filters,
                                 candidate_limit)

async def lexical_branch():
    keywords = await self._keyword_extractor.extract(query)
    return keywords, await lexical_search(self._supabase, keywords.search_text,
                                          active_filters, candidate_limit)

(semantic, _), (keywords, lexical, _) = await asyncio.gather(
    semantic_branch(), lexical_branch())
fused = reciprocal_rank_fusion({"semantic": [...], "lexical": [...]},
                               k=self._rrf_k, weights=self._weights)
```

The semantic branch embeds the original search query with OpenAI and calls the
Supabase `match_document_chunks_semantic` RPC. The lexical branch first asks the
keyword-extraction model for 1–6 tightly constrained filing concepts, joins them
into `search_text`, and calls `match_document_chunks_lexical`. Their independent
rankings are combined by weighted Reciprocal Rank Fusion (semantic weight 20,
lexical weight 1, `k=60`):

```py
# app/retrieval/fusion.py
scores[chunk_id] += weight / (k + rank)
```

The final fused chunk IDs are hydrated from `document_chunks` with their source
document metadata before previews are returned.

### Does search include surrounding chunks?

Not the ordinary immediate neighbors. Search does automatically include a
special, narrower kind of context: **bridge chunks**. If two ranked results are
from the same document and section and their chunk indexes differ by exactly 2,
the one missing chunk is fetched as a `neighbor` preview. This preserves a
structurally useful gap in the ranked results; it is not a general
"previous/next chunk" expansion.

```py
# app/retrieval/retriever.py
if (left.document_id == right.document_id
        and left.section_title == right.section_title
        and abs(left.chunk_index - right.chunk_index) == 2):
    bridge_index = min(left.chunk_index, right.chunk_index) + 1
    requested.setdefault(left.document_id, set()).add(bridge_index)
...
return tuple(passage.model_copy(update={"passage_kind": "neighbor"})
             for passage in ...)
```

Those bridges arrive as previews in `context_passages`, alongside (but separate
from) the 10 ranked previews. They are registered as current-turn evidence and
can be explicitly read, but they are not automatically full-text reads.

## 5. `read_chunk` and `read_surrounding_chunks`

Search never automatically reads a full chunk. The instructions tell the model
to call `read_chunk` for every source it intends to cite. This tool only returns
the full text for a source ID already returned in this turn:

```py
# app/assistant/tools.py
async def read_chunk(ctx: RunContext[AssistantDeps], source_id: str) -> ReadablePassage:
    passage = ctx.deps.evidence.require(source_id)
    return ctx.deps.evidence.readable(passage)
```

Calling it marks that exact source ID as read:

```py
# app/assistant/evidence.py
def readable(self, passage: SourcePassage) -> ReadablePassage:
    source_id = self.source_id_for(passage)
    self._read_source_ids.add(source_id)
    return ReadablePassage(source_id=source_id, ..., text=passage.text)
```

Reading one chunk does **not** automatically read its neighbors. The model must
ask for them explicitly with `read_surrounding_chunks(Sn)`. This call is limited
to three calls per turn, fetches radius 1, and returns at most two immediate
neighbors (previous and/or next, subject to document boundaries):

```py
# app/assistant/tools.py
passages = await ctx.deps.retriever.surrounding_chunks(anchor.chunk_id, radius=1)
return tuple(ctx.deps.evidence.readable(item) for item in passages[:2])

# app/retrieval/queries.py
.eq("document_id", str(anchor.document_id))
.gte("chunk_index", max(0, anchor.chunk_index - radius))
.lte("chunk_index", anchor.chunk_index + radius)
```

Those returned neighbors are full-text `ReadablePassage` values, registered if
new, and marked read. They may therefore be cited. The anchor is excluded from
the neighbor query result; calling this tool does not itself mark the anchor as
read.

## 6. Final answer and deterministic grounding validation

The model finally emits strict structured `DraftGroundedAnswer` output. It can
choose `conversational`, `out_of_scope`, `supported`, `insufficient_evidence`,
or `investment_advice_refused`.
Before anything leaves the assistant boundary, the output validator in
[`app/assistant/agent.py`](app/assistant/agent.py) validates it against only
the request-local evidence:

```py
@self._agent.output_validator
async def validate_grounding(ctx, output):
    try:
        ctx.deps.validated_answer = ctx.deps.grounding_validator.validate(
            output, evidence=ctx.deps.evidence.passages,
            read_source_ids=ctx.deps.evidence.read_source_ids,
            search_calls=ctx.deps.counters.search_calls,
        )
    except GroundingValidationError as error:
        if ctx.retry < ctx.max_retries:
            raise ModelRetry("The answer failed grounding validation ...") from error
        raise GroundingFailureError(...) from error
    return output
```

[`GroundingValidator`](app/grounding/validator.py) is deterministic Python code;
it is not another LLM judgment. `conversational` and `out_of_scope` answers must
use zero searches, contain no citations or source-like markers, and stay within
1,000 characters. Their semantic routing is controlled by the same agent policy;
there is no second classifier. For a supported answer the validator requires at
least one search and one citation. For every inline `[S<number>]` marker, it
requires one matching structured citation, verifies that the source was
retrieved **and read**, and verifies every source fragment in the proposed 20–500
character excerpt. Runs of whitespace and case are normalized, punctuation at a
fragment boundary may differ, and `...` or `…` may separate omitted source text.
Every substantive fragment must still occur in the full passage in source order:

```py
if source_id not in read_source_ids:
    citation_errors.append(f"Citation {source_id} must be read before it can be cited")
excerpt = references[source_id].excerpt
excerpt_ranges = _excerpt_raw_ranges(excerpt, passage.text)
if not excerpt_ranges:
    citation_errors.append(
        f"Citation {source_id} excerpt fragments are not present in order")
```

It also enforces exact insufficient-evidence wording with no citations, required
investment-advice refusal wording, marker/reference agreement, and a set of
prohibited investment-advice patterns across every status. Citation-specific errors
are collected before validation fails, so one `ModelRetry` asks the agent to correct
all bad citations together. If its allowed output retry is exhausted,
`GroundingFailureError` prevents a response from being persisted or shown; streaming
maps it to `grounding_failed`.

## 7. Persist first, then stream the completed answer

After a validated answer, the orchestrator turns citations into UI parts and
calls one Supabase RPC to atomically insert the user message, assistant message,
citation rows, usage, and update the thread:

```py
# app/chat/orchestrator.py
persistence = await chats.complete_chat_turn(
    self._supabase, turn.thread_id, turn.expected_position, turn.user_message,
    user_message_id, assistant_message_id, result.answer.answer,
    assistant_message_data(result.answer.status, parts),
    result.usage.model_dump(mode="json"), citations, derive_thread_title(...),
)
```

The database function locks the thread and rejects a turn if another request
changed message position while the model was working:

```sql
-- app/alembic/versions/20260821_0007_complete_chat_turn.py
SELECT thread.owner_id ... WHERE thread.id = p_thread_id FOR UPDATE;
...
IF v_next_position <> p_expected_position THEN
  RAISE EXCEPTION 'Chat message position changed during the turn'
    USING ERRCODE = '40001';
END IF;
```

Finally [`chat_turn_events`](app/chat/streaming.py) sends Server-Sent Events.
The UI receives an early `Preparing response…` status and periodic heartbeats. It does
**not** receive live model-token streaming: the backend waits for the complete,
grounded, persisted result, then splits its already-final text into 160-character
SSE deltas followed by citation parts and `finish`.

```py
# app/chat/streaming.py
task = asyncio.create_task(orchestrator.complete(turn))
...
for offset in range(0, len(part.text), TEXT_DELTA_CHARACTERS):
    yield _event({"type": "text-delta", "id": text_id,
                  "delta": part.text[offset : offset + TEXT_DELTA_CHARACTERS]})
```

If the request disconnects, times out, fails grounding, hits a model limit, or
encounters a database conflict, the stream sends a stable error event rather
than an unvalidated partial answer. The frontend can reconcile a broken stream
by reloading the thread, which is safe because successful turns have already
been atomically committed.

## 8. Correlated backend diagnostics

[`app/assistant/tracing.py`](app/assistant/tracing.py) owns one mutable trace object
per frontend turn. The API route creates it before thread preparation and passes it
through the orchestrator, `PreparedChatTurn`, `AssistantDeps`, keyword extractor,
and retriever. Every record has a unique `trace_id`, ordered `sequence`, current
`stage`, user/thread/client-message identifiers, and elapsed time. This explicit
request-local object prevents concurrent turns from mixing correlation state.

The trace records these boundaries:

- `turn.*`: request content, thread/history loading, cache replay, and completion.
- `assistant.model.*`: instructions, messages, tool and output definitions, model
  settings, observable response parts, provider response ID, finish reason, usage,
  duration, and errors for every model request.
- `assistant.tool.*`: raw validation failures, validated arguments, execution result,
  retry/error, tool-call ID, tool index, and duration.
- `retrieval.*`: keyword-model input/output, embedding metadata and fingerprint,
  semantic/lexical candidates, RRF fusion, hydration, bridge context, and surrounding
  reads. Raw embedding vectors are never logged.
- `assistant.grounding.*`: the model-selected draft status, evidence/read state,
  exact deterministic rejection, retry availability, or stable acceptance reason.
- `turn.persistence.*` and `stream.*`: atomic database completion, timeout,
  disconnect, mapped failure, traceback, and final delivery.

Local development uses `LOG_FORMAT=console` and `ASSISTANT_TRACE_MODE=full`.
Railway uses `LOG_FORMAT=json` and `ASSISTANT_TRACE_MODE=summary`; its log search can
filter one complete turn by `trace_id`. Summary mode limits raw text to short
previews. Full mode is still bounded, and truncated fields include total/omitted
character counts and a SHA-256 fingerprint. Secret-bearing keys and token patterns,
provider-private payloads, hidden reasoning, and embeddings are redacted or omitted.
