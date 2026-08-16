# Document Copilot implementation to-do list

Work through these phases in order. A phase is complete when its final check passes.

## 1. Confirm the MVP rules

- [ ] Use the five-company sample corpus for the first working version: Apple, Amazon, Alphabet, Microsoft, and NVIDIA, covering the available 2021–2025 10-K filings.
- [ ] Remove any sample ticker that is not part of the agreed pilot corpus from the download configuration.
- [ ] Confirm which 10-K Club email domain or email allow-list can create accounts.
- [ ] Define the citation format shown to users: company, filing type, filing date, page when reliable, section, excerpt, and SEC source link.
- [ ] Test a few downloaded SEC filings and confirm that extraction can preserve a reliable page or section locator. Use section plus source offsets when a trustworthy page number is not present.
- [ ] Write down the expected behavior for an answerable question, an unsupported question, and a request for investment advice.
- [ ] Turn the example questions in the client brief into the initial evaluation set.

Phase complete when the team has one written MVP contract for the corpus, access rules, citations, answers, and refusals.

## 2. Create the application foundations

- [x] Add the backend dependencies declared in the project guidance with `uv`, including FastAPI, Pydantic, Supabase, SQLAlchemy, Alembic, OpenAI, PydanticAI, `pgvector`, `httpx`, and `structlog`.
- [ ] Create the backend package structure under `backend/app`, plus `backend/ingest` and `backend/tests`.
- [x] Implement `backend/app/config.py` as the only place that reads and validates backend environment variables.
- [x] Create the FastAPI application with CORS, structured logging, a health endpoint, and application dependencies stored through FastAPI rather than module globals.
- [ ] Initialize Alembic and connect it to the SQLAlchemy metadata and the direct Supabase database URL.
- [ ] Scaffold the Vite React application with strict TypeScript, React Router, Tailwind CSS, and shadcn/ui.
- [ ] Add `frontend/src/lib/env.ts` as the only place that reads and validates frontend environment variables.
- [ ] Create the basic frontend route and component folders described in the architecture.
- [ ] Document the exact local setup, run, migration, lint, type-check, and test commands in the main README.

Phase complete when both services start locally, the frontend can call the backend health endpoint, and configuration fails clearly when a required value is missing.

## 3. Build the database schema

- [ ] Model `profiles`, linked to Supabase Auth users.
- [ ] Model `chat_threads` with an owner, title, and timestamps.
- [ ] Model ordered `chat_messages` with role, content, message data, model usage, and timestamps.
- [ ] Model `message_citations` linked to assistant messages and source chunks.
- [ ] Model `source_documents` with company, ticker, form, filing dates, accession number, SEC URL, normalized Markdown, extraction metadata, and a content checksum.
- [ ] Model `document_chunks` with document ID, chunk order, text, token count, page or section locator, source offsets, metadata, embedding, and full-text search data.
- [ ] Add uniqueness and foreign-key rules that prevent duplicate filings, duplicate chunks, orphan citations, and messages without a thread.
- [ ] Create the first reviewed Alembic migration.
- [ ] In the migration, enable `pgvector`, add the embedding column with the configured dimensions, add the generated `tsvector` column, and create HNSW and GIN indexes.
- [ ] Enable row-level security and add policies so users can only read and change their own profiles, threads, messages, and citations. Keep the shared filing corpus read-only to signed-in users.
- [ ] Decide how a profile is created for a new Auth user and implement that flow.
- [ ] Apply the migration to a clean Supabase project and verify every table, index, policy, and grant.

Phase complete when the full schema can be created from an empty database by running `uv run alembic upgrade head`.

## 4. Implement authentication and the shared API layer

- [ ] Configure Supabase email authentication for local development and production.
- [ ] Enforce the approved company email domain or email allow-list during account creation.
- [ ] Create the shared Supabase browser client and an auth provider for session loading, sign-in, sign-out, and expired sessions.
- [ ] Add protected frontend routes and a simple email sign-in screen.
- [ ] Implement backend bearer-token validation by asking Supabase Auth for the current user.
- [ ] Expose a reusable `get_current_user` FastAPI dependency.
- [ ] Create user-scoped and admin Supabase clients in the backend; never send the service-role key to the browser.
- [ ] Implement the frontend `fetch` wrapper with the API base URL, bearer-token injection, JSON handling, a timeout, and typed HTTP versus network errors.
- [ ] Add the product-level API client used by pages and components.
- [ ] Add backend tests for missing, invalid, and expired tokens and for attempts to access another user's records.

Phase complete when a user can sign in and call a protected backend endpoint, while unauthenticated and cross-user requests are rejected.

## 5. Build a thin chat path with a stubbed assistant

