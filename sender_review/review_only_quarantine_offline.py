"""Static quarantine audit for test-only sender review fixtures.

NO network, signer, database, exchange, workflow mutation or credential access.
This audit cannot prove that a live runner is isolated or signer-free. It
only guards one critical migration mistake: importing CI-only authority
fixtures from the FIVE existing, still signer-enabled execution paths.
Never treat a passing audit as permission to submit or deploy orders.
"""
from __future__ import annotations

import ast
import hashlib
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


# Git blob identifiers confirmed identical on main and PR #42's review
# branch, 15 Nov 2026. These freeze the original LIVE surface during the
# separate OFFLINE review. Do not update pins merely to make CI pass: any
# proposed live edit requires its own coordinated cutover and human review.
# Git SHA-1 blobs are drift fingerprints, NOT runtime or security attestation.
_REVIEW_BASELINE_GIT_BLOBS = {
    "hyperliquid_executor.py": "d98cba6e73507192f5155dfd7f2e414dddc7fcb4",
    "intraday_executor.py": "2a3984dbe52dfa443de4823c157a22410974eb41",
    "aggressive_executor.py": "62bd386693c4c76517ba23fd7520b360f373c685",
    "intraday_profit_protection.py": "f058462709e2a22bcdcd095d28d5d8fc8c4bcf10",
    "aggressive_profit_protection.py": "9e40fac7eb28c113b4476aada6f0188a64e23269",
    ".github/workflows/execute-trades.yml": "402f9532bd7fdc8f2ca2728249799f484a48d12e",
    ".github/workflows/execute-intraday.yml": "3e1f7e2a70c4967738c95bd713b15f4c8afebaee",
    ".github/workflows/execute-aggressive.yml": "12c95e7bfdd70007951b74c9d90b4f3083bb0860",
}


def git_blob_fingerprint(content: bytes) -> str:
    """Git content blob ID, for detecting offline working-tree baseline drift."""
    if type(content) is not bytes:
        raise TypeError("expected bytes")
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def check_frozen_legacy_content(root: Path = ROOT) -> tuple[str, ...]:
    """Flag ANY byte-level mutation of reviewed legacy source/workflows."""
    issues = []
    for path, expected_blob in _REVIEW_BASELINE_GIT_BLOBS.items():
        file = root / path
        if not file.is_file():
            issues.append("missing frozen live path: " + path)
        elif git_blob_fingerprint(file.read_bytes()) != expected_blob:
            issues.append("legacy live path changed; re-audit required: " + path)
    return tuple(sorted(issues))


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
    issues = list(check_frozen_legacy_content(root))
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
