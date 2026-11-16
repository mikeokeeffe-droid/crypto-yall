"""Exact Git-blob fingerprints for original three-bot strategies/protection.

This inventories 13 original bot, protection and direct signal/loss-lock source files on PR #42's reviewed baseline.
Unlike counts of SDK calls, it also detects changes to sizing, stops and
workflow conditions that leave the same number of call sites.

No executor is imported. No workflow is run. A matching digest is NOT
independent provenance, deployability, risk approval or proof of safe exits.
Every result remains HOLD / NO-GO. An expected hash change requires an
independent source review before updating the pinned reference.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from sender_review.legacy_cutover_audit import ROOT

# Git blob SHA-1 IDs returned from GitHub's contents API on the PR #42 branch
# on 16 Nov 2026. This is change detection ONLY, not adversarial source
# authentication. Independent signed SHA-256 artifacts are a separate gate.
EXPECTED_GIT_BLOBS = {
    ".github/workflows/execute-trades.yml":
        "402f9532bd7fdc8f2ca2728249799f484a48d12e",
    ".github/workflows/execute-intraday.yml":
        "3e1f7e2a70c4967738c95bd713b15f4c8afebaee",
    ".github/workflows/execute-aggressive.yml":
        "12c95e7bfdd70007951b74c9d90b4f3083bb0860",
    "hyperliquid_executor.py":
        "d98cba6e73507192f5155dfd7f2e414dddc7fcb4",
    "intraday_executor.py":
        "2a3984dbe52dfa443de4823c157a22410974eb41",
    "aggressive_executor.py":
        "62bd386693c4c76517ba23fd7520b360f373c685",
    "intraday_profit_protection.py":
        "f058462709e2a22bcdcd095d28d5d8fc8c4bcf10",
    "aggressive_profit_protection.py":
        "9e40fac7eb28c113b4476aada6f0188a64e23269",
    "usd_loss_cap.py":
        "4b3cbbf2207713bfb718204531fea75efab5ac83",
    "reentry_lock.py":
        "28aaf65ad6623ee546c1542695ae3bde78ba4c4c",
    "strategy.py":
        "4f927f235b0fc6a8182c701de6ef6c75a3fea31e",
    "intraday_strategy.py":
        "8ad689bfc22637341c0b8d8e0831458b267fe983",
    "aggressive_strategy.py":
        "9d309f2a51b7ea8c48a03a0f47b4ccc53dcda3b0",
}
_MAX_SOURCE_BYTES = 256_000


@dataclass(frozen=True)
class LegacySourceReview:
    state: str = "NO_GO"
    reason: str = "legacy source not attested or reviewed for migration"
    exact_bytes_match: bool = False
    matched_paths: tuple[str, ...] = ()
    changed_or_missing_paths: tuple[str, ...] = ()
    executable_cutover_ready: bool = False
    runtime_source_attested: bool = False
    signer_free_workers_proven: bool = False
    safe_close_proven: bool = False
    deployment_authorized: bool = False


def _git_blob_sha1(raw: bytes) -> str:
    # Git's normal object framing for SHA-1 repositories; comparison only.
    header = b"blob " + str(len(raw)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + raw).hexdigest()


def inspect_legacy_source_bytes_offline(root: Path = ROOT) -> LegacySourceReview:
    """Read only 13 fixed checkout files; return NO_GO even on exact match."""
    if not isinstance(root, Path):
        return LegacySourceReview(reason="invalid audit checkout")
    matching, changed = [], []
    for relative, expected in EXPECTED_GIT_BLOBS.items():
        file_path = root / relative
        try:
            if file_path.is_symlink() or not file_path.is_file():
                changed.append(relative)
                continue
            if not 0 < file_path.stat().st_size <= _MAX_SOURCE_BYTES:
                changed.append(relative)
                continue
            raw = file_path.read_bytes()
            if len(raw) > _MAX_SOURCE_BYTES:
                changed.append(relative)
            elif _git_blob_sha1(raw) == expected:
                matching.append(relative)
            else:
                changed.append(relative)
        except (OSError, ValueError):
            changed.append(relative)
    return LegacySourceReview(
        reason=("13 original source bytes match an untrusted audit baseline; "
                "independent runtime and protection verification still absent"
                if not changed else
                "legacy bot/workflow bytes differ or are missing; re-audit "
                "strategy and protection before any migration"),
        exact_bytes_match=not changed,
        matched_paths=tuple(matching),
        changed_or_missing_paths=tuple(changed),
    )
