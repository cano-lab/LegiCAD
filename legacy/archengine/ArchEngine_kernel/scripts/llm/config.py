"""LLM provider configuration and management."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

from .provider import LLMProvider
from .providers.lmstudio import LMStudioProvider
from .providers.openai import OpenAIProvider
from .providers.anthropic import AnthropicProvider
from .providers.google import GoogleProvider


class LLMConfig:
    """Manage LLM provider configuration."""

    _providers: Dict[str, LLMProvider] = {}
    _active: Optional[str] = None
    _initialized: bool = False

    @classmethod
    def register_defaults(cls):
        """Register default providers."""
        cls._providers = {
            "lmstudio": LMStudioProvider(),
            "openai": OpenAIProvider(),
            "claude": AnthropicProvider(),
            "gemini": GoogleProvider(),
        }
        cls._initialized = True

        # Load user config if exists
        cls._load_user_config()

    @classmethod
    def _load_user_config(cls):
        """Load user configuration from ~/.archengine/llm_config.json."""
        config_path = Path.home() / ".archengine" / "llm_config.json"
        if not config_path.exists():
            return

        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            # Apply provider-specific configs
            providers_config = config.get("providers", {})

            if "lmstudio" in providers_config:
                lm_cfg = providers_config["lmstudio"]
                cls._providers["lmstudio"] = LMStudioProvider(
                    base_url=lm_cfg.get("base_url", "http://localhost:1234/v1"),
                    model=lm_cfg.get("model")
                )

            if "openai" in providers_config:
                oa_cfg = providers_config["openai"]
                cls._providers["openai"] = OpenAIProvider(
                    api_key=oa_cfg.get("api_key"),
                    model=oa_cfg.get("model", "gpt-4o")
                )

            if "claude" in providers_config:
                cl_cfg = providers_config["claude"]
                cls._providers["claude"] = AnthropicProvider(
                    api_key=cl_cfg.get("api_key"),
                    model=cl_cfg.get("model", "claude-sonnet-4-20250514")
                )

            if "gemini" in providers_config:
                gm_cfg = providers_config["gemini"]
                cls._providers["gemini"] = GoogleProvider(
                    api_key=gm_cfg.get("api_key"),
                    model=gm_cfg.get("model", "gemini-1.5-pro")
                )

            # Set active provider from config
            if "active_provider" in config:
                cls._active = config["active_provider"]

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load LLM config: {e}")

    @classmethod
    def save_user_config(cls):
        """Save current configuration to ~/.archengine/llm_config.json."""
        config_dir = Path.home() / ".archengine"
        config_dir.mkdir(exist_ok=True)
        config_path = config_dir / "llm_config.json"

        config = {
            "active_provider": cls._active,
            "providers": {}
        }

        # Save provider configs (without API keys for security)
        if "lmstudio" in cls._providers:
            p = cls._providers["lmstudio"]
            config["providers"]["lmstudio"] = {
                "base_url": p.base_url,
                "model": p.model
            }

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    @classmethod
    def get_provider(cls, name: str) -> Optional[LLMProvider]:
        """Get a specific provider by name."""
        if not cls._initialized:
            cls.register_defaults()
        return cls._providers.get(name)

    @classmethod
    def get_all(cls) -> Dict[str, LLMProvider]:
        """Get all registered providers."""
        if not cls._initialized:
            cls.register_defaults()
        return cls._providers.copy()

    @classmethod
    def get_available(cls) -> Dict[str, LLMProvider]:
        """Get all available (configured) providers."""
        if not cls._initialized:
            cls.register_defaults()
        return {k: v for k, v in cls._providers.items() if v.is_available()}

    @classmethod
    def get_active(cls) -> Optional[LLMProvider]:
        """Get the active provider."""
        if not cls._initialized:
            cls.register_defaults()

        if cls._active and cls._active in cls._providers:
            provider = cls._providers[cls._active]
            if provider.is_available():
                return provider

        # Auto-select first available
        available = cls.get_available()
        if available:
            cls._active = list(available.keys())[0]
            return available[cls._active]

        return None

    @classmethod
    def set_active(cls, name: str) -> bool:
        """Set the active provider by name.

        Args:
            name: Provider name (lmstudio, openai, claude, gemini)

        Returns:
            True if provider was set, False if not found
        """
        if not cls._initialized:
            cls.register_defaults()

        if name in cls._providers:
            cls._active = name
            return True
        return False

    @classmethod
    def register_provider(cls, name: str, provider: LLMProvider):
        """Register a custom provider.

        Args:
            name: Provider name
            provider: LLMProvider instance
        """
        if not cls._initialized:
            cls.register_defaults()
        cls._providers[name] = provider

    @classmethod
    def status(cls) -> Dict[str, Any]:
        """Get status of all providers.

        Returns:
            Dict with provider status information
        """
        if not cls._initialized:
            cls.register_defaults()

        # Trigger auto-selection if no active provider
        active_provider = cls.get_active()
        active_name = cls._active

        status = {
            "active": active_name,
            "providers": {}
        }

        for name, provider in cls._providers.items():
            available = provider.is_available()
            status["providers"][name] = {
                "name": provider.name,
                "available": available,
                "active": name == active_name
            }

        return status
