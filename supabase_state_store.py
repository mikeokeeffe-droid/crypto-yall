"""Opt-in Supabase state persistence. Disabled unless SUPABASE_STATE_ENABLED=ON.

Never silently fall back to Gist after a Supabase error. This module only stores
state; it does not authorize or perform exchange orders.
"""
import os
import requests

_REVISIONS = {}
_ALLOWED = {"aggressive", "intraday", "daily"}


def enabled():
    return os.environ.get("SUPABASE_STATE_ENABLED", "").upper() == "ON"


def _config(bot):
    if bot not in _ALLOWED:
        raise ValueError("Unknown bot")
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    return url, headers


def load(bot):
    url, headers = _config(bot)
    response = requests.get(
        url + "/rest/v1/bot_state",
        headers=headers,
        params={"select": "state,revision", "bot": "eq." + bot},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    if len(rows) != 1 or not isinstance(rows[0].get("state"), dict):
        raise RuntimeError("Missing or invalid Supabase state for " + bot)
    revision = rows[0]["revision"]
    if type(revision) is not int or revision < 1:
        raise RuntimeError("Invalid revision for " + bot)
    _REVISIONS[bot] = revision
    return rows[0]["state"]


def save(bot, state):
    if not isinstance(state, dict):
        raise TypeError("State must be a dict")
    if bot not in _REVISIONS:
        raise RuntimeError("Must load Supabase state before saving " + bot)
    url, headers = _config(bot)
    response = requests.post(
        url + "/rest/v1/rpc/cas_bot_state",
        headers=headers,
        json={
            "p_bot": bot,
            "p_expected_revision": _REVISIONS[bot],
            "p_state": state,
        },
        timeout=30,
    )
    response.raise_for_status()
    revision = response.json()
    if type(revision) is not int or revision != _REVISIONS[bot] + 1:
        raise RuntimeError("Unexpected Supabase revision for " + bot)
    _REVISIONS[bot] = revision
