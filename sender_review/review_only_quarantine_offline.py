"""Static quarantine audit for test-only sender review fixtures.

NO network, signer, database, exchange, workflow mutation or credential access.
This audit cannot prove that a live runner is isolated or signer-free. It
only guards one critical migration mistake: importing CI-only authority
fixtures from the FIVE existing, still signer-enabled execution paths.
Never treat a passing audit as permission to submit or deploy orders.
"""
from __future__ import annotations

import ast
from pathlib import Path

from sender_review.legacy_cutover_audit import LEGACY, ROOT

# The existing wrappers and the three executors are intentional, audited
# entrypoints. A future approved coordinated cutover needs a separate review
# and MUST NOT relax this guard to import fake fixture authentication.
_LEGACY_EXECUTABLES = (
    "hyperliquid_executor.py",
    "intraday_executor.py",
    "aggressive_executor.py",
    "intraday_profit_protection.py",
    "aggressive_profit_protection.py",
)
_FORBIDDEN_TEXT = (
    "sender_review.",
    "sender_review/",
    "sender_review\\",
    "SENDER_REVIEW_DISPOSABLE_CI",
    "sender_review_test",
    "worker_intent_fixture_builder_offline",
    "ci_only_identity_bridge",
    "ci_only_journal",
)
_FORBIDDEN_WORKFLOW_TEXT = _FORBIDDEN_TEXT + (
    "test-protected-sender-contract-review.yml",
    "test-protected-sender-postgres-review.yml",
)


def check_worker_source(source: str) -> tuple[str, ...]:
    """Conservative source-only check, not a complete import/egress proof."""
    issues = []
    try:
        tree = ast.parse(source)
    except (ValueError, SyntaxError):
        return ("invalid Python syntax",)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "sender_review" or imported.name.startswith(
                    "sender_review."
                ):
                    issues.append("legacy worker imports sender_review")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "sender_review" or module.startswith("sender_review."):
                issues.append("legacy worker imports sender_review")
    for forbidden in _FORBIDDEN_TEXT:
        if forbidden in source:
            issues.append("legacy worker references forbidden CI fixture: " + forbidden)
    return tuple(sorted(set(issues)))


def check_workflow_source(source: str) -> tuple[str, ...]:
    """Reject CI fixture execution/credentials in original LIVE workflows."""
    issues = []
    for forbidden in _FORBIDDEN_WORKFLOW_TEXT:
        if forbidden in source:
            issues.append("legacy workflow references CI fixture: " + forbidden)
    # Do not assert legacy workers are safe because their private key is still
    # present. Missing it here signals an unaudited migration/changed baseline.
    if "HL_PRIVATE_KEY" not in source:
        issues.append("legacy signing-key baseline changed: re-audit cutover")
    return tuple(sorted(set(issues)))


def review_fixture_quarantine(root: Path = ROOT) -> dict:
    if set(LEGACY) != {"daily", "intraday", "aggressive"}:
        raise ValueError("bot inventory changed: independent re-audit required")
    issues = []
    for path in _LEGACY_EXECUTABLES:
        file = root / path
        if not file.is_file():
            issues.append("missing legacy worker: " + path)
            continue
        issues.extend(path + ": " + issue for issue in check_worker_source(
            file.read_text(encoding="utf-8")
        ))
    for info in LEGACY.values():
        path = info["workflow"]
        file = root / path
        if not file.is_file():
            issues.append("missing legacy workflow: " + path)
            continue
        issues.extend(path + ": " + issue for issue in check_workflow_source(
            file.read_text(encoding="utf-8")
        ))
    return {
        "status": "NO_GO",
        "scope": "static fixture quarantine; NOT runtime isolation or deployable sender",
        "quarantine_checks_pass": not issues,
        "issues": tuple(sorted(issues)),
        "live_trading_authorized": False,
        "signing_authorized": False,
        "testnet_authorized": False,
    }
