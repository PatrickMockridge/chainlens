# `chainlens.config`

Runtime configuration.

API keys are read **only** from the environment (or a local ``.env``), never from
function arguments. That matters for two reasons: a key passed as an argument
ends up in tracebacks, logs and notebook history, and a library that accepts keys
per call invites callers to scatter them through a codebase.

Keys are held as `pydantic.SecretStr`, so an accidental ``print(settings)``
or logging call renders ``**********`` rather than leaking the credential.

The library works with **no keys at all**: the default Bitcoin and Ethereum
providers use free public endpoints.

## `Settings`

Environment-backed settings.

Unknown environment variables are ignored, so the process environment can be
as noisy as it likes without breaking construction.

**Members**

- `model_config` = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore', case_sensitive=True, frozen=True, populate_by_name=True)
- `etherscan_api_key` = Field(default=None, validation_alias='ETHERSCAN_API_KEY')
- `blockchair_api_key` = Field(default=None, validation_alias='BLOCKCHAIR_API_KEY')
- `glassnode_api_key` = Field(default=None, validation_alias='GLASSNODE_API_KEY')
- `dune_api_key` = Field(default=None, validation_alias='DUNE_API_KEY')
- `nansen_api_key` = Field(default=None, validation_alias='NANSEN_API_KEY')
- `anthropic_api_key` = Field(default=None, validation_alias='ANTHROPIC_API_KEY')
- `anthropic_auth_token` = Field(default=None, validation_alias='ANTHROPIC_AUTH_TOKEN')
- `anthropic_base_url` = Field(default=_DEFAULT_MODEL_ENDPOINT, validation_alias='ANTHROPIC_BASE_URL')
- `eth_rpc_url` = Field(default=_DEFAULT_ETH_RPC_URL, validation_alias='CHAINLENS_ETH_RPC_URL')
- `cache_dir` = Field(default_factory=_default_cache_dir, validation_alias='CHAINLENS_CACHE_DIR')
- `cache_mode` = Field(default='live', validation_alias='CHAINLENS_CACHE_MODE')
- `disable_plugins` = Field(default=False, validation_alias='CHAINLENS_DISABLE_PLUGINS')
- `timeout_seconds` = Field(default=30.0, gt=0, validation_alias='CHAINLENS_TIMEOUT')
- `user_agent` = Field(default=_DEFAULT_USER_AGENT, validation_alias='CHAINLENS_USER_AGENT')

### `is_offline`

Whether the cache mode forbids live requests.

### `has_key`

```python
has_key(name: str) -> bool
```

Whether an API key is configured for the given logical provider name.

**Parameters**

- `name` `str` — one of ``etherscan``, ``blockchair``, ``glassnode``, ``dune``, ``nansen``.

### `api_key`

```python
api_key(name: str) -> str | None
```

Return the plaintext key for a provider, or ``None`` if unset.

Call this as late as possible and never log the result.

## `CacheMode`

## `get_settings`

```python
get_settings() -> Settings
```

Return process-wide settings, constructed once.

## `reset_settings_cache`

```python
reset_settings_cache() -> None
```

Clear the settings cache. For tests that mutate the environment.