- [ ] Add backend operations to create, list, load, rename, and delete the current user's chat threads.
- [ ] Add backend operations to load the ordered messages and citations for one owned thread.
- [ ] Define the frontend-to-backend message format and keep the conversion to internal message types in one backend module.
- [ ] Add `POST /chat/stream` with ownership checks and a temporary streamed response in the AI SDK format.
- [ ] Verify the exact AI SDK React and streaming packages and APIs, then install the required packages with `pnpm`.
- [ ] Build a minimal protected chat page with a thread list, new-thread action, message history, input box, and streaming state.
- [ ] Connect the frontend chat transport directly to FastAPI with the current Supabase access token.
- [ ] Persist the stubbed user and assistant messages, then prove that a page refresh restores the conversation.
- [ ] Show useful UI messages for authentication, forbidden, missing-thread, validation, server, network, and CORS failures.

Phase complete when an authenticated user can create a chat, receive a streamed stub response, reload it, and never see another user's chat.

## 6. Build the SEC filing ingestion pipeline

- [ ] Set a valid SEC contact in the downloader and make its sample-company configuration match the MVP corpus.
- [ ] Read the download manifest and process each filing with its accession number and source URL.
- [ ] Convert SEC HTML into clean, normalized Markdown while preserving headings, tables, and the citation locators agreed in phase 1.
- [ ] Strip navigation, scripts, style data, repeated headers, and other text that should not be searchable.
- [ ] Store the normalized document text and extraction metadata in `source_documents`.
- [ ] Split each document into useful passages that respect sections and tables, with small overlap where needed.
- [ ] Record stable chunk order, token count, page or section, source offsets, and filing metadata on every chunk.
- [ ] Generate embeddings in batches with the configured OpenAI model and dimensions.
- [ ] Make ingestion safe to rerun by using accession numbers, checksums, and upserts instead of creating duplicates.
- [ ] Add clear progress, retry, failure, and final-summary output without logging secrets or full filing contents.
- [ ] Provide one command for a dry run and one command for ingesting or re-ingesting the sample corpus.
- [ ] Add fixture-based backend tests for HTML cleanup, Markdown output, chunk boundaries, metadata, and rerun behavior.
- [ ] Ingest the sample corpus and manually inspect representative financial tables, risk factors, and cross-page sections.

Phase complete when the sample filings are stored once, searchable as clean chunks, and traceable back to their SEC sources.

## 7. Implement hybrid retrieval

- [ ] Convert each user query into an embedding with the same model and dimensions used during ingestion.
- [ ] Implement a bounded `pgvector` similarity query over document chunks.
- [ ] Implement a bounded Postgres full-text query over the generated search vector.
- [ ] Support explicit filters for company or ticker, filing type, filing year, and date range.
- [ ] Fuse the semantic and lexical ranked lists in Python with Reciprocal Rank Fusion.
- [ ] Remove duplicate results and fetch neighboring chunks only when they add useful context.
- [ ] Return a typed source-passage object with all metadata needed for grounding and display.
- [ ] Keep retrieval independent from the model agent and do not allow the model to generate SQL.
- [ ] Add unit tests for vector-query construction, full-text-query construction, filters, rank fusion, deduplication, and neighboring context.
- [ ] Run the evaluation questions against retrieval alone and inspect whether the needed passages appear near the top.
- [ ] Tune chunking, result counts, and ranking weights using recorded evaluation results rather than individual anecdotes.

Phase complete when the retrieval layer consistently finds the evidence needed by the initial evaluation set without calling the answer model.

## 8. Implement the grounded document assistant

- [ ] Define typed models for source passages, citations, and a grounded answer.
- [ ] Create explicit request-scoped agent dependencies containing the user, thread, retriever, grounding validator, and model settings.
- [ ] Write the assistant instructions: use only retrieved evidence, cite factual claims, refuse unsupported conclusions, and never give stock recommendations or investment advice.
- [ ] Give the agent only bounded tools such as searching filings, reading a selected chunk, and reading nearby chunks.
- [ ] Include only the conversation history needed to understand the current question.
- [ ] Define one machine-checkable citation marker and use it consistently in model output and the UI.
- [ ] Validate that every citation names a passage retrieved during the current turn and that every supported answer includes citations.
- [ ] Validate that refusal answers clearly say the corpus does not contain enough evidence and do not attach invented citations.
- [ ] Return a controlled grounding failure when validation fails; never save an invalid assistant answer as a successful message.
- [ ] Add unit tests for valid answers, unknown citation IDs, missing citations, unsupported questions, and investment-advice requests.
- [ ] Add a small set of marked integration tests that call OpenAI and Supabase only when test credentials are present.

Phase complete when the assistant either returns a validated, cited answer or a clear refusal—never an unsupported polished answer.

## 9. Replace the stub with the complete chat turn

