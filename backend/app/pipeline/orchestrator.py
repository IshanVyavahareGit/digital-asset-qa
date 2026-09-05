"""Evaluation orchestrator — the parallel check pipeline.

Design: the three *analyzers* (typo/roster via Gemini, sponsor audit via OpenCV,
design/theme via Gemini) are independent, so they run concurrently with
asyncio.gather. The *safe-zone* check is a composition step: it consumes the
critical elements the analyzers located, so it runs once those complete. It's pure
geometry, so it adds no real latency.

Every check is wrapped so that an unexpected exception becomes an honest `failed`
CheckRun rather than crashing the request or fabricating findings.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.checks.base import Check, CheckContext, CheckResult, RawFinding
from app.checks.design_theme import DesignThemeCheck
from app.checks.matchup import MatchupCheck
from app.checks.safe_zone import SafeZoneCheck
from app.checks.sponsor_audit import SponsorAuditCheck
from app.checks.typo_roster import TypoRosterCheck
from app.core.enums import Verdict
from app.pipeline.verdict import compute_verdict
from app.services.gemini import Usage

# Analyzers run in parallel; safe-zone composes their output afterwards.
ANALYZERS: list[Check] = [
    TypoRosterCheck(),
    MatchupCheck(),
    SponsorAuditCheck(),
    DesignThemeCheck(),
]
# Safe-zone runs last: it tests the elements the analyzers located against the
# platform's danger zones, so it needs their output.
COMPOSER: Check | None = SafeZoneCheck()


@dataclass
class EvaluationOutcome:
    verdict: Verdict
    reasoning: str
    pipeline_status: str
    findings: list[RawFinding]
    check_results: list[CheckResult]
    usage: Usage = field(default_factory=Usage)


async def _timed(check: Check, ctx: CheckContext) -> CheckResult:
    """Run a check, record its duration, and never let it raise."""
    start = time.perf_counter()
    try:
        result = await check.run(ctx)
    except Exception as exc:  # noqa: BLE001 — safety net; honest failure
        result = CheckResult.failed(check.check_type, f"Unexpected error: {exc}")
    result.duration_ms = int((time.perf_counter() - start) * 1000)
    return result


def _pipeline_status(results: list[CheckResult]) -> str:
    from app.core.enums import CheckStatus

    statuses = [r.status for r in results]
    if all(s == CheckStatus.failed for s in statuses):
        return "failed"
    if any(s == CheckStatus.failed for s in statuses):
        return "partial"
    return "ok"


async def evaluate(ctx: CheckContext) -> EvaluationOutcome:
    # Phase A: independent analyzers, concurrently.
    analyzer_results = await asyncio.gather(*(_timed(c, ctx) for c in ANALYZERS))

    # Phase B: safe-zone composition (only if a composer is enabled).
    results = list(analyzer_results)
    if COMPOSER is not None:
        # Compose located elements (handle/logo boxes) for the geometric check.
        ctx.located_elements = [
            el for r in analyzer_results for el in r.located_elements
        ]
        results.append(await _timed(COMPOSER, ctx))

    findings = [f for r in results for f in r.findings]
    usage = Usage()
    for r in results:
        usage.add(r.usage)

    pipeline_status = _pipeline_status(results)
    verdict, reasoning = compute_verdict(findings, pipeline_status)

    return EvaluationOutcome(
        verdict=verdict, reasoning=reasoning, pipeline_status=pipeline_status,
        findings=findings, check_results=results, usage=usage,
    )
