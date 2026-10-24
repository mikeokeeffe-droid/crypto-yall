"""Read-only audit for all three Gist-backed bots; no state is printed or changed."""
import hashlib
import json
import os
import sys
import requests

SOURCES = (
    ("aggressive", "AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    ("intraday", "INTRADAY_GIST_ID", "intraday_state.json"),
    ("daily", "GIST_ID", "crypto_yall_state.json"),
)

def main():
    token = os.environ["GIST_TOKEN"]
    headers = {"Authorization": "token " + token}
    for bot, env, filename in SOURCES:
        gist_id = os.environ[env]
        response = requests.get("https://api.github.com/gists/" + gist_id, headers=headers, timeout=20)
        response.raise_for_status()
        entry = response.json()["files"][filename]
        if entry.get("truncated"):
            raw = requests.get(entry["raw_url"], headers=headers, timeout=30)
            raw.raise_for_status()
            contents = raw.text
        else:
            contents = entry["content"]
        state = json.loads(contents)
        if not isinstance(state, dict):
            raise ValueError(bot + ": state is not a JSON object")
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        print(bot + ": readable, JSON valid, sha256=" + hashlib.sha256(payload).hexdigest())
    print("Read-only audit completed. No state copied or changed.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Audit failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
