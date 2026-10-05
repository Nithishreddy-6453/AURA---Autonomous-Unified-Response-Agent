from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMProvider(ABC):
    """Abstract interface defining the contract for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """Generate text completion from a prompt asynchronously.

        Args:
            prompt: User prompt text.
            system_instruction: Optional system level instruction/persona.
            temperature: Sampling temperature.
            **kwargs: Provider-specific additional parameters.

        Returns:
            The response string from the model.
        """
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """Conduct chat conversation asynchronously.

        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            temperature: Sampling temperature.
            **kwargs: Provider-specific additional parameters.

        Returns:
            The response content from the model.
        """
        pass
