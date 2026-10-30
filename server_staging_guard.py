"""Fail-closed startup guard for a future offline Hetzner staging service.

No exchange/network/database imports. This is NOT wired into live executors.
"""
import os


class UnsafeStartup(RuntimeError):
    pass


def validate_offline_startup(env=None):
    env = os.environ if env is None else env
    required = {
        "BOT_RUN_MODE": "offline",
        "ORDER_SUBMISSION_ENABLED": "false",
        "HL_TESTNET": "true",
        "SERVER_LIVE_TRADING_APPROVED": "false",
    }
    for key, expected in required.items():
        if env.get(key, "").strip().lower() != expected:
            raise UnsafeStartup(f"offline startup blocked: {key} must be {expected}")
    for key in ("HL_PRIVATE_KEY", "HYPERLIQUID_PRIVATE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        if env.get(key):
            raise UnsafeStartup(f"offline startup blocked: unexpected secret {key}")
    return True


if __name__ == "__main__":
    validate_offline_startup()
    print("OFFLINE-ONLY startup configuration verified; no trading service launched.")
