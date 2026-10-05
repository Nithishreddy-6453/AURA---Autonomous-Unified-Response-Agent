from typing import Any, Dict, List, Optional
import httpx
import ollama
from ollama import AsyncClient

from backend.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    """LLM provider implementation for local Ollama instances."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5-coder:14b",
    ):
        self.base_url = base_url.rstrip("/") if base_url else "http://localhost:11434"
        self.model = model or "qwen2.5-coder:14b"
        self.client = AsyncClient(host=self.base_url)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        options = kwargs.pop("options", {})
        if "temperature" not in options:
            options["temperature"] = temperature

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=prompt,
                system=system_instruction,
                options=options,
                **kwargs,
            )
            return response.get("response", "") if isinstance(response, dict) else response.response
        except (ollama.ResponseError, httpx.RequestError, ConnectionError, OSError) as e:
            raise RuntimeError(
                f"Ollama provider failed to connect or respond at {self.base_url} (model: {self.model}): {e}"
            ) from e

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        options = kwargs.pop("options", {})
        if "temperature" not in options:
            options["temperature"] = temperature

        try:
            response = await self.client.chat(
                model=self.model,
                messages=messages,
                options=options,
                **kwargs,
            )
            msg = response.get("message", {}) if isinstance(response, dict) else response.message
            if isinstance(msg, dict):
                return msg.get("content", "")
            return getattr(msg, "content", "")
        except (ollama.ResponseError, httpx.RequestError, ConnectionError, OSError) as e:
            raise RuntimeError(
                f"Ollama provider failed to connect or respond at {self.base_url} (model: {self.model}): {e}"
            ) from e