- [ ] Make the chat orchestrator own the full turn: authorize the thread, normalize messages, retrieve evidence, run the agent, validate citations, persist results, and report usage.
- [ ] Send answer text as streaming message parts and citations as structured source parts understood by the frontend.
- [ ] Define a streaming failure protocol that prevents a failed grounding check from appearing as a completed answer.
- [ ] Persist the user message, validated assistant message, citation rows, and model usage together after a successful run.
- [ ] Map authentication, ownership, validation, missing-record, Supabase, OpenAI, timeout, and unexpected failures to the documented HTTP or stream errors.
- [ ] Handle client cancellation and server timeouts without leaving a false completed assistant message.
- [ ] Confirm that follow-up questions use the saved conversation while retrieval stays focused on the new question.
- [ ] Add end-to-end backend integration coverage for one successful cited turn, one insufficient-evidence turn, one upstream failure, and one forbidden thread.

Phase complete when the real assistant completes reliable multi-turn conversations through the same path proven by the stub.

## 10. Finish the analyst chat experience

- [ ] Build the final thread sidebar, new-chat flow, thread titles, message list, composer, loading state, and empty state.
- [ ] Render assistant answers with citation markers beside the claims they support.
- [ ] Let a user open each citation and see the company, filing, date, page or section, exact excerpt, and SEC source link.
- [ ] Clearly distinguish a normal answer, an insufficient-evidence refusal, an investment-advice refusal, and a system error.
- [ ] Preserve useful draft and retry behavior when a network request fails.
- [ ] Add accessible labels, keyboard behavior, focus handling, readable contrast, and sensible desktop and narrow-browser layouts.
- [ ] Keep all backend calls in the shared API layer and all environment reads in `src/lib/env.ts`.
- [ ] Run `pnpm tsc --noEmit` and `pnpm lint`.
- [ ] Manually verify sign-in, sign-out, session expiry, thread ownership, streaming, citations, refresh, empty results, and failures in the browser.

Phase complete when an analyst can ask, verify, revisit, and continue a conversation without needing developer help.

## 11. Evaluate trust, security, and operating quality

- [ ] Expand the evaluation set with answerable, cross-company, multi-year, table-heavy, ambiguous, unsupported, and investment-advice questions.
- [ ] Record retrieval quality, citation validity, refusal correctness, answer usefulness, response time, and model cost for each evaluation run.
- [ ] Have a person verify that cited excerpts really support the nearby claims.
- [ ] Keep the fast backend test suite offline and database-free; keep live-service tests behind the `integration` marker.
- [ ] Run the required backend coverage for ingestion, retrieval, citation extraction, and grounding enforcement.
- [ ] Add request IDs and structured logs for authentication result, retrieval timing, model timing, token usage, validation result, and error class.
- [ ] Confirm that logs do not contain access tokens, service keys, or unnecessary document and chat contents.
- [ ] Review RLS policies, privileged writes, CORS origins, request-size limits, timeouts, and model token limits.
- [ ] Test with two real user accounts to prove that threads, messages, and citations cannot leak between users.
- [ ] Document how to rerun ingestion, change an embedding model, rebuild embeddings, apply migrations, and investigate a failed chat turn.

Phase complete when the evaluation results meet an agreed trust threshold and the security checks pass.

## 12. Deploy the pilot

- [ ] Create or prepare the production Supabase project and apply all Alembic migrations through the direct database connection.
- [ ] Configure production email authentication, redirect URLs, approved-user access, and RLS policies.
- [ ] Deploy the stateless FastAPI backend to Railway with its secrets, start command, health check, and logs.
- [ ] Deploy the built Vite SPA to a separate Railway frontend service with SPA route fallback enabled.
- [ ] Set the production API URL and exact CORS origin in the two services.
- [ ] Run the production ingestion command for the agreed pilot corpus.
- [ ] Smoke-test login, thread isolation, an answerable question, citation opening, an unsupported question, an advice refusal, refresh, and sign-out.
- [ ] Record the deployed versions, migration revision, embedding model, generation model, and ingestion run used by the pilot.
- [ ] Write a short operator guide for deployments, migrations, re-ingestion, log checks, and rollback.

Phase complete when the five-person pilot can use the production app with the complete sample corpus.

## 13. Run the pilot and decide on rollout

- [ ] Give the five senior analysts a short guide explaining the supported corpus, citation behavior, and known limits.
- [ ] Collect failed questions, incorrect retrievals, unsupported claims, confusing citations, usability issues, response times, and time saved.
- [ ] Review serious trust failures immediately and fix them before continuing the pilot.
- [ ] Compare pilot feedback with the target of at least three hours saved per analyst per week.
- [ ] Prioritize fixes using evidence from the pilot and rerun the evaluation set after every retrieval, prompt, or model change.
- [ ] If the target is met, plan the controlled expansion from the sample corpus to the agreed S&P 500 filings for 2020–2025.
- [ ] Re-test ingestion volume, index size, retrieval latency, OpenAI cost, and Railway capacity before firm-wide rollout.

The project is done when analysts can securely ask questions, receive answers supported by visible filing passages, revisit their conversations, and trust the system to refuse when the corpus does not support a claim—and the pilot shows the required time savings.
