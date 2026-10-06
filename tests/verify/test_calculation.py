"""The vocabulary, and the one rule that holds it together.

`chainlens.models.calculation` exists to replace sixteen overlapping ways of saying "we did not
answer" with two questions asked of every value: is it bound, and how good is the bound. These tests
are about the properties that make that a *unification* rather than a rename — chiefly that the two
halves of an `Input` cannot both be populated, so no input can drift back into meaning two things.

The last test here is the one that keeps the artifact honest. A formula displayed beside a number is
a promise, and the only thing that catches a promise edited away from the arithmetic is evaluating
the displayed string and comparing it to the function.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping

import pytest

from chainlens.models.calculation import (
    Binding,
    BoundDirection,
    Input,
    Operation,
    OperationKind,
    RatioAttempt,
    Source,
    SourceKind,
    UnboundKind,
)
from chainlens.verify.likelihood import (
    coincidence_probability,
    formula_for,
    likelihood_ratio,
)

BOUND = Source(kind=SourceKind.OBSERVED, text="read from the provider")


def _bound(name: str, value: float, **kwargs: object) -> Input:
    return Input(
        name=name,
        label=name,
        binding=Binding.BOUND,
        value=value,
        source=BOUND,
        **kwargs,  # type: ignore[arg-type]
    )


def _unbound(name: str, kind: UnboundKind, reason: str) -> Input:
    return Input(name=name, label=name, binding=Binding.UNBOUND, kind=kind, reason=reason)


class TestAnInputIsOneThing:
    def test_a_bound_input_must_carry_a_value_and_a_source(self) -> None:
        with pytest.raises(ValueError, match="carries no value"):
            Input(name="k", label="k", binding=Binding.BOUND, source=BOUND)
        with pytest.raises(ValueError, match="carries no source"):
            Input(name="k", label="k", binding=Binding.BOUND, value=1.0)

    def test_a_bound_input_may_not_also_explain_why_it_has_none(self) -> None:
        """The failure this validator exists for: an input meaning two things at once."""
        with pytest.raises(ValueError, match="which only an unbound input has"):
            Input(
                name="k",
                label="k",
                binding=Binding.BOUND,
                value=1.0,
                source=BOUND,
                kind=UnboundKind.NO_DATA,
                reason="there was no data",
            )

    def test_an_unbound_input_must_carry_a_kind_and_a_reason(self) -> None:
        with pytest.raises(ValueError, match="carries no kind"):
            Input(name="p", label="p", binding=Binding.UNBOUND, reason="nothing to price")
        with pytest.raises(ValueError, match="carries no reason"):
            Input(name="p", label="p", binding=Binding.UNBOUND, kind=UnboundKind.NO_DATA)

    def test_an_unbound_input_may_not_carry_a_value(self) -> None:
        with pytest.raises(ValueError, match="which only a bound input has"):
            Input(
                name="p",
                label="p",
                binding=Binding.UNBOUND,
                kind=UnboundKind.NO_DATA,
                reason="nothing to price",
                value=1e-4,
            )

    def test_none_of_the_three_kinds_can_stand_for_another(self) -> None:
        """They are three answers, not three spellings.

        `no_method` says stop asking, `no_data` says configure something or wait, and
        `not_requested` says nobody asked. Collapsing any pair would put a gap in a caller's own
        setup on the same footing as a limit of the chain — which is the conflation this whole
        module is here to remove, and the one `--no-estimate` was actually being reported under.
        """
        assert len(set(UnboundKind)) == 3
        for kind in UnboundKind:
            item = _unbound("p", kind, "because")
            assert item.kind is kind
            assert item.value is None
            assert item.source is None
            assert not item.is_exact


class TestWhatExactMeans:
    def test_a_point_value_is_exact(self) -> None:
        assert _bound("k", 2000).is_exact

    @pytest.mark.parametrize("direction", [BoundDirection.LOWER, BoundDirection.UPPER])
    def test_a_one_sided_bound_is_not(self, direction: BoundDirection) -> None:
        """A lower bound is not a value, and this is what stops one being used as one.

        The truncated scan is the case: `k` is bound, and bounded from below, so an operation
        over it would produce a ratio inflated by an unknown amount. Withholding is the only
        honest outcome, and it is decided here rather than by a boolean flag elsewhere on the
        artifact.
        """
        item = _bound("k", 2000, direction=direction)
        assert item.binding is Binding.BOUND
        assert not item.is_exact

    def test_an_unbound_input_is_not_exact(self) -> None:
        assert not _unbound("p", UnboundKind.NO_DATA, "too thin").is_exact


class TestAnOperationAnswersOrExplains:
    def test_a_result_and_a_reason_for_having_none_is_refused(self) -> None:
        with pytest.raises(ValueError, match="a result and a reason"):
            Operation(
                kind=OperationKind.LIKELIHOOD_RATIO,
                formula="1 / (1 - (1 - p) ** k)",
                inputs=("k", "p"),
                result=4.1,
                reason="but the scan was truncated",
            )

    def test_neither_a_result_nor_a_reason_is_refused(self) -> None:
        """A hole with no explanation is the state this shape exists to make unrepresentable."""
        with pytest.raises(ValueError, match="no result and no reason"):
            Operation(
                kind=OperationKind.LIKELIHOOD_RATIO,
                formula="1 / (1 - (1 - p) ** k)",
                inputs=("k", "p"),
            )

    def test_a_withheld_result_may_not_carry_a_direction(self) -> None:
        with pytest.raises(ValueError, match="nothing for the direction to qualify"):
            Operation(
                kind=OperationKind.LIKELIHOOD_RATIO,
                formula="1 / (1 - (1 - p) ** k)",
                inputs=("k", "p"),
                direction=BoundDirection.LOWER,
                reason="k is a lower bound",
            )

    def test_an_unbounded_result_is_a_direction_rather_than_a_boolean(self) -> None:
        """An infinite ratio: the top of the scale is a floor, not the value.

        This replaces the `lr_at_least` flag the artifact carried, so "at least" is the same word
        here as it is on a truncated scan's `k` rather than a second convention for one idea.
        """
        op = Operation(
            kind=OperationKind.LIKELIHOOD_RATIO,
            formula="1 / (1 - (1 - p) ** k)",
            inputs=("k", "p"),
            result=math.inf,
            direction=BoundDirection.LOWER,
        )
        assert op.reason is None
        assert op.direction is BoundDirection.LOWER


class TestRatioAttempt:
    def test_an_input_is_found_by_the_name_the_operation_uses(self) -> None:
        attempt = RatioAttempt(
            inputs=(_bound("k", 2000), _unbound("p", UnboundKind.NO_DATA, "too thin"))
        )
        assert attempt.by_name("k") is not None
        assert attempt.by_name("p") is not None
        assert attempt.by_name("prior") is None


# --------------------------------------------------------------------------- #
# The formula a reader is shown is the formula that ran
# --------------------------------------------------------------------------- #
_ARITHMETIC: dict[type[ast.AST], Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _evaluate(expression: str, values: Mapping[str, float]) -> float:
    """Evaluate one of our own formula strings, over a deliberately tiny grammar.

    A restricted walk rather than `eval`, which is not a security posture here — the strings come
    from a dict this repository owns — but a *statement of what a formula is allowed to be*. If a
    formula ever needs a function call or a conditional, this fails and somebody decides whether the
    artifact should be able to say that, rather than it happening by accident.
    """

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            return float(values[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC:
            return float(_ARITHMETIC[type(node.op)](walk(node.left), walk(node.right)))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITHMETIC:
            return float(_ARITHMETIC[type(node.op)](walk(node.operand)))
        raise AssertionError(f"a formula used {type(node).__name__}, which is not arithmetic here")

    return walk(ast.parse(expression, mode="eval"))


#: `(values, the function the formula must agree with)` for every operation the library has.
_CASES: dict[OperationKind, tuple[Mapping[str, float], object]] = {
    OperationKind.COINCIDENCE: (
        {"k": 2000.0, "p": 1e-4},
        lambda v: coincidence_probability(int(v["k"]), v["p"]),
    ),
    OperationKind.LIKELIHOOD_RATIO: (
        {"k": 2000.0, "p": 1e-4},
        lambda v: likelihood_ratio(int(v["k"]), v["p"]),
    ),
    OperationKind.POSTERIOR: (
        {"lr": 4.1, "prior": 0.001},
        lambda v: (lambda o: o / (1.0 + o))(v["lr"] * (v["prior"] / (1.0 - v["prior"]))),
    ),
}


def test_every_operation_has_a_formula() -> None:
    """A member with no formula would reach an artifact as an empty string."""
    for kind in OperationKind:
        assert formula_for(kind).strip()


@pytest.mark.parametrize("kind", sorted(OperationKind))
def test_the_displayed_formula_is_the_formula_that_ran(kind: OperationKind) -> None:
    """**The test that makes a formula on an artifact worth showing.**

    A test that merely recomputed a stored result from its inputs would pass on a formula that had
    been edited away from its function, because both sides would have moved together. This evaluates
    the *string* — the thing a reader sees — and compares it to the function, so an edit to one that
    missed the other is a failure.

    The tolerance is not laziness. The library evaluates these in algebraically identical but
    numerically stabler forms: `coincidence_probability` uses `-expm1(k * log1p(-p))` because the
    naive form loses its precision to cancellation for small `p`. The two differ in the last bits of
    a float and agree to every digit a reader would write down, which is exactly the claim
    `formula_for` makes in its docstring.
    """
    values, compute = _CASES[kind]
    expected = compute(values)  # type: ignore[operator]
    shown = _evaluate(formula_for(kind), values)
    assert shown == pytest.approx(expected, rel=1e-12), (
        f"the formula for {kind.value!r} no longer computes what the library computes"
    )


def test_the_ratio_formula_is_the_reciprocal_of_the_coincidence_one() -> None:
    """Stated as its own assertion because the two being consistent is a fact about the model.

    `likelihood_ratio` is `1 / coincidence_probability`, so the displayed strings have to say the
    same thing — otherwise the artifact could show a ratio that is not the reciprocal of the
    probability printed beside it.
    """
    coincidence = formula_for(OperationKind.COINCIDENCE)
    ratio = formula_for(OperationKind.LIKELIHOOD_RATIO)
    for values in ({"k": 1.0, "p": 1e-3}, {"k": 500.0, "p": 1e-2}, {"k": 2000.0, "p": 1e-5}):
        assert _evaluate(ratio, values) == pytest.approx(1.0 / _evaluate(coincidence, values))


def test_a_formula_that_uses_anything_but_arithmetic_is_refused() -> None:
    """The evaluator is a statement of what a formula may be, so it has to actually refuse."""
    with pytest.raises(AssertionError, match="not arithmetic here"):
        _evaluate("log(p)", {"p": 0.5})
    with pytest.raises(KeyError):
        _evaluate(formula_for(OperationKind.COINCIDENCE), {"k": 1.0})
