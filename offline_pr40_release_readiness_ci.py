"""Static PR #40 review-status report. Always LIVE NO-GO.

The offline tests passing is not authorization to merge, deploy, or trade.
Read the three original source files as text/AST only; never import them,
the Hyperliquid SDK, or secrets. Count direct source mutation call sites to
make unreviewed code drift visible. Static inspection is not a proof of
runtime signer isolation. Manual production gates must be independently met.
"""
import ast
from pathlib import Path

BOT_FILES = {
    "Daily": "hyperliquid_executor.py",
    "Intraday": "intraday_executor.py",
    "Aggressive": "aggressive_executor.py",
}
MUTATIONS = frozenset(("market_open", "market_close", "update_leverage"))


def _source_findings(name, source):
    try:
        tree = ast.parse(source, filename=name)
    except (TypeError, ValueError, SyntaxError):
        return None
    mutations = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "exchange"
                and node.func.attr in MUTATIONS):
            mutations.append((node.func.attr, len(node.keywords) == 0))
    return {
        "direct_mutations": len(mutations),
        "unsized_closes": sum(1 for kind, no_kwargs in mutations
                             if kind == "market_close" and no_kwargs),
        "get_client_calls": sum(
            1 for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "get_client"
        ),
        "has_key_reference": any(
            isinstance(n, ast.Constant) and n.value == "HL_PRIVATE_KEY"
            for n in ast.walk(tree)
        ),
    }


def review_pr40_release_readiness(sources):
    """Produce a read-only HOLD review, NEVER a trading authorization."""
    if type(sources) is not dict or set(sources) != set(BOT_FILES.values()):
        return {"decision": "LIVE NO-GO", "source_verified": False,
                "reason": "missing or unexpected bot source; manual re-audit",
                "trading_authorized": False, "details": {}}
    details = {}
    for label, filename in BOT_FILES.items():
        content = sources[filename]
        if type(content) is not str or not content or len(content) > 500_000:
            return {"decision": "LIVE NO-GO", "source_verified": False,
                    "reason": "invalid or oversized bot source; manual re-audit",
                    "trading_authorized": False, "details": {}}
        finding = _source_findings(filename, content)
        if finding is None:
            return {"decision": "LIVE NO-GO", "source_verified": False,
                    "reason": "unparseable bot source; manual re-audit",
                    "trading_authorized": False, "details": {}}
        details[label] = finding

    baseline = (
        all(v["direct_mutations"] == 4
            and v["unsized_closes"] == 1
            and v["get_client_calls"] >= 1
            for v in details.values())
        and details["Daily"]["has_key_reference"]
    )
    return {
        "decision": "LIVE NO-GO",
        "source_verified": baseline,
        "reason": (
            "baseline confirms original signer/unsized-close risks remain"
            if baseline else
            "risk baseline changed; mandatory manual re-audit"
        ),
        "trading_authorized": False,
        "details": details,
    }


def format_pr40_gate_summary(result):
    """Markdown for the GitHub Actions summary; never a GO badge."""
    lines = [
        "## PR #40 — LIVE NO-GO (regardless of green offline tests)",
        "",
        "**Decision: LIVE NO-GO.** CI is synthetic, not a deployment audit.",
        "",
        f"**Source review:** {result['reason']}.",
        "",
        "| Original bot | Direct exchange mutations | Unsized closes | "
        "Uses `get_client()` |",
        "| --- | ---: | ---: | --- |",
    ]
    for bot in BOT_FILES:
        item = result["details"].get(bot)
        if item is None:
            lines.append(f"| {bot} | UNKNOWN | UNKNOWN | UNKNOWN |")
        else:
            lines.append(
                f"| {bot} | {item['direct_mutations']} | "
                f"{item['unsized_closes']} | "
                f"{'yes' if item['get_client_calls'] else 'unknown'} |"
            )
    lines.extend([
        "",
        "**Still blocking release:** independently deployed exclusive signer, "
        "removed bot signing credentials, verified workload identities, "
        "durable pre-dispatch journal/fencing, authoritative order/fill "
        "and account-position reconciliation, bounded reduce-only close, "
        "emergency response/rollback and independent security/risk approval.",
        "",
        "Passing these checks proves only narrow offline behavior. "
        "This report does **not** authorize merging PR #40, testnet access, "
        "server deployment, credential changes, or live orders.",
    ])
    return "\n".join(lines)


def main():
    root = Path(__file__).resolve().parent
    sources = {filename: (root / filename).read_text(encoding="utf-8")
               for filename in BOT_FILES.values()}
    print(format_pr40_gate_summary(review_pr40_release_readiness(sources)))


if __name__ == "__main__":
    main()
