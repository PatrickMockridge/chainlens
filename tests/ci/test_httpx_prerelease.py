"""The rule that decides whether an httpx pre-release breaks us or something we depend on.

**This is the thing that was missing.** The CI job ran `pytest -x -q` and went red on every
commit, because collection dies on `respx` before any chainlens module is imported — so a
dependency's incompatibility and this library's own looked identical from outside, and the red
mark said nothing about the question the job exists to ask. `tools/check_httpx_prerelease.py`
asks it directly, and these are the shapes it answers.

The tracebacks below are the real ones, trimmed to the frames that matter. The third is the one
that has not happened yet — it is what the log will look like the day `hishel` and `respx` catch
up and the breakage becomes ours.
"""

from __future__ import annotations

import check_httpx_prerelease as tool

#: `hishel` 1.4.0 under httpx 1.0.dev6, as it appeared in the CI log. Note that
#: `chainlens/providers/transport.py` **does** appear — the failing line is inside it — and the
#: frame that raised is hishel's. That is the distinction the rule turns on.
DEPENDENCY_BREAKAGE = """Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/venv/site-packages/chainlens/providers/transport.py", line 33, in <module>
    from hishel.httpx import AsyncCacheTransport
  File "/venv/site-packages/hishel/httpx.py", line 11, in <module>
    from ._async_httpx import AsyncCacheClient
  File "/venv/site-packages/hishel/_async_httpx.py", line 14, in <module>
    from httpx import RequestNotRead
ImportError: cannot import name 'RequestNotRead' from 'httpx'
"""

#: What the log looks like once `hishel` and `respx` support 1.0 — the breakage is `transport.py`'s
#: own use of a name 1.0 renamed. Synthetic, in the shape Python emits for a class definition.
OUR_BREAKAGE = """Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/venv/site-packages/chainlens/providers/transport.py", line 136, in <module>
    class _OfflineBackend(httpx.AsyncBaseTransport):
AttributeError: module 'httpx' has no attribute 'AsyncBaseTransport'
"""

#: A missing module of ours raises inside the import machinery, so *no* frame names our package.
#: Green here would hide a real bug rather than a dependency's, and the rule has a case for it.
MISSING_OURS = """Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'chainlens.nope'
"""


class TestWhoseBreakageItIs:
    def test_a_dependencys_is_not_ours(self) -> None:
        """The case that made the job red on every commit. `transport.py` is in the traceback and
        is not the frame that raised, which is exactly why the rule reads the *last* one."""
        verdict, detail = tool.classify(DEPENDENCY_BREAKAGE)
        assert verdict == "theirs"
        assert "hishel" in detail
        assert "chainlens" not in detail

    def test_ours_is_ours(self) -> None:
        verdict, detail = tool.classify(OUR_BREAKAGE)
        assert verdict == "ours"
        assert "chainlens/providers/transport.py" in detail

    def test_a_missing_module_of_ours_is_ours_though_no_frame_says_so(self) -> None:
        """The hole in the first version of the rule: the frame that raises is the import
        machinery's, so the last-frame test alone would call this somebody else's."""
        verdict, detail = tool.classify(MISSING_OURS)
        assert verdict == "ours"
        assert "chainlens.nope" in detail, "the detail should name the module, not say '<string>'"

    def test_a_traceback_with_no_frames_at_all_is_ours(self) -> None:
        """A `SyntaxError` is reported without frames, and an unrecognised failure should be red
        rather than quietly counted as somebody else's."""
        verdict, _ = tool.classify("SyntaxError: invalid syntax\n")
        assert verdict == "ours"

    def test_nothing_at_all_is_ours(self) -> None:
        """Not a case that arises from a real probe — but the empty string must not be read as
        'clean', which is the one direction that would hide everything."""
        assert tool.classify("")[0] == "ours"


class TestWhichFrameDecides:
    def test_it_is_the_last_and_not_the_first(self) -> None:
        assert tool.last_frame(DEPENDENCY_BREAKAGE) == (
            "/venv/site-packages/hishel/_async_httpx.py"
        )
        ours = tool.last_frame(OUR_BREAKAGE)
        assert ours is not None
        assert "chainlens" in ours

    def test_a_checkout_directory_does_not_make_a_dependency_look_like_ours(self) -> None:
        """The marker is the package directory and not the word: a clone at `/home/x/chainlens/`
        would otherwise make every frame in every dependency read as this repository's."""
        elsewhere = """Traceback (most recent call last):
  File "/home/x/chainlens/.venv/lib/site-packages/somepkg/__init__.py", line 3, in <module>
ImportError: cannot import name 'gone' from 'httpx'
"""
        assert tool.classify(elsewhere)[0] == "theirs"

    def test_the_package_directory_decides_when_it_can_be_read(self) -> None:
        """The authoritative form, and the one the tool actually uses: compare against where the
        library was imported from rather than against a shape."""
        root = "/venv/site-packages/chainlens"
        assert tool.classify(OUR_BREAKAGE, root=root)[0] == "ours"
        assert tool.classify(DEPENDENCY_BREAKAGE, root=root)[0] == "theirs"

    def test_an_installed_checkout_is_recognised_without_the_root(self) -> None:
        """The fallback, for the case where the library cannot be imported at all — which is what
        the probe is checking for."""
        assert tool.classify(OUR_BREAKAGE)[0] == "ours"

    def test_no_frames_gives_none(self) -> None:
        assert tool.last_frame("ImportError: something\n") is None
