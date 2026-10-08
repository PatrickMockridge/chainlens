"""The vocabulary table: what this library may name, and what each of those things is.

Every chain this library prices, and the one native asset on it, in one place. The table itself
is `specs/vocabulary/vocabulary.toml`, compiled into :mod:`chainlens.vocabulary._generated` by
``tools/gen_vocabulary.py`` and read from there by the codec, the adapters and the asset
reference.

**Why this is a module rather than a dict at each call site.** ``decimals`` was written down in
four places before this existed — ``codec/btc_amount.py`` scaled by ``10**-8`` and bounded
``format_btc``'s ``places`` at 8, ``adapters/_evm.py`` carried a module-level ``WEI_DECIMALS =
18``, ``adapters/esplora.py`` carried ``_BTC_DECIMALS = 8``, and ``verify/parsing.py`` held a
unit table with both numbers in it. A number in four places is four numbers that can disagree,
and the way that failure presents is a rendering that is off by a power of ten, at one call site,
for one chain.

**The rule this module exists to keep is: no decimals is written down twice.** The value lives in
the table's row and every reader asks this module for it. Nothing here restates a number the
table holds, and a test holds the tables' stated decimals to an independent library's
(`pycoin`'s ``SATOSHI_PER_COIN``) rather than to a second copy of this one.

**What a row is and is not.** A row is a :class:`~chainlens.vocabulary._generated.AssetRow` —
an id, a chain, a symbol, a decimals count and the address families this library validates. Its
*identity* is ``(chain, id)`` and not ``symbol``: testnet bitcoin and mainnet bitcoin both render
as ``BTC``, and a chain and a ticker are not the same question.

**The order is load-bearing.** `ASSETS` is in the table's order and that order is the dimension
basis — ``lean/Chainlens/Dim.lean`` reads an amount's dimension as a weight per row *by
position* — so rows are appended, never reordered in place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chainlens.vocabulary._generated import ASSETS, AssetRow

if TYPE_CHECKING:
    # **Annotation-only, and importing it at run time was a cycle.** `chainlens.models.enums`
    # is a leaf, but importing it runs `chainlens/models/__init__.py`, which imports the flow
    # models, which import the primitives, which import *this* module — so
    # `import chainlens.vocabulary` failed whenever it came first and worked whenever something
    # had already imported `chainlens.models`. Test collection order hid that for two tranches.
    #
    # Nothing here needs the class at run time: the table's rows key a chain by the *string* it
    # is written as, and `_spelling` below reads that off whatever a caller passes.
    from chainlens.models.enums import Chain

__all__ = [
    "ASSETS",
    "AssetRow",
    "VocabularyError",
    "decimals_for",
    "maybe_row_for",
    "row_for",
    "symbol_for",
]


class VocabularyError(LookupError):
    """A chain the vocabulary table has no row for.

    Loud rather than a default, because the alternative is a rendered amount in the wrong
    units. A chain with no row is a chain whose amounts this library cannot render, and saying
    so at the call is better than printing a number nobody can check.
    """


def _spelling(chain: Chain | str) -> str:
    """A chain as the table writes it, from either a `Chain` or a bare string.

    `getattr` rather than `isinstance` against `Chain`, because that check is the only thing that
    needed the class at run time and importing it is what made this module unimportable on its
    own. Every member of `Chain` is a `StrEnum`, so a member carries the table's spelling as
    ``value`` and a plain string is already one.
    """
    value: object = getattr(chain, "value", chain)
    return value if isinstance(value, str) else str(value)


def maybe_row_for(chain: Chain | str) -> AssetRow | None:
    """The native asset's row for ``chain``, or ``None`` if the table does not name it.

    Takes the ``Chain`` a caller has in hand as well as the string the table writes, because a
    caller reading a chain out of a document has the string — and because refusing a string
    would make "the table does not name this chain" indistinguishable from "that is not a
    chain", which are different facts.
    """
    wanted = _spelling(chain)
    return next((row for row in ASSETS if row.chain == wanted), None)


def row_for(chain: Chain | str) -> AssetRow:
    """The native asset's row for ``chain``.

    Raises:
        VocabularyError: the table has no row for the chain. The message names the table and
            the chain, because the fix is to add a row — with the decimals checked against the
            chain rather than copied from a neighbouring one.
    """
    row = maybe_row_for(chain)
    if row is None:
        named = _spelling(chain)
        raise VocabularyError(
            f"the vocabulary table names no asset on {named!r}; add a row to "
            f"specs/vocabulary/vocabulary.toml and run `make vocabulary`"
        )
    return row


def decimals_for(chain: Chain | str) -> int:
    """How many decimal places one whole unit of ``chain``'s native asset has."""
    return row_for(chain).decimals


def symbol_for(chain: Chain | str) -> str:
    """The ticker ``chain``'s native asset is written with.

    A display convention, not an identity — see the module docstring.
    """
    return row_for(chain).symbol
