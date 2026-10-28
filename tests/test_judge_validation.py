"""Judge validation maths against hand-computed values."""

import pytest

from arl.evals import judge_validation as jv


def _labels(tp, fn, fp, tn):
    human = ["fail"] * (tp + fn) + ["pass"] * (fp + tn)
    judge = ["fail"] * tp + ["pass"] * fn + ["fail"] * fp + ["pass"] * tn
    return human, judge


def test_confusion_counts_fail_as_positive():
    c = jv.confusion(*_labels(3, 1, 2, 4))
    assert (c.tp, c.fn, c.fp, c.tn, c.n) == (3, 1, 2, 4, 10)
    assert c.tpr == pytest.approx(0.75) and c.tnr == pytest.approx(4 / 6)
    assert c.prevalence == pytest.approx(0.4)


def test_always_pass_judge_agrees_often_and_catches_nothing():
    """Why raw agreement misleads: 85% agreement, TPR 0, kappa 0."""
    c = jv.confusion(*_labels(0, 3, 0, 17))
    assert c.agreement == pytest.approx(0.85)
    assert c.tpr == 0 and c.tnr == 1
    assert c.kappa == pytest.approx(0.0)


def test_kappa_hand_computed():
    # po = 0.7; human fail 0.5, judge fail 0.6; pe = 0.5*0.6 + 0.5*0.4 = 0.5
    c = jv.confusion(*_labels(20, 5, 10, 15))
    assert c.kappa == pytest.approx(0.4)
    assert jv.confusion(*_labels(5, 0, 0, 5)).kappa == pytest.approx(1.0)


def test_kappa_undefined_when_both_raters_use_one_label():
    assert jv.confusion(*_labels(0, 0, 0, 10)).kappa is None


def test_wilson_known_values():
    lo, hi = jv.wilson(15, 15)
    assert lo == pytest.approx(15 / (15 + jv.Z95 ** 2), abs=1e-6)   # about 0.796
    assert hi == 1.0
    lo, hi = jv.wilson(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-4), pytest.approx(0.7634, abs=1e-4))
    assert jv.wilson(0, 0) is None


def test_bootstrap_kappa_is_deterministic_and_brackets_the_point():
    human, judge = _labels(10, 3, 2, 15)
    ci = jv.bootstrap_kappa(human, judge)
    assert ci == jv.bootstrap_kappa(human, judge)
    assert ci[0] <= jv.confusion(human, judge).kappa <= ci[1]


def test_corrected_pass_rate():
    # q = 0.3 observed fails; pi = (0.3 + 0.9 - 1) / (0.8 + 0.9 - 1) = 0.2857
    assert jv.corrected_pass_rate(0.7, tpr=0.8, tnr=0.9) == pytest.approx(1 - 0.2 / 0.7)
    assert jv.corrected_pass_rate(0.7, tpr=1.0, tnr=1.0) == pytest.approx(0.7)
    assert jv.corrected_pass_rate(0.7, tpr=0.5, tnr=0.5) is None
    assert jv.corrected_pass_rate(1.0, tpr=0.8, tnr=0.9) == 1.0     # clipped


def test_validate_leaves_out_judge_errors_and_reports():
    human = ["fail", "fail", "pass", "pass"]
    v = jv.validate(human, ["fail", None, "pass", "fail"])
    assert v.judge_errors == 1
    assert (v.confusion.tp, v.confusion.fn, v.confusion.fp, v.confusion.tn) == (1, 0, 1, 1)
    text = jv.report(v, "test")
    assert "TPR (fails caught) | 1.00 (1/1)" in text and "Judge errors (no verdict, left out): 1" in text


def test_confusion_rejects_unpaired_or_unknown_labels():
    with pytest.raises(ValueError):
        jv.confusion(["pass"], [])
    with pytest.raises(ValueError):
        jv.confusion(["skip"], ["pass"])
