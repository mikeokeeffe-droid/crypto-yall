"""Read-only inventory for the coordinated Daily/Intraday/Aggressive cutover.

Never imports a trading executor, starts a service, accesses credentials, or
connects to a database or exchange. This is a KNOWN LEGACY SURFACE inventory,
not a demonstration that a signer-free service exists. It always returns NO_GO.
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from sender_review.legacy_cutover_audit import LEGACY, ROOT

# Expected baseline from 2026-11-15 main. If a workflow or SDK call changes,
# this test must FAIL until the review matrix is independently updated.
_EXPECTED = {
    "daily": {"entry_script": "hyperliquid_executor.py",
              "execution_invocations": 1, "key_injections": 1},
    "intraday": {"entry_script": "intraday_profit_protection.py",
                 "execution_invocations": 2, "key_injections": 2},
    "aggressive": {"entry_script": "aggressive_profit_protection.py",
                  "execution_invocations": 2, "key_injections": 2},
}
_KNOWN_MUTATIONS = {
    "market_open": 1,
    "market_close_explicit_size": 1,
    "market_close_unsized": 1,
    "update_leverage": 1,
}
_EXEC_RE = re.compile(r"\bpython(?:3)?\s+(?:-u\s+)?([\w./-]+\.py)\b")
_KEY_RE = re.compile(r"^\s*HL_PRIVATE_KEY\s*:", re.MULTILINE)
_OIDC_RE = re.compile(r"^\s*id-token\s*:\s*write\s*$", re.MULTILINE)
_EXIT_REASONS = (
    "signal_exit", "profit_floor", "trailing_protection", "usd_loss_cap",
)
_CUTOVER_REQUIREMENTS = (
    "all legacy workflow executions and secret injections removed together",
    "verified runtime workload identity with durable token/request replay protection",
    "account-wide coordinator and single exclusive exchange signer with fencing",
    "server-controlled effective network/account/DEX/coin/risk limits",
    "entry and aggressive pyramid sizing/decimal and leverage update semantics",
    "verified fill-and-baseline ownership before any explicit-size reduce-only close",
    "signal, profit-floor, trailing and USD-loss-cap protective exits preserved",
    "separate protection-only jobs and exception/retry paths accounted for",
    "outage, partial fill, unknown ACK, stop and rollback drills approved",
    "independent security/trading-risk review and explicit testnet approval",
)


@dataclass(frozen=True)
class ReviewedBotSurface:
    bot: str
    workflow: str
    execution_script: str
    execution_invocations: int
    exposed_signer_env_assignments: int
    runtime_oidc_permission: bool
    mutation_counts: dict[str, int]
    exit_types_requiring_preservation: tuple[str, ...]
    requires_real_sender: bool = True
    signer_free_runtime_proven: bool = False
    safe_close_proven: bool = False
    migration_approved: bool = False


def _parse_mutations(source: str) -> Counter:
    tree = ast.parse(source)
    result = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        action = node.func.attr
        if action == "market_close":
            has_size = any(kw.arg == "sz" for kw in node.keywords)
            result["market_close_explicit_size" if has_size
                   else "market_close_unsized"] += 1
        elif action in ("market_open", "update_leverage"):
            result[action] += 1
        elif action in ("order", "bulk_orders", "cancel", "bulk_cancel",
                        "modify_order", "schedule_cancel"):
            # A future new mutation must not be silently ignored.
            result["unknown_direct_mutation_" + action] += 1
    return result


def inspect_cutover_surfaces(root: Path = ROOT) -> dict[str, ReviewedBotSurface]:
    surfaces = {}
    for bot, meta in LEGACY.items():
        expected = _EXPECTED[bot]
        workflow = root / meta["workflow"]
        executor = root / meta["executor"]
        if not workflow.is_file() or not executor.is_file():
            raise FileNotFoundError(f"{bot}: required source absent; STOP")
        workflow_text = workflow.read_text(encoding="utf-8")
        executor_text = executor.read_text(encoding="utf-8")
        # Exclude only full-line comments, not in-script YAML or real steps.
        active_lines = "\n".join(line for line in workflow_text.splitlines()
                                 if not line.lstrip().startswith("#"))
        execution_invocations = _EXEC_RE.findall(active_lines).count(
            expected["entry_script"])
        injections = len(_KEY_RE.findall(active_lines))
        counts = _parse_mutations(executor_text)
        if execution_invocations != expected["execution_invocations"]:
            raise ValueError(f"{bot}: unexpected execution-path count; re-audit")
        if injections != expected["key_injections"]:
            raise ValueError(f"{bot}: signer environment changed; re-audit")
        if counts != Counter(_KNOWN_MUTATIONS):
            raise ValueError(f"{bot}: mutation sink changed; re-audit: {counts}")
        if not injections or _OIDC_RE.search(active_lines):
            raise ValueError(f"{bot}: workflow identity/secret baseline drift; re-audit")
        if meta["wrapper"]:
            wrapper = root / meta["wrapper"]
            if not wrapper.is_file():
                raise FileNotFoundError(f"{bot}: protection wrapper absent; STOP")
            wrapper_source = wrapper.read_text(encoding="utf-8")
            # Wrappers call their base executor; a changed direct SDK sink
            # requires an independent audit before expanding this matrix.
            if _parse_mutations(wrapper_source):
                raise ValueError(f"{bot}: new direct mutation in wrapper; re-audit")
        surfaces[bot] = ReviewedBotSurface(
            bot=bot, workflow=meta["workflow"],
            execution_script=expected["entry_script"],
            execution_invocations=execution_invocations,
            exposed_signer_env_assignments=injections,
            runtime_oidc_permission=False,
            mutation_counts=dict(sorted(counts.items())),
            exit_types_requiring_preservation=_EXIT_REASONS,
        )
    return surfaces


def build_no_go_matrix(root: Path = ROOT) -> dict:
    bots = inspect_cutover_surfaces(root)
    return {
        "status": "NO_GO",
        "scope": "static baseline only; no remote service, order, or deployment",
        "bots": {name: asdict(entry) for name, entry in bots.items()},
        "additional_aggressive_action": "pyramid_long/pyramid_short",
        "critical_requirements_unproven": _CUTOVER_REQUIREMENTS,
    }


if __name__ == "__main__":
    print(json.dumps(build_no_go_matrix(), indent=2, sort_keys=True))
