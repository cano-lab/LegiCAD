"""Google Gemini API provider."""

import os
from typing import List

import requests

from ..provider import LLMProvider, Message, LLMResponse


class GoogleProvider(LLMProvider):
    """Google Gemini API provider."""

    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str = None, model: str = "gemini-1.5-pro"):
        """Initialize Google provider.

        Args:
            api_key: Google API key (default: from GOOGLE_API_KEY env var)
            model: Model to use (default: gemini-1.5-pro)
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model

    @property
    def name(self) -> str:
        return f"Gemini ({self.model})"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    def chat(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Send chat request to Google Gemini API.

        Args:
            messages: List of Message objects
            **kwargs: Optional parameters:
                - temperature: Sampling temperature (default: 0.7)
                - max_tokens: Maximum tokens to generate (default: 4096)
                - top_p: Top-p sampling (default: None)
                - stop_sequences: Stop sequences (default: None)

        Returns:
            LLMResponse with generated content

        Raises:
            requests.RequestException: If the request fails
            RuntimeError: If API key is not configured
        """
        if not self.api_key:
            raise RuntimeError("Google API key not configured")

        # Convert messages to Gemini format
        # Gemini uses "user" and "model" roles, system is prepended to first user message
        system_content = ""
        contents = []

        for m in messages:
            if m.role == "system":
                system_content = m.content
            elif m.role == "user":
                content = m.content
                if system_content and not contents:
                    # Prepend system to first user message
                    content = f"{system_content}\n\n{content}"
                    system_content = ""
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}]
                })
            elif m.role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": m.content}]
                })

        generation_config = {
            "temperature": kwargs.get("temperature", 0.7),
            "maxOutputTokens": kwargs.get("max_tokens", 4096),
        }

        if "top_p" in kwargs:
            generation_config["topP"] = kwargs["top_p"]

        if "stop_sequences" in kwargs:
            generation_config["stopSequences"] = kwargs["stop_sequences"]

        payload = {
            "contents": contents,
            "generationConfig": generation_config
        }

        url = f"{self.API_BASE}/{self.model}:generateContent?key={self.api_key}"

        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=kwargs.get("timeout", 120)
        )
        response.raise_for_status()
        data = response.json()

        # Extract text from response
        content = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content += part["text"]

        # Extract usage metadata
        usage = None
        usage_metadata = data.get("usageMetadata")
        if usage_metadata:
            usage = {
                "input": usage_metadata.get("promptTokenCount", 0),
                "output": usage_metadata.get("candidatesTokenCount", 0)
            }

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            raw=data
        )
