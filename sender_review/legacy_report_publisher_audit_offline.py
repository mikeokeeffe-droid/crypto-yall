"""Read-only inventory of the existing bot-report publishing hazards.

This scans the three original workflow YAML source files as text. It does not
parse arbitrary shell logic, run workflows, access tokens, submit trades, or
establish that any bot has run recently. All outcomes remain NO_GO.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from sender_review.legacy_cutover_audit import ROOT

WORKFLOWS = (
    "execute-trades.yml",
    "execute-intraday.yml",
    "execute-aggressive.yml",
)
_MAX_WORKFLOW_BYTES = 128_000
_REPORT_STEP = re.compile(r"^      - name: Publish daily bot report\s*$", re.M)
_NEXT_STEP = re.compile(r"^      - name: ", re.M)


@dataclass(frozen=True)
class WorkflowReportRisk:
    workflow: str
    source_read: bool = False
    report_step_present: bool = False
    grants_contents_write: bool = False
    directly_pushes_main: bool = False
    resets_checkout_to_main: bool = False
    report_failure_nonfatal: bool = False
    protection_monitor_follows_report: bool = False


@dataclass(frozen=True)
class ReportPublisherAudit:
    decision: str = "NO_GO"
    source_review_only: bool = True
    production_migration_ready: bool = False
    report_delivery_verified: bool = False
    safe_workspace_proven: bool = False
    findings: tuple[WorkflowReportRisk, ...] = ()


def inspect_legacy_report_publishers_offline(root: Path = ROOT) -> ReportPublisherAudit:
    """Identify source-level risks without performing any workflow actions."""
    if not isinstance(root, Path):
        return ReportPublisherAudit()
    findings = []
    for filename in WORKFLOWS:
        path = root / ".github" / "workflows" / filename
        try:
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_WORKFLOW_BYTES:
                findings.append(WorkflowReportRisk(filename))
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            findings.append(WorkflowReportRisk(filename))
            continue
        match = _REPORT_STEP.search(text)
        step = ""
        following = ""
        if match:
            remaining = text[match.end():]
            end = _NEXT_STEP.search(remaining)
            step = remaining[:end.start()] if end else remaining
            following = remaining[end.start():] if end else ""
        findings.append(WorkflowReportRisk(
            workflow=filename,
            source_read=True,
            report_step_present=bool(match),
            grants_contents_write=bool(re.search(r"^  contents: write\s*$", text, re.M)),
            directly_pushes_main="git push origin HEAD:main" in step,
            resets_checkout_to_main="git reset --hard origin/main" in step,
            report_failure_nonfatal=(
                bool(re.search(r"^        continue-on-error: true\s*$", step, re.M))
                and bool(re.search(r"^        if: always\(\)\s*$", step, re.M))
            ),
            protection_monitor_follows_report=bool(re.search(
                r"^      - name: Monitor (Intraday|Aggressive) protection", following, re.M
            )),
        ))
    return ReportPublisherAudit(findings=tuple(findings))
