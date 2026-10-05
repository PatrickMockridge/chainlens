"""Runtime configuration.

API keys are read **only** from the environment (or a local ``.env``), never from
function arguments. That matters for two reasons: a key passed as an argument
ends up in tracebacks, logs and notebook history, and a library that accepts keys
per call invites callers to scatter them through a codebase.

Keys are held as :class:`~pydantic.SecretStr`, so an accidental ``print(settings)``
or logging call renders ``**********`` rather than leaking the credential.

The library works with **no keys at all**: the default Bitcoin and Ethereum
providers use free public endpoints.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["CacheMode", "Settings", "get_settings", "reset_settings_cache"]

#: ``live`` uses the HTTP cache per RFC 9111 and may revalidate against the
#: network. ``offline`` refuses to touch the network at all: anything cached is
#: served, anything else raises. There is no separate "replay" mode because with
#: a store-then-serve cache it would be indistinguishable from ``offline``.
CacheMode = Literal["live", "offline"]

_DEFAULT_ETH_RPC_URL = "https://eth.llamarpc.com"
_DEFAULT_USER_AGENT = "chainlens (+https://github.com/PatrickMockridge/chainlens)"


def _default_cache_dir() -> Path:
    """XDG cache location, without taking a dependency on platformdirs."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "chainlens"


class Settings(BaseSettings):
    """Environment-backed settings.

    Unknown environment variables are ignored, so the process environment can be
    as noisy as it likes without breaking construction.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        frozen=True,
    )

    # --- BYO-key providers. All optional: free providers need none of these. ---
    etherscan_api_key: SecretStr | None = Field(default=None, validation_alias="ETHERSCAN_API_KEY")
    blockchair_api_key: SecretStr | None = Field(
        default=None, validation_alias="BLOCKCHAIR_API_KEY"
    )
    glassnode_api_key: SecretStr | None = Field(default=None, validation_alias="GLASSNODE_API_KEY")
    dune_api_key: SecretStr | None = Field(default=None, validation_alias="DUNE_API_KEY")
    nansen_api_key: SecretStr | None = Field(default=None, validation_alias="NANSEN_API_KEY")

    # --- Behaviour ---
    eth_rpc_url: str = Field(default=_DEFAULT_ETH_RPC_URL, validation_alias="CHAINLENS_ETH_RPC_URL")
    cache_dir: Path = Field(
        default_factory=_default_cache_dir, validation_alias="CHAINLENS_CACHE_DIR"
    )
    cache_mode: CacheMode = Field(default="live", validation_alias="CHAINLENS_CACHE_MODE")
    disable_plugins: bool = Field(default=False, validation_alias="CHAINLENS_DISABLE_PLUGINS")

    timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="CHAINLENS_TIMEOUT")
    user_agent: str = Field(default=_DEFAULT_USER_AGENT, validation_alias="CHAINLENS_USER_AGENT")

    @property
    def is_offline(self) -> bool:
        """Whether the cache mode forbids live requests."""
        return self.cache_mode == "offline"

    def has_key(self, name: str) -> bool:
        """Whether an API key is configured for the given logical provider name.

        Args:
            name: one of ``etherscan``, ``blockchair``, ``glassnode``, ``dune``,
                ``nansen``.
        """
        field = f"{name}_api_key"
        if field not in type(self).model_fields:
            raise ValueError(f"unknown provider key name {name!r}")
        return getattr(self, field) is not None

    def api_key(self, name: str) -> str | None:
        """Return the plaintext key for a provider, or ``None`` if unset.

        Call this as late as possible and never log the result.
        """
        field = f"{name}_api_key"
        if field not in type(self).model_fields:
            raise ValueError(f"unknown provider key name {name!r}")
        secret: SecretStr | None = getattr(self, field)
        return secret.get_secret_value() if secret is not None else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings, constructed once."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache. For tests that mutate the environment."""
    get_settings.cache_clear()
