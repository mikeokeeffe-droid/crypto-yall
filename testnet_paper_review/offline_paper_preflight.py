"""Credential-free, offline-only Hyperliquid TESTNET paper trading readiness gate.

Does NOT connect to an exchange, install dependencies, import trading code,
access env secrets, modify persistent state, or place any order. This script
is NOT a trading executor, authorization, or permission to activate bots.

Exit 2 (HOLD) unless a human separately completes all post-review checks.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_FILES = (
    "hyperliquid_executor.py",
    "intraday_executor.py",
    "aggressive_executor.py",
)
EXISTING_WORKFLOWS = (
    ".github/workflows/execute-trades.yml",
    ".github/workflows/execute-intraday.yml",
    ".github/workflows/execute-aggressive.yml",
)
UNSAFE_ACTIONS = {"market_open", "market_close", "update_leverage", "order"}
GATE_FIELDS = (
    "single_manual_run_only",
    "separate_testnet_only_signing_identity",
    "independently_verified_testnet_endpoint",
    "confirmed_public_account_testnet_collateral",
    "exclusive_order_sender_and_position_ownership",
    "duplicate_and_unknown_ack_protection",
    "small_order_notional_and_leverage_cap",
    "maximum_loss_and_emergency_halt",
    "independent_security_review",
    "exact_artifact_and_operator_approval",
)
EXPECTED_PROFILE = {
    "schema_version": 1,
    "kind": "testnet_paper_activation_review_only",
    "deployment_authorized": False,
    "network_authorized": False,
    "order_placement_authorized": False,
    "workflow_automation_authorized": False,
    "mainnet_authorized": False,
    "testnet_endpoint": "https://api.hyperliquid-testnet.xyz",
    "maximum_orders_per_manual_run": 1,
    "checks": {key: "UNVERIFIED" for key in GATE_FIELDS},
}


def load_profile():
    path = Path(__file__).with_name("paper_activation_hold_profile.json")
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_repository(root=ROOT):
    """Find known signing/order paths and missing hard Mainnet fail-closed gate."""
    findings = []
    for filename in EXECUTOR_FILES:
        path = root / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
        calls = sorted({
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in UNSAFE_ACTIONS
        })
        if not calls:
            findings.append(f"HOLD: missing order-path inventory in {filename}")
        else:
            findings.append(f"HOLD: {filename} contains executable exchange methods: {', '.join(calls)}")
        contents = path.read_text(encoding="utf-8")
        if 'HL_TESTNET' in contents and "MAINNET_API_URL" in contents:
            findings.append(f"HOLD: {filename} has Mainnet-selectable client configuration")
    for filename in EXISTING_WORKFLOWS:
        contents = (root / filename).read_text(encoding="utf-8")
        if "HL_PRIVATE_KEY:" in contents:
            findings.append(f"HOLD: {filename} is signing-key-capable; not a safe paper-test runner")
    return findings


def check_review_profile(profile):
    if profile != EXPECTED_PROFILE:
        return ["HOLD: review profile drift or unsupported attempt to authorize execution"]
    return [f"HOLD: {name} has not been independently verified" for name in GATE_FIELDS]


def main():
    findings = check_review_profile(load_profile()) + inspect_repository()
    for finding in findings:
        print(finding)
    print("NO-GO: Testnet paper trading is not authorized. No orders or external requests made.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
