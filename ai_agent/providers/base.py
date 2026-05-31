"""Abstract base class for all LLM provider implementations.

Adding a new provider (e.g. Anthropic, Cohere) requires only:
1. Creating a new subclass of LLMProvider
2. Registering it in providers/factory.py

No other code needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    """A single message in the conversation history."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMProvider(ABC):
    """Abstract interface that every LLM backend must implement."""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 512,
    ) -> str:
        """Send *messages* to the LLM and return the reply as plain text.

        Parameters
        ----------
        messages:
            Full conversation history including the system prompt, prior
            user/assistant turns, and the current user message.
        max_tokens:
            Upper bound on reply length.

        Returns
        -------
        str
            The assistant's reply text (stripped, non-empty).
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier, e.g. 'gemini', 'openai'."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The exact model string used in API calls."""
