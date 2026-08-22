# Backend chat-turn workflow

This is the actual backend path for one new frontend chat message, from
`POST /chat/stream` through a validated, stored response. It describes the
current implementation rather than an intended design. File links and the
short excerpts below are the authoritative starting points for each step.

## 1. The frontend sends one user message

`ChatConversation` calls `sendMessage({ text: message })`. The AI SDK transport
posts the thread id and the newest UI message to the backend and adds the
Supabase access token:

```ts
// frontend/src/lib/chat-transport.ts
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

The rest of this document is about the backend. The HTTP boundary is
[`app/api/chat.py`](app/api/chat.py): FastAPI validates the JSON as
`ChatStreamRequest`, authenticates the bearer token via `ChatContext`, and
starts the streaming response.

```py
@router.post("/stream")
async def stream_chat(payload: ChatStreamRequest, request: Request,
                      context: ChatContext) -> StreamingResponse:
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
    return StreamingResponse(chat_turn_events(...), media_type="text/event-stream", ...)
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

## 3. The request-scoped assistant is built and run

[`complete`](app/chat/orchestrator.py) constructs a fresh retriever, evidence
store, counters, and grounding validator for every non-cached turn. The shared
application-level `DocumentAssistant` is created at startup in
[`app/main.py`](app/main.py), but all mutable evidence is per request.

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
make it an SEC-filing research assistant. In particular, factual answers must
search current-turn evidence first; a passage must be read before it is cited;
and the agent must return structured `status`, `answer`, and `citations`.

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
plus optional company, ticker, filing type, filing-year, and filing-date filters.
At most three searches are allowed, and one search requests 50 candidates and
returns at most 10 fused ranked passages:

```py
# app/assistant/tools.py
result = await ctx.deps.retriever.search(
    query, (filters or FilingSearchFilters()).to_retrieval_filters(),
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
choose `supported`, `insufficient_evidence`, or `investment_advice_refused`.
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
it is not another LLM judgment. For a supported answer it requires at least one
search and one citation. For every inline `[S<number>]` marker, it requires one
matching structured citation, verifies that the source was retrieved **and
read**, and verifies the proposed 20–500 character excerpt occurs in that full
passage:

```py
if source_id not in read_source_ids:
    raise GroundingValidationError(f"Citation {source_id} must be read before it can be cited")
excerpt = references[source_id].excerpt
if _normalized_text(excerpt) not in _normalized_text(passage.text):
    raise GroundingValidationError(
        f"Citation {source_id} excerpt is not present in its passage")
```

It also enforces exact insufficient-evidence wording with no citations, required
investment-advice refusal wording, marker/reference agreement, and a set of
prohibited investment-advice patterns. On the first invalid final output,
`ModelRetry` asks the agent to correct its answer. If its allowed output retry is
exhausted, `GroundingFailureError` prevents a response from being persisted or
shown; streaming maps it to `grounding_failed`.

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
The UI receives an early `researching` status and periodic heartbeats. It does
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
