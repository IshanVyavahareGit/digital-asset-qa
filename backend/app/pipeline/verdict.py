"""Verdict aggregation.

Reduces a set of findings (+ pipeline health) to Pass / Needs Changes / Fail with
a short reasoning string. Kept pure and side-effect free so it can be recomputed
whenever findings change (e.g. after a manager dismisses one).

Rule (simple and defensible):
  - any active CRITICAL finding      -> Fail
  - else any active WARNING finding   -> Needs Changes
  - else                              -> Pass
Guardrail: if a check could not run, a would-be Pass is downgraded to Needs
Changes, because we can't honestly certify what we didn't evaluate.
"""
from __future__ import annotations

from app.core.enums import FindingStatus, Severity, Verdict

# Statuses that still "count" toward the verdict (dismissed ones don't).
_ACTIVE = {FindingStatus.open.value, FindingStatus.edited.value}


def _val(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


def compute_verdict(findings, pipeline_status: str) -> tuple[Verdict, str]:
    active = [f for f in findings if _val(getattr(f, "status", FindingStatus.open)) in _ACTIVE]
    criticals = [f for f in active if _val(f.severity) == Severity.critical.value]
    warnings = [f for f in active if _val(f.severity) == Severity.warning.value]

    if criticals:
        verdict = Verdict.fail
    elif warnings:
        verdict = Verdict.needs_changes
    else:
        verdict = Verdict.passed

    # Can't certify a clean pass if part of the pipeline failed to run.
    if verdict == Verdict.passed and pipeline_status != "ok":
        verdict = Verdict.needs_changes

    reasoning = _reasoning(verdict, len(criticals), len(warnings), pipeline_status)
    return verdict, reasoning


def _reasoning(verdict: Verdict, n_crit: int, n_warn: int, pipeline_status: str) -> str:
    parts: list[str] = []
    if n_crit:
        parts.append(f"{n_crit} critical issue{'s' if n_crit != 1 else ''}")
    if n_warn:
        parts.append(f"{n_warn} warning{'s' if n_warn != 1 else ''}")
    body = ", ".join(parts) if parts else "no issues"

    if pipeline_status == "failed":
        return "Evaluation could not run (all checks failed); manual review required."
    if pipeline_status == "partial":
        return f"Found {body}; note: some checks could not run, so results are incomplete."
    return f"Found {body}."
