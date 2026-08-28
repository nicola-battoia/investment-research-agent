"""Azure-compatible Responses model with local pre-request token estimates."""

from __future__ import annotations

import dataclasses
import json
import math
from enum import Enum
from typing import cast

from openai import Omit
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import (
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

_ESTIMATED_ASCII_CHARACTERS_PER_TOKEN = 5
_ESTIMATED_NON_ASCII_TOKENS_PER_CHARACTER = 4
_REQUEST_OVERHEAD_TOKENS = 512


class AzureResponsesModel(OpenAIResponsesModel):
    """Estimate input locally because Azure does not expose Responses token count."""

    async def count_tokens(
        self,
        messages: list[ModelRequest | ModelResponse],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        prepared_settings, prepared_parameters = self.prepare_request(
            model_settings,
            model_request_parameters,
        )
        settings = cast(OpenAIResponsesModelSettings, prepared_settings or {})
        request = await self._build_responses_request_params(
            messages,
            settings,
            prepared_parameters,
            self.profile,
        )
        payload = {
            field.name: value
            for field in dataclasses.fields(request)
            if not isinstance((value := getattr(request, field.name)), Omit)
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        non_ascii_characters = sum(not character.isascii() for character in serialized)
        ascii_characters = len(serialized) - non_ascii_characters
        return RequestUsage(
            input_tokens=(
                math.ceil(ascii_characters / _ESTIMATED_ASCII_CHARACTERS_PER_TOKEN)
                + non_ascii_characters * _ESTIMATED_NON_ASCII_TOKENS_PER_CHARACTER
                + _REQUEST_OVERHEAD_TOKENS
            )
        )


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot estimate tokens for {type(value).__name__}")
