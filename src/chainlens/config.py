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
#: Where model calls go unless something says otherwise. See `anthropic_base_url` for why this is
#: a gateway rather than Anthropic's own endpoint, and what a caller should know about it.
_DEFAULT_MODEL_ENDPOINT = "https://api.deepseek.com/anthropic/"

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
        # Every field has a validation_alias, because the env var names are not
        # uniformly prefixed (api keys are bare ETHERSCAN_API_KEY, behaviour
        # settings are CHAINLENS_*). Without populate_by_name the field name is not
        # accepted as a keyword, so Settings(etherscan_api_key="...") would silently
        # produce None rather than the value — a footgun with no error to notice.
        populate_by_name=True,
    )

    # --- BYO-key providers. All optional: free providers need none of these. ---
    etherscan_api_key: SecretStr | None = Field(default=None, validation_alias="ETHERSCAN_API_KEY")
    blockchair_api_key: SecretStr | None = Field(
        default=None, validation_alias="BLOCKCHAIR_API_KEY"
    )
    glassnode_api_key: SecretStr | None = Field(default=None, validation_alias="GLASSNODE_API_KEY")
    dune_api_key: SecretStr | None = Field(default=None, validation_alias="DUNE_API_KEY")
    nansen_api_key: SecretStr | None = Field(default=None, validation_alias="NANSEN_API_KEY")
    #: Reading posts with a model. Named here rather than passed in, like every other credential:
    #: the library's public functions never take a key as a parameter, so there is nowhere for one
    #: to be logged, committed, or copied into a notebook.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    #: The other way of authenticating: a bearer token, which is what a gateway or a signed-in
    #: profile supplies. Both are read because both are in use, and a caller with only this one
    #: should not have to discover that the library wanted the other.
    anthropic_auth_token: SecretStr | None = Field(
        default=None, validation_alias="ANTHROPIC_AUTH_TOKEN"
    )
    #: Which endpoint answers model calls.
    #:
    #: **The shipped default is not Anthropic's API.** It is an Anthropic-*compatible* gateway,
    #: because that is what this project has access to and a default nobody can run is not a
    #: default. Two consequences a caller should know rather than discover: text sent for
    #: extraction leaves for that host and not for Anthropic, and it is somebody else's service
    #: with its own model and terms. Set `ANTHROPIC_BASE_URL` — or this setting — to point at
    #: Anthropic or at a local gateway; the SDK's own `ANTHROPIC_BASE_URL` is read through the same
    #: alias, so an environment that already sets it keeps winning over the default here.
    #:
    #: It also **does not honour the structured-output schema** a model call declares — measured,
    #: not inferred: asked for a shape with two required fields it answered `Hello!`. The prompt
    #: carries the shape because of that, and the library validates the answer itself, which is what
    #: makes a non-conforming endpoint cost a refusal rather than a claim. Anthropic's own API
    #: enforces the schema, so pointing here at it is a strictly stronger arrangement.
    anthropic_base_url: str = Field(
        default=_DEFAULT_MODEL_ENDPOINT, validation_alias="ANTHROPIC_BASE_URL"
    )

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
