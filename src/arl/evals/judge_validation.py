"""How far the judge agrees with human labels, and how sure we can be of that.

"Fail" is the positive class: the judge's job is to catch bad replies.

                     judge fail   judge pass
        human fail       TP           FN        TPR = TP / (TP + FN)   fails caught
        human pass       FP           TN        TNR = TN / (TN + FP)   passes kept

Raw agreement, (TP + TN) / n, is reported but not trusted on its own: it is dominated by the
majority class. On a set that is 85% passes, a judge that always says "pass" agrees 85% of
the time and catches nothing (TPR 0). Cohen's kappa corrects agreement for what two raters
would reach by chance at these label rates.

Intervals: Wilson 95% for the rates (good at small n and near 0 or 1), and a percentile
bootstrap for kappa. With about 15 labels per class, even a perfect 15/15 has a Wilson lower
bound near 0.80, which is why a judge validated on 30 labels stays advisory.

The corrected pass rate turns a judge's raw pass rate on unlabelled runs into an estimate of
the true one, using its measured TPR and TNR:

    observed fail rate q = TPR·π + (1 − TNR)·(1 − π)   =>   π = (q + TNR − 1) / (TPR + TNR − 1)
"""

import math
import random
from dataclasses import dataclass

Z95 = 1.959964


@dataclass(frozen=True)
class Confusion:
    tp: int   # human fail, judge fail
    fn: int   # human fail, judge pass
    fp: int   # human pass, judge fail
    tn: int   # human pass, judge pass

    @property
    def n(self) -> int:
        return self.tp + self.fn + self.fp + self.tn

    @property
    def tpr(self) -> float | None:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def tnr(self) -> float | None:
        return _ratio(self.tn, self.tn + self.fp)

    @property
    def agreement(self) -> float | None:
        return _ratio(self.tp + self.tn, self.n)

    @property
    def prevalence(self) -> float | None:
        """The share of human fails."""
        return _ratio(self.tp + self.fn, self.n)

    @property
    def kappa(self) -> float | None:
        return cohen_kappa(self)


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def confusion(human: list[str], judge: list[str]) -> Confusion:
    """From paired labels ("pass"/"fail"). Pairs where the judge erred (None) are dropped
    by the caller and counted separately."""
    if len(human) != len(judge):
        raise ValueError("human and judge labels must be paired")
    counts = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    for h, j in zip(human, judge, strict=True):
        if h not in ("pass", "fail") or j not in ("pass", "fail"):
            raise ValueError(f"labels must be pass or fail, got {h!r}, {j!r}")
        key = ("t" if h == j else "f") + ("p" if j == "fail" else "n")
        counts[key] += 1
    return Confusion(**counts)


def cohen_kappa(c: Confusion) -> float | None:
    if c.n == 0:
        return None
    observed = (c.tp + c.tn) / c.n
    human_fail, judge_fail = (c.tp + c.fn) / c.n, (c.tp + c.fp) / c.n
    chance = human_fail * judge_fail + (1 - human_fail) * (1 - judge_fail)
    if chance == 1:
        return None   # both raters gave a single label to everything: kappa is undefined
    return (observed - chance) / (1 - chance)


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_kappa(human: list[str], judge: list[str], resamples: int = 2000,
                    seed: int = 20261027) -> tuple[float, float] | None:
    """Percentile 95% interval for kappa, resampling the labelled pairs."""
    pairs = list(zip(human, judge, strict=True))
    if not pairs:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [rng.choice(pairs) for _ in pairs]
        k = cohen_kappa(confusion([h for h, _ in sample], [j for _, j in sample]))
        if k is not None:
            values.append(k)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


def corrected_pass_rate(judge_pass_rate: float, tpr: float, tnr: float) -> float | None:
    """The true pass rate implied by a judge's raw pass rate and its TPR and TNR.

    None when TPR + TNR <= 1: such a judge is no better than chance and cannot be inverted.
    """
    if tpr + tnr <= 1:
        return None
    fail = ((1 - judge_pass_rate) + tnr - 1) / (tpr + tnr - 1)
    return 1 - min(1.0, max(0.0, fail))


@dataclass(frozen=True)
class Validation:
    confusion: Confusion
    tpr_ci: tuple[float, float] | None
    tnr_ci: tuple[float, float] | None
    agreement_ci: tuple[float, float] | None
    kappa_ci: tuple[float, float] | None
    judge_errors: int

    def to_dict(self) -> dict:
        c = self.confusion
        return {"tp": c.tp, "fn": c.fn, "fp": c.fp, "tn": c.tn, "n": c.n,
                "tpr": c.tpr, "tpr_ci": self.tpr_ci, "tnr": c.tnr, "tnr_ci": self.tnr_ci,
                "agreement": c.agreement, "agreement_ci": self.agreement_ci,
                "kappa": c.kappa, "kappa_ci": self.kappa_ci, "prevalence": c.prevalence,
                "judge_errors": self.judge_errors}


def validate(human: list[str], judge: list[str | None]) -> Validation:
    """All the numbers for one labelled set. Judge errors (None) are left out and counted."""
    kept = [(h, j) for h, j in zip(human, judge, strict=True) if j is not None]
    hs, js = [h for h, _ in kept], [j for _, j in kept]
    c = confusion(hs, js)
    return Validation(
        confusion=c,
        tpr_ci=wilson(c.tp, c.tp + c.fn),
        tnr_ci=wilson(c.tn, c.tn + c.fp),
        agreement_ci=wilson(c.tp + c.tn, c.n),
        kappa_ci=bootstrap_kappa(hs, js),
        judge_errors=len(human) - len(kept),
    )


def _fmt(x: float | None) -> str:
    return "–" if x is None else f"{x:.2f}"


def _ci(ci) -> str:
    return "–" if ci is None else f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def report(v: Validation, title: str) -> str:
    c = v.confusion
    return "\n".join([
        f"### {title}",
        "",
        "| | judge fail | judge pass |",
        "|---|---|---|",
        f"| **human fail** | {c.tp} (TP) | {c.fn} (FN) |",
        f"| **human pass** | {c.fp} (FP) | {c.tn} (TN) |",
        "",
        "| Measure | Value | 95% interval |",
        "|---|---|---|",
        f"| TPR (fails caught) | {_fmt(c.tpr)} ({c.tp}/{c.tp + c.fn}) | {_ci(v.tpr_ci)} |",
        f"| TNR (passes kept) | {_fmt(c.tnr)} ({c.tn}/{c.tn + c.fp}) | {_ci(v.tnr_ci)} |",
        f"| Raw agreement | {_fmt(c.agreement)} ({c.tp + c.tn}/{c.n}) | {_ci(v.agreement_ci)} |",
        f"| Cohen's kappa | {_fmt(c.kappa)} | {_ci(v.kappa_ci)} (bootstrap) |",
        f"| Human fail share | {_fmt(c.prevalence)} | |",
        "",
        f"Judge errors (no verdict, left out): {v.judge_errors}.",
    ]) + "\n"
