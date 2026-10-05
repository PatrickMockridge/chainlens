"""Smoke tests for the package surface established in M0."""

from __future__ import annotations

import importlib

import pytest


def test_version_is_exposed() -> None:
    import chainlens

    assert isinstance(chainlens.__version__, str)
    assert chainlens.__version__


def test_dunder_all_matches_public_names() -> None:
    import chainlens

    for name in chainlens.__all__:
        assert hasattr(chainlens, name), f"{name} listed in __all__ but not exported"


def test_public_exceptions_are_rooted_at_chainlens_error() -> None:
    import chainlens

    for name in chainlens.__all__:
        obj = getattr(chainlens, name)
        if isinstance(obj, type) and issubclass(obj, Exception):
            assert issubclass(obj, chainlens.ChainlensError)


def test_package_ships_a_pep561_marker() -> None:
    """Without py.typed downstream users get no type information."""
    import importlib.resources

    marker = importlib.resources.files("chainlens").joinpath("py.typed")
    assert marker.is_file()


def test_import_does_not_import_optional_heavy_dependencies() -> None:
    """Importing the package must not drag in the [eth]/[nx] extras.

    These are deliberately optional; a BTC-only user should never pay for web3.py.
    """
    import subprocess
    import sys

    code = (
        "import sys, chainlens;"
        "leaked = [m for m in ('web3', 'networkx', 'pandas') if m in sys.modules];"
        "print(leaked)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_module_layout_is_importable() -> None:
    """The sub-packages that exist in M0 must import cleanly."""
    for module in ("chainlens", "chainlens.exceptions"):
        assert importlib.import_module(module) is not None


@pytest.mark.anyio
async def test_async_test_harness_runs() -> None:
    """Guards the anyio wiring so a broken async fixture fails loudly, not silently."""
    import anyio

    await anyio.sleep(0)
