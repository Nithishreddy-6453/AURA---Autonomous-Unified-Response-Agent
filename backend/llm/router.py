import os
from typing import Optional
from dotenv import load_dotenv

from backend.llm.base import LLMProvider
from backend.llm.ollama_provider import OllamaProvider
from backend.llm.gemini_provider import GeminiProvider

# Load environment variables from .env
load_dotenv()


def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """Factory function to resolve and instantiate the configured LLMProvider.

    Defaults to Ollama if LLM_PROVIDER is not explicitly configured.
    """
    provider_type = (provider_name or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()

    if provider_type == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
        return OllamaProvider(base_url=base_url, model=model)

    elif provider_type == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return GeminiProvider(api_key=api_key, model=model)

    else:
        raise ValueError(
            f"Unsupported LLM provider: '{provider_type}'. Supported providers are: 'ollama', 'gemini'."
        )
