from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from backend.llm.base import LLMProvider


class GeminiProvider(LLMProvider):
    """LLM provider implementation for Google Gemini models using the google-genai SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ):
        if not api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY in your environment or .env file."
            )
        self.model = model or "gemini-2.5-flash"
        self.client = genai.Client(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            **kwargs,
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            return response.text or ""
        except Exception as e:
            raise RuntimeError(
                f"Gemini provider failed to generate content (model: {self.model}): {e}"
            ) from e

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        # Convert standard OpenAI/Ollama messages [{role, content}] to contents representation
        contents: List[Any] = []
        system_instruction = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append(
                    types.Content(
                        role=gemini_role,
                        parts=[types.Part.from_text(text=content)],
                    )
                )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            **kwargs,
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            return response.text or ""
        except Exception as e:
            raise RuntimeError(
                f"Gemini provider failed in chat interaction (model: {self.model}): {e}"
            ) from e
