# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Report privately via
GitHub's [Security Advisories](https://github.com/PatrickMockridge/chainlens/security/advisories/new),
or email the maintainer listed in `pyproject.toml`.

Include a description, reproduction steps, and the affected version. You can expect an
acknowledgement within a few days.

## What counts as a security issue here

`chainlens` is a read-only analysis library: it does not sign transactions, hold keys,
or move funds. The realistic security surface is therefore narrow but not empty:

- **Credential leakage.** Provider API keys are read from the environment / settings,
  never from function arguments, and must not appear in logs, exceptions, cache
  filenames, or recorded test fixtures. A key escaping into a log line or a cassette is
  a security bug — please report it.
- **Untrusted-input parsing.** Malformed or hostile provider responses must not cause
  code execution, unbounded memory growth, or path traversal via cache keys. Parsing
  bugs that escalate beyond a raised exception are security bugs.
- **Dependency supply chain.** Issues in pinned dependencies (`httpx`, `hishel`,
  `pydantic`, `rustworkx`, ...) that affect us.

## Out of scope

- Misuse of the library for unlawful surveillance or harassment. That is a violation of
  the licence's spirit and the project's intent, but it is not a vulnerability in this
  codebase.
- The accuracy of chain-analysis heuristics. False positives are a documented,
  expected property of on-chain clustering, not a security defect — see
  `docs/explanation/forensic-limits.md`.
