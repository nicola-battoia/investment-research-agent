"""Shared Azure AI Foundry connection for OpenAI-compatible model calls."""

from typing import Self

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import Settings


class AzureOpenAIService:
    """Own one async Azure OpenAI v1 client and its PydanticAI model adapter."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or AsyncOpenAI(
            base_url=str(settings.azure_openai_endpoint),
            api_key=settings.azure_openai_api_key.get_secret_value(),
            max_retries=settings.azure_openai_http_max_retries,
        )

    @property
    def client(self) -> AsyncOpenAI:
        """Return the shared client for Responses and embedding requests."""
        return self._client

    def create_responses_model(
        self,
        deployment: str,
        underlying_model: str,
    ) -> OpenAIResponsesModel:
        """Create a PydanticAI Responses model routed to an Azure deployment."""
        return OpenAIResponsesModel(
            deployment,
            provider=OpenAIProvider(openai_client=self._client),
            profile=AzureProvider.model_profile(underlying_model),
        )

    async def close(self) -> None:
        """Close the client only when this service created it."""
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()
