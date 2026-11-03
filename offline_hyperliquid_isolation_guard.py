"""Offline architectural guard for the synthetic Hyperliquid review modules.

Inspects repository source as text; never imports a live executor, reads
credentials, performs network calls or connects to a database.
"""
import ast
from dataclasses import dataclass
from pathlib import Path

REVIEW_MODULES = (
    "offline_hyperliquid_wire_review.py",
    "offline_hyperliquid_http_envelope.py",
    "offline_hyperliquid_json_boundary.py",
    "offline_hyperliquid_evidence_freshness.py",
    "offline_hyperliquid_order_fill_conflicts.py",
    "offline_hyperliquid_account_impact.py",
    "offline_hyperliquid_synthetic_pipeline.py",
    "offline_hyperliquid_entry_release_boundary.py",
)
BLOCKED_IMPORT_ROOTS = frozenset({
    "requests", "httpx", "urllib", "socket", "websocket", "websockets",
    "hyperliquid", "ccxt", "supabase", "psycopg", "psycopg2", "asyncpg",
    "subprocess", "intraday_executor", "aggressive_executor",
})
BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__"})

@dataclass(frozen=True)
class IsolationReview:
    status: str
    reason: str

def inspect_offline_source_isolation(*, source, filename):
    def hold(reason):
        return IsolationReview("hold", reason)
    if type(source) is not str or type(filename) is not str:
        return hold("invalid source input")
    try:
        tree = ast.parse(source, filename=filename)
    except (SyntaxError, ValueError, TypeError):
        return hold("unparseable offline source")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return hold("relative imports require manual review")
            names = (node.module or "",)
        else:
            names = ()
        for name in names:
            if name.split(".")[0] in BLOCKED_IMPORT_ROOTS:
                return hold("live/network/database import forbidden in offline module")
        if isinstance(node, (ast.Call,)):
            target = node.func
            if isinstance(target, ast.Name) and target.id in BLOCKED_CALLS:
                return hold("dynamic code execution forbidden")
            if isinstance(target, ast.Attribute) and target.attr in (
                "system", "popen", "run", "Popen", "connect", "urlopen",
                "request", "post", "get",
            ):
                return hold("potential external side-effect call forbidden")
    return IsolationReview("review_only", "static import/call guard passed; manual review still required")

def inspect_offline_module_files(*, root):
    base = Path(root)
    for name in REVIEW_MODULES:
        try:
            source = (base / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return IsolationReview("hold", "missing or unreadable offline module")
        result = inspect_offline_source_isolation(source=source, filename=name)
        if result.status != "review_only":
            return result
    return IsolationReview("review_only", "offline module source guard passed; no runtime guarantee")
