"""Source-only review of CURRENT bot paths; always NO-GO for live deployment.

Never imports an executor or workflow module. Never connects to an exchange,
network, PostgreSQL, Supabase, or loads secrets. This is a *known-blocker
inventory*, not a proof of operational isolation or a launch gate that can
authorize trading. Dynamic/reflection-based calls require independent review.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = {
    "daily": {
        "workflow": ".github/workflows/execute-trades.yml",
        "executor": "hyperliquid_executor.py",
        "wrapper": None,
    },
    "intraday": {
        "workflow": ".github/workflows/execute-intraday.yml",
        "executor": "intraday_executor.py",
        "wrapper": "intraday_profit_protection.py",
    },
    "aggressive": {
        "workflow": ".github/workflows/execute-aggressive.yml",
        "executor": "aggressive_executor.py",
        "wrapper": "aggressive_profit_protection.py",
    },
}
# Broad inventory for direct calls on an exchange object; not a complete
# proof that all SDK aliases or dynamic call sites were found.
_MUTATIONS = frozenset((
    "market_open", "market_close", "update_leverage", "order",
    "bulk_orders", "cancel", "bulk_cancel", "modify_order",
    "schedule_cancel", "set_referrer", "vault_transfer",
))
_WORKFLOW_PY = re.compile(r"\bpython(?:3)?\s+(?:-u\s+)?([\w./-]+\.py)\b")
_EXPOSED_SECRET = re.compile(r"^\s*HL_PRIVATE_KEY\s*:", re.MULTILINE)
_OIDC_PERMISSION = re.compile(r"^\s*id-token\s*:\s*write\s*$", re.MULTILINE)


@dataclass(frozen=True)
class WorkerCutoverBlockers:
    bot: str
    workflow: str
    entrypoints: tuple[str, ...]
    signing_key_in_workflow: bool
    oidc_token_permission_present: bool
    has_signer_backed_bootstrap: bool
    direct_mutations: tuple[str, ...]
    unsized_market_close_lines: tuple[int, ...]
    workflow_dispatch_available: bool
    can_prove_no_signing_or_order_egress: bool = False
    ready_for_cutover: bool = False


def _source_lines(source: str) -> str:
    # Exclude full-line YAML comments from our coarse static inventory.
    return "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )


def inspect_python_mutation_sites(source: str) -> tuple[tuple[str, ...], tuple[int, ...], bool]:
    """Identify explicit AST sinks only; report direct calls, never execute."""
    tree = ast.parse(source)
    sink_sites = []
    unsized_close = []
    signer_bootstrap = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else ""
            )
            if name in _MUTATIONS:
                sink_sites.append(f"{name}@{node.lineno}")
                if name == "market_close" and not any(
                    kw.arg == "sz" for kw in node.keywords
                ):
                    unsized_close.append(node.lineno)
            if name in ("get_client", "Exchange"):
                signer_bootstrap = True
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name in ("get_client", "Exchange")
                   for alias in node.names):
                signer_bootstrap = True
        elif isinstance(node, ast.Constant):
            if node.value == "HL_PRIVATE_KEY":
                signer_bootstrap = True
    return tuple(sorted(sink_sites)), tuple(sorted(set(unsized_close))), signer_bootstrap


def inspect_current_checkout(root: Path = ROOT) -> dict[str, WorkerCutoverBlockers]:
    result = {}
    for bot, paths in LEGACY.items():
        wf_path = root / paths["workflow"]
        executor_path = root / paths["executor"]
        if not wf_path.is_file() or not executor_path.is_file():
            raise FileNotFoundError(f"Missing audited {bot} source (fail closed)")
        wf = _source_lines(wf_path.read_text(encoding="utf-8"))
        executed = set(_WORKFLOW_PY.findall(wf))
        expected = paths["wrapper"] or paths["executor"]
        if expected not in executed:
            raise ValueError(f"{bot} executor path changed; manual re-audit required")
        all_sources = [paths["executor"]]
        if paths["wrapper"]:
            wrapper_path = root / paths["wrapper"]
            if not wrapper_path.is_file():
                raise FileNotFoundError(f"Missing {bot} wrapper")
            all_sources.append(paths["wrapper"])
        mutations = []
        unsized = []
        signer_bootstrap = False
        for path in all_sources:
            site, close, signer = inspect_python_mutation_sites(
                (root / path).read_text(encoding="utf-8")
            )
            mutations.extend(f"{path}:{x}" for x in site)
            unsized.extend(close)
            signer_bootstrap = signer_bootstrap or signer
        result[bot] = WorkerCutoverBlockers(
            bot=bot,
            workflow=paths["workflow"],
            entrypoints=tuple(sorted(executed)),
            signing_key_in_workflow=bool(_EXPOSED_SECRET.search(wf)),
            oidc_token_permission_present=bool(_OIDC_PERMISSION.search(wf)),
            has_signer_backed_bootstrap=signer_bootstrap,
            direct_mutations=tuple(sorted(mutations)),
            unsized_market_close_lines=tuple(sorted(unsized)),
            workflow_dispatch_available="workflow_dispatch:" in wf,
        )
    return result


def make_no_go_report(root: Path = ROOT) -> dict:
    workers = inspect_current_checkout(root)
    return {
        "status": "NO_GO",
        "source": "static checkout inspection only",
        "meaning": "Known legacy blockers; NOT a deployment or trade authorization",
        "workers": {name: asdict(item) for name, item in workers.items()},
        "release_gates_unproven": [
            "real runtime OIDC/JWKS, HTTPS caller identity and persistent replay",
            "all old exchange signing secrets absent from all worker processes",
            "network egress and OS key/credential isolation verified on actual hosts",
            "all entry, close, pyramid and leverage mutations routed to one sender",
            "independent order/fill provenance and safe explicit-size reduce-only close",
            "independent exact-commit security/risk review and operator approval",
        ],
    }


if __name__ == "__main__":
    report = make_no_go_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    # This command is a successful AUDIT when it identifies known blockers.
    # It is never a GO switch. A future clean candidate needs different,
    # independently verified runtime evidence and an explicit approval.
    if not all(w.signing_key_in_workflow and w.direct_mutations
               for w in inspect_current_checkout().values()):
        print("Baseline drift: redo independent legacy audit", file=sys.stderr)
        sys.exit(1)
