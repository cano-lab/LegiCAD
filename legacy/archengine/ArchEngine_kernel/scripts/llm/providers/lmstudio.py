"""LM Studio local provider - OpenAI compatible API."""

import requests
from typing import List, Optional

from ..provider import LLMProvider, Message, LLMResponse


class LMStudioProvider(LLMProvider):
    """LM Studio local provider using OpenAI-compatible API."""

    def __init__(self, base_url: str = "http://localhost:1234/v1", model: str = None):
        """Initialize LM Studio provider.

        Args:
            base_url: LM Studio server URL (default: http://localhost:1234/v1)
            model: Model name (None = use whatever is loaded in LM Studio)
        """
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def name(self) -> str:
        return "LM Studio (Local)"

    def is_available(self) -> bool:
        """Check if LM Studio server is running."""
        try:
            response = requests.get(f"{self.base_url}/models", timeout=2)
            return response.status_code == 200
        except (requests.RequestException, Exception):
            return False

    def get_loaded_models(self) -> List[str]:
        """Get list of models loaded in LM Studio."""
        try:
            response = requests.get(f"{self.base_url}/models", timeout=5)
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except (requests.RequestException, Exception):
            return []

    def chat(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Send chat request to LM Studio.

        Args:
            messages: List of Message objects
            **kwargs: Optional parameters:
                - temperature: Sampling temperature (default: 0.7)
                - max_tokens: Maximum tokens to generate (default: 4096)
                - top_p: Top-p sampling (default: None)
                - stop: Stop sequences (default: None)

        Returns:
            LLMResponse with generated content

        Raises:
            requests.RequestException: If the request fails
            RuntimeError: If LM Studio is not available
        """
        if not self.is_available():
            raise RuntimeError("LM Studio server is not available")

        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if self.model:
            payload["model"] = self.model

        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        if "stop" in kwargs:
            payload["stop"] = kwargs["stop"]

        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=kwargs.get("timeout", 300)  # 5 minutes for large schemas
        )
        response.raise_for_status()
        data = response.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", "local"),
            usage=data.get("usage"),
            raw=data
        )
