#!/usr/bin/env python3
"""Is the httpx pre-release breaking this library, or something it depends on?

    python tools/check_httpx_prerelease.py

The `httpx-prerelease` CI job exists to answer one question: **will httpx 1.0 break chainlens?**
Its first version could not, and returned the same red mark for both answers — because test
collection dies on `respx` before any chainlens module is imported, so a dependency's
incompatibility and this library's own looked identical from outside.

A check that is red on every commit is a check people stop reading, which is worse than not having
one. So this separates the two, and the job is green exactly while the breakage is somebody
else's.

**How it decides.** It imports `chainlens.providers.transport` — the one module that owns every
httpx name this library uses — in a subprocess, and looks at the **last** frame of the traceback.
That frame is the line that raised:

* the last frame under a `chainlens/` path → **this library's** code needs migrating
* the last frame under anything else → a dependency has not caught up
* no failure at all → the library imports; the suite then runs, and its status stands

The *last* frame and not "any frame", and that distinction is the whole tool. `transport.py`
appears in the traceback either way, because when a dependency is missing the failing line is
*inside* it — `from hishel.httpx import ...` at line 33. Only the frame that raised says whose
fault it is.

**Three libs, measured against httpx 1.0.dev6 (2026-10-08).** `hishel` 1.4.0, a core dependency,
dies on `ImportError: cannot import name 'RequestNotRead' from 'httpx'`. `respx`, a dev-only test
dependency, dies on `no attribute 'BaseTransport'`. And `providers/transport.py` uses
`httpx.AsyncBaseTransport`, which 1.0 renamed to `Transport` — the one that is ours, and one this
job cannot report until the other two are out of the way.

Exit status:
    0   the library imports, or does not import for a reason outside this repository
    1   the failure is this library's own code
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

#: The module whose import answers the question. Every httpx name this library uses is here, and
#: `providers/transport.py` says so in its own docstring: *"only this module imports httpx."*
PROBE = "import chainlens.providers.transport"

#: A traceback frame. `File "path", line N, in name`.
_FRAME = re.compile(r'^\s*File "(?P<path>[^"]+)"', re.MULTILINE)

#: Where an installed copy of this package lives, as a fallback for when its path cannot be read.
#: **A bare `chainlens/` is not good enough and a test caught that**: a checkout at
#: `/home/x/chainlens/` puts the name in the path of *every* dependency's frames, so
#: `.../chainlens/.venv/lib/site-packages/somepkg/__init__.py` read as ours. What identifies the
#: package is the directory a module of *ours* sits in, which is one of these two.
INSTALLED_MARKERS = ("/site-packages/chainlens/", "/src/chainlens/")


def package_root() -> str | None:
    """The directory this library's modules live in, or ``None`` if it cannot be imported.

    Read from the import rather than inferred from a path shape, so a checkout named `chainlens`
    is not mistaken for the package. ``None`` happens when the probe is being run against the
    library itself and the library is what is broken — which is why the markers above still exist.
    """
    try:
        import chainlens
    except ImportError:  # pragma: no cover - the tool imports in any environment it is run in
        return None
    path = getattr(chainlens, "__file__", None)
    return str(Path(path).parent) if path else None


def last_frame(traceback_text: str) -> str | None:
    """The path of the frame that raised, or ``None`` when the text carries no frames.

    The last and not the first: see the module docstring. A traceback with no frames at all is an
    error Python reported without one — a `SyntaxError`, or a failure in the interpreter itself —
    and the caller treats that as this library's problem rather than as somebody else's.
    """
    frames = _FRAME.findall(traceback_text)
    return frames[-1] if frames else None


#: An error naming a module of ours that is not there. The frame that raises this is the import
#: machinery's own, so the rule below would otherwise call it somebody else's.
_MISSING_OURS = re.compile(r"No module named 'chainlens[.'\"]")


def _is_ours(frame: str, root: str | None) -> bool:
    """Whether a traceback frame is this library's own code.

    The package directory when it can be read, and a path shape when it cannot — the two markers
    an install puts the package under. Never a bare `chainlens/`: see `INSTALLED_MARKERS`.
    """
    normalised = frame.replace("\\", "/")
    if root is not None:
        return normalised.startswith(root.replace("\\", "/").rstrip("/") + "/")
    return any(marker in normalised for marker in INSTALLED_MARKERS)


def classify(traceback_text: str, *, root: str | None = None) -> tuple[str, str]:
    """``("ours" | "theirs", detail)`` for a failed import.

    ``root`` is this library's package directory; ``None`` means "work it out", and the fallback
    markers are used when even that fails.

    The detail is the last frame's path, or the failing message when there is no frame to point
    at — because "no frame" is a state a reader needs to see, not one to summarise.
    """
    frame = last_frame(traceback_text)
    if frame is not None and _is_ours(frame, root):
        return "ours", frame
    missing = re.search(r"No module named '(chainlens[^']*)'", traceback_text)
    if missing:
        # `No module named 'chainlens.nope'` raises inside the import machinery, so no frame
        # names our package — and green here would hide a real bug rather than a dependency's.
        # The *name* is the useful detail; a frame path would say `<string>`.
        return "ours", f"the missing module {missing.group(1)!r}"
    if frame is None:
        return "ours", traceback_text.strip().splitlines()[-1] if traceback_text.strip() else ""
    return "theirs", frame


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--suite",
        default="-x -q",
        help="arguments for pytest, run only when the library imports (default: '-x -q')",
    )
    parser.add_argument(
        "--probe",
        default=PROBE,
        help="what to import to answer the question; overridable so the rule can be exercised",
    )
    parser.add_argument("--quiet", action="store_true", help="only report problems")
    args = parser.parse_args(argv)

    probe = _run([sys.executable, "-c", args.probe])
    if probe.returncode != 0:
        verdict, detail = classify(probe.stderr, root=package_root())
        if verdict == "ours":
            print(f"the pre-release breaks this library, at {detail}", file=sys.stderr)
            print(probe.stderr, file=sys.stderr)
            return 1
        # Green, with the reason on stdout so the job's log says what it is waiting for.
        print(f"::warning::the pre-release breaks a dependency, not chainlens: at {detail}")
        print(probe.stderr)
        return 0

    if not args.quiet:
        print("the library imports against the pre-release; running the suite")
    # Not captured: this is the run whose output a reader actually wants, and a test run whose
    # log went into a variable nobody prints is a test run that reported nothing.
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args.suite.split()], check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
