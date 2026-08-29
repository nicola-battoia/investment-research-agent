"""Validated environment settings and backend runtime tuning."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    # Supabase project endpoint used by all authenticated and admin database clients.
    supabase_url: AnyHttpUrl
    # Browser-safe key used by request-scoped Supabase clients with user auth.
    supabase_anon_key: SecretStr
    # Privileged key used only for server-side ownership and maintenance queries.
    supabase_service_role_key: SecretStr
    # Direct Psycopg connection used by Alembic migrations.
    database_url: SecretStr
    # Shared Supabase transport deadlines for connection acquisition and I/O.
    supabase_http_connect_timeout_seconds: PositiveFloat = 5
    supabase_http_read_timeout_seconds: PositiveFloat = 15
    supabase_http_write_timeout_seconds: PositiveFloat = 15
    supabase_http_pool_timeout_seconds: PositiveFloat = 5

    # Azure OpenAI-compatible v1 endpoint shared by every model workload.
    azure_openai_endpoint: AnyHttpUrl
    # Credential for the parent Azure AI Foundry resource.
    azure_openai_api_key: SecretStr
    # Azure deployment used by the grounded research assistant.
    azure_openai_assistant_deployment: str
    # Azure deployment used for typed keyword extraction.
    azure_openai_keyword_deployment: str
    # Azure deployment used for query and ingestion embeddings.
    azure_openai_embedding_deployment: str
    # Retry count used by the shared Azure OpenAI HTTP client.
    azure_openai_http_max_retries: NonNegativeInt = 3
    # Embedding model used for semantic retrieval queries and ingestion.
    openai_embedding_model: str
    # Vector width used by OpenAI and the document_chunks embedding column.
    openai_embedding_dimensions: PositiveInt
    # Model that turns questions into bounded lexical search concepts.
    openai_keyword_model: str
    # Maximum tokens returned by one keyword-extraction request.
    openai_keyword_max_output_tokens: PositiveInt = 800
    # Main model used to plan research and produce the grounded answer.
    openai_assistant_model: str
    # Reasoning effort sent with each main assistant model request.
    openai_assistant_reasoning_effort: Literal[
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    # Per-request response cap sent to the main assistant model.
    openai_assistant_max_output_tokens: PositiveInt = 2500

    # Maximum model requests allowed across one assistant run, including retries.
    assistant_max_model_requests: PositiveInt = 10
    # Maximum total tool invocations allowed across one assistant run.
    assistant_max_tool_calls: PositiveInt = 8
    # Cumulative output-token ceiling across all model requests in one run.
    assistant_max_total_output_tokens: PositiveInt = 10_000
    # Cumulative input-token ceiling across all model requests in one run.
    assistant_max_total_input_tokens: PositiveInt = 75_000
    # Input-token ceiling applied separately to every model request.
    assistant_max_request_input_tokens: PositiveInt = 50_000
    # Shared character ceiling for user questions, answers, and stored history messages.
    assistant_max_message_characters: PositiveInt = 10_000
    # Number of automatic retries allowed after tool validation or execution errors.
    assistant_tool_retries: NonNegativeInt = 1
    # Number of correction attempts allowed after invalid structured/grounded output.
    assistant_output_retries: NonNegativeInt = 1
    # Deadline in seconds for one assistant tool invocation.
    assistant_tool_timeout_seconds: PositiveFloat = 120
    # Whether the main model may request multiple tool calls concurrently.
    assistant_parallel_tool_calls: bool = False
    # Whether OpenAI may retain assistant and keyword-extraction responses.
    openai_store_responses: bool = False
    # Response verbosity requested from the main assistant model.
    assistant_text_verbosity: Literal["low", "medium", "high"] = "low"

    # Maximum recent complete user/assistant pairs supplied as model history.
    assistant_max_history_turns: PositiveInt = 5
    # Maximum combined characters supplied as model history.
    assistant_max_history_characters: PositiveInt = 20_000
    # Maximum unique passages that may be registered as evidence in one turn.
    assistant_max_turn_evidence: PositiveInt = 150
    # Characters from each retrieved passage exposed in search-result previews.
    assistant_evidence_preview_characters: PositiveInt = 400

    # Maximum filing-search tool calls the model may make in one turn.
    assistant_max_search_calls: PositiveInt = 5
    # Maximum surrounding-chunk tool calls the model may make in one turn.
    assistant_max_surrounding_calls: PositiveInt = 2
    # Ranked passages returned to the model by each filing search.
    assistant_search_result_limit: PositiveInt = 10
    # Candidates fetched per retrieval branch for each model-controlled search.
    assistant_search_candidate_limit: PositiveInt = 50
    # Character ceiling for a model-generated filing-search query.
    assistant_max_search_query_characters: PositiveInt = 500
    # Number of adjacent chunk positions inspected on each side of an anchor.
    assistant_surrounding_chunk_radius: PositiveInt = 1
    # Maximum neighboring chunks returned by one surrounding-chunk tool call.
    assistant_max_surrounding_chunks: PositiveInt = 2
    # Maximum company filters accepted by one filing-search tool call.
    assistant_max_filter_companies: PositiveInt = 5
    # Maximum ticker filters accepted by one filing-search tool call.
    assistant_max_filter_tickers: PositiveInt = 5
    # Maximum filing-form filters accepted by one filing-search tool call.
    assistant_max_filter_filing_types: PositiveInt = 3
    # Maximum filing-year filters accepted by one filing-search tool call.
    assistant_max_filter_filing_years: PositiveInt = 5

    # Maximum answer characters for conversational and out-of-scope responses.
    assistant_max_non_retrieval_answer_characters: PositiveInt = 1_000
    # Maximum citations accepted in one structured assistant answer.
    assistant_max_citations: PositiveInt = 20
    # Minimum copied characters required in a citation excerpt.
    citation_excerpt_min_characters: PositiveInt = 20
    # Maximum copied characters accepted in a citation excerpt.
    citation_excerpt_max_characters: PositiveInt = 500

    # Default number of fused passages returned by direct retriever calls.
    retrieval_default_result_limit: PositiveInt = 10
    # Hard ceiling for fused passages returned by the retriever.
    retrieval_max_result_limit: PositiveInt = 20
    # Default candidates fetched independently by semantic and lexical branches.
    retrieval_default_candidate_limit: PositiveInt = 50
    # Hard candidate ceiling enforced before Supabase retrieval RPCs.
    retrieval_max_candidate_limit: PositiveInt = 100
    # Semantic branch multiplier used by reciprocal-rank fusion.
    retrieval_semantic_weight: NonNegativeFloat = 20.0
    # Lexical branch multiplier used by reciprocal-rank fusion.
    retrieval_lexical_weight: NonNegativeFloat = 1.0
    # Fusion weight assigned to a ranking branch without an explicit multiplier.
    retrieval_unconfigured_branch_weight: NonNegativeFloat = 1.0
    # Smoothing constant in reciprocal-rank fusion; larger values flatten rank gaps.
    retrieval_rrf_k: PositiveInt = 60
    # Earliest filing year accepted by retrieval filters.
    retrieval_min_filing_year: PositiveInt = 1_900
    # Latest filing year accepted by retrieval filters.
    retrieval_max_filing_year: PositiveInt = 2_100
    # Maximum distinct concepts produced by keyword extraction.
    retrieval_keyword_max_groups: PositiveInt = 6
    # Maximum close lexical forms allowed in one keyword concept.
    retrieval_keyword_max_terms_per_group: PositiveInt = 3
    # Maximum characters allowed in one extracted keyword or phrase.
    retrieval_keyword_max_term_characters: PositiveInt = 80
    # Maximum words requested in each extracted keyword phrase.
    retrieval_keyword_max_phrase_words: PositiveInt = 4

    # Hard deadline for retrieval, agent execution, validation, and persistence.
    chat_turn_timeout_seconds: PositiveInt = 180
    # Interval between streamed status heartbeats while a turn is running.
    chat_stream_heartbeat_seconds: PositiveFloat = 15
    # Characters emitted in each assistant text-delta stream event.
    chat_stream_text_delta_characters: PositiveInt = 160
    # Maximum characters generated for the automatic first-turn thread title.
    chat_auto_title_max_characters: PositiveInt = 60
    # Database and API character ceiling for user-supplied thread titles.
    chat_thread_title_max_characters: PositiveInt = 200
    # Default title assigned before the first completed assistant turn.
    chat_default_thread_title: str = "New chat"
    # Character ceiling for frontend-generated client message IDs.
    chat_client_message_id_max_characters: PositiveInt = 200

    # Explicit runtime profile used to enforce safe logging combinations.
    app_environment: Literal["development", "test", "production"]
    # Application log severity threshold.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Structured production logs or readable local console logs.
    log_format: Literal["json", "console"] = "json"
    # Assistant diagnostic detail: disabled, bounded summaries, or full content.
    assistant_trace_mode: Literal["off", "summary", "full"] = "summary"
    # Maximum characters retained for one content value in full assistant traces.
    assistant_trace_max_content_characters: PositiveInt = 12_000
    # Hard byte ceiling for one production JSON event.
    log_max_event_bytes: Annotated[int, Field(ge=1_024, le=65_536)] = 4_096
    # Browser origins permitted to call the API through CORS.
    allowed_origins: Annotated[tuple[AnyHttpUrl, ...], NoDecode]

    @field_validator("database_url")
    @classmethod
    def require_psycopg_3(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+psycopg:// for Psycopg 3"
            )
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_allowed_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(
                origin.strip() for origin in value.split(",") if origin.strip()
            )
        return value

    @field_validator("azure_openai_endpoint")
    @classmethod
    def require_azure_openai_v1_endpoint(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if not str(value).rstrip("/").endswith("/openai/v1"):
            raise ValueError("AZURE_OPENAI_ENDPOINT must end with /openai/v1/")
        return value

    @field_validator(
        "azure_openai_assistant_deployment",
        "azure_openai_keyword_deployment",
        "azure_openai_embedding_deployment",
    )
    @classmethod
    def require_azure_deployment_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Azure deployment names cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_tuning_relationships(self) -> Self:
        if self.app_environment == "production":
            if self.log_format != "json":
                raise ValueError("Production logging requires LOG_FORMAT=json")
            if self.assistant_trace_mode == "full":
                raise ValueError(
                    "Production logging cannot use ASSISTANT_TRACE_MODE=full"
                )
        if (
            self.openai_assistant_max_output_tokens
            > self.assistant_max_total_output_tokens
        ):
            raise ValueError(
                "OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS cannot exceed "
                "ASSISTANT_MAX_TOTAL_OUTPUT_TOKENS"
            )
        if (
            self.assistant_max_request_input_tokens
            > self.assistant_max_total_input_tokens
        ):
            raise ValueError(
                "ASSISTANT_MAX_REQUEST_INPUT_TOKENS cannot exceed "
                "ASSISTANT_MAX_TOTAL_INPUT_TOKENS"
            )
        if (
            self.assistant_max_non_retrieval_answer_characters
            > self.assistant_max_message_characters
        ):
            raise ValueError(
                "ASSISTANT_MAX_NON_RETRIEVAL_ANSWER_CHARACTERS cannot exceed "
                "ASSISTANT_MAX_MESSAGE_CHARACTERS"
            )
        if self.citation_excerpt_min_characters > self.citation_excerpt_max_characters:
            raise ValueError(
                "CITATION_EXCERPT_MIN_CHARACTERS cannot exceed "
                "CITATION_EXCERPT_MAX_CHARACTERS"
            )
        if self.retrieval_default_result_limit > self.retrieval_max_result_limit:
            raise ValueError(
                "RETRIEVAL_DEFAULT_RESULT_LIMIT cannot exceed "
                "RETRIEVAL_MAX_RESULT_LIMIT"
            )
        if self.retrieval_max_result_limit > self.retrieval_max_candidate_limit:
            raise ValueError(
                "RETRIEVAL_MAX_RESULT_LIMIT cannot exceed RETRIEVAL_MAX_CANDIDATE_LIMIT"
            )
        candidate_limits = (
            self.retrieval_default_candidate_limit,
            self.assistant_search_candidate_limit,
        )
        if any(
            limit > self.retrieval_max_candidate_limit for limit in candidate_limits
        ):
            raise ValueError(
                "Default and assistant candidate limits cannot exceed "
                "RETRIEVAL_MAX_CANDIDATE_LIMIT"
            )
        if self.retrieval_default_candidate_limit < self.retrieval_default_result_limit:
            raise ValueError(
                "RETRIEVAL_DEFAULT_CANDIDATE_LIMIT cannot be below "
                "RETRIEVAL_DEFAULT_RESULT_LIMIT"
            )
        if self.assistant_search_result_limit > self.retrieval_max_result_limit:
            raise ValueError(
                "ASSISTANT_SEARCH_RESULT_LIMIT cannot exceed RETRIEVAL_MAX_RESULT_LIMIT"
            )
        if self.assistant_search_candidate_limit < self.assistant_search_result_limit:
            raise ValueError(
                "ASSISTANT_SEARCH_CANDIDATE_LIMIT cannot be below "
                "ASSISTANT_SEARCH_RESULT_LIMIT"
            )
        if (
            self.assistant_max_search_calls + self.assistant_max_surrounding_calls
            > self.assistant_max_tool_calls
        ):
            raise ValueError(
                "Assistant search and surrounding-call limits cannot exceed "
                "ASSISTANT_MAX_TOOL_CALLS in total"
            )
        if self.assistant_search_result_limit > self.assistant_max_turn_evidence:
            raise ValueError(
                "ASSISTANT_SEARCH_RESULT_LIMIT cannot exceed "
                "ASSISTANT_MAX_TURN_EVIDENCE"
            )
        if self.assistant_max_citations > self.assistant_max_turn_evidence:
            raise ValueError(
                "ASSISTANT_MAX_CITATIONS cannot exceed ASSISTANT_MAX_TURN_EVIDENCE"
            )
        if (
            self.assistant_max_surrounding_chunks
            > self.assistant_surrounding_chunk_radius * 2
        ):
            raise ValueError(
                "ASSISTANT_MAX_SURROUNDING_CHUNKS cannot exceed both sides of "
                "ASSISTANT_SURROUNDING_CHUNK_RADIUS"
            )
        if self.retrieval_semantic_weight == self.retrieval_lexical_weight == 0:
            raise ValueError("At least one retrieval fusion weight must be positive")
        if self.retrieval_min_filing_year > self.retrieval_max_filing_year:
            raise ValueError(
                "RETRIEVAL_MIN_FILING_YEAR cannot exceed RETRIEVAL_MAX_FILING_YEAR"
            )
        if self.chat_auto_title_max_characters > self.chat_thread_title_max_characters:
            raise ValueError(
                "CHAT_AUTO_TITLE_MAX_CHARACTERS cannot exceed "
                "CHAT_THREAD_TITLE_MAX_CHARACTERS"
            )
        if not self.chat_default_thread_title.strip():
            raise ValueError("CHAT_DEFAULT_THREAD_TITLE cannot be empty")
        if len(self.chat_default_thread_title) > self.chat_thread_title_max_characters:
            raise ValueError(
                "CHAT_DEFAULT_THREAD_TITLE cannot exceed "
                "CHAT_THREAD_TITLE_MAX_CHARACTERS"
            )
        return self


settings = Settings()
