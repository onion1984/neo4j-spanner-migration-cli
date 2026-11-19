"""Hypothesis findings recorder.

Tests call `check(cond, hyp, test_id, evidence, ...)`: records Refuted (cond True) or
Confirmed (cond False) into reports/<run-id>/findings.jsonl, then asserts cond so that a
confirmed defect shows up as a failing test.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import threading

_LOCK = threading.Lock()
_PATH: Path | None = None


def init(report_dir: Path) -> None:
    global _PATH
    _PATH = report_dir / "findings.jsonl"


def record(
    hyp: str | None,
    test_id: str,
    status: str,
    evidence: str,
    severity: str | None = None,
    title: str | None = None,
    workaround: str | None = None,
) -> None:
    """status: Confirmed | Refuted | Not testable | Out of scope | Observation | Pass | Fail."""
    assert _PATH is not None
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "hyp": hyp,
        "test": test_id,
        "status": status,
        "severity": severity,
        "title": title,
        "evidence": evidence[:4000],
        "workaround": workaround,
    }
    with _LOCK, _PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def check(
    cond: bool,
    hyp: str | None,
    test_id: str,
    evidence: str,
    severity: str = "P1",
    title: str | None = None,
    workaround: str | None = None,
) -> None:
    """Assert expected-correct behaviour; record Confirmed (defect) or Refuted."""
    if hyp:
        record(
            hyp,
            test_id,
            "Refuted" if cond else "Confirmed",
            evidence,
            severity=None if cond else severity,
            title=title,
            workaround=None if cond else workaround,
        )
    else:
        record(None, test_id, "Pass" if cond else "Fail", evidence, severity=None if cond else severity, title=title)
    assert cond, f"[{test_id}{' / ' + hyp if hyp else ''}] {title or ''}: {evidence[:1500]}"
