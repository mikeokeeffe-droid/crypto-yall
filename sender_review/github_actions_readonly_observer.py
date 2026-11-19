"""Read-only GitHub Actions run visibility for the existing original bots.

This checks PUBLIC GitHub workflow-run metadata from Hetzner via outbound HTTPS.
It is NOT a persistent server-to-server heartbeat, does not authenticate a
trading executor, cannot send messages to GitHub, and cannot issue orders.
No key, GitHub token, GitHub runner, service installation or firewall change.
Run manually before considering optional monitoring or an authenticated link.
"""
import datetime as dt
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

_ROOT = "https://api.github.com/repos/mikeokeeffe-droid/crypto-yall/actions/workflows/"
_WORKFLOWS = (
    ("daily", "execute-trades.yml"),
    ("intraday", "execute-intraday.yml"),
    ("aggressive", "execute-aggressive.yml"),
)
_MAX_RESPONSE = 128_000


@dataclass(frozen=True)
class RunObservation:
    bot: str
    state: str
    last_run: str | None = None
    conclusion: str | None = None
    age_minutes: int | None = None
    note: str = "Observation only; no live communication or trading authority"


def _iso_utc(value):
    if type(value) is not str:
        raise ValueError("missing run timestamp")
    result = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )
    return result


def interpret_workflow_response(bot, response, *, now):
    """Parse GitHub-supplied metadata, never infer a continuous heartbeat."""
    if type(now) is not dt.datetime or now.tzinfo is None:
        raise ValueError("require timezone-aware clock")
    if type(response) is not dict or type(response.get("workflow_runs")) is not list:
        raise ValueError("unexpected workflow response")
    runs = response["workflow_runs"]
    if not runs:
        return RunObservation(bot=bot, state="NO_RUNS",
                              note="No recent workflow run reported; no heartbeat verified")
    run = runs[0]
    if type(run) is not dict or type(run.get("status")) is not str:
        raise ValueError("invalid workflow run")
    status = run["status"]
    if status not in ("queued", "in_progress", "completed", "waiting",
                      "requested", "pending", "action_required"):
        raise ValueError("unrecognized workflow status")
    conclusion = run.get("conclusion")
    if conclusion is not None and (type(conclusion) is not str
                                   or conclusion not in (
                                       "success", "failure", "cancelled",
                                       "skipped", "timed_out", "action_required",
                                       "neutral", "stale", "startup_failure")):
        raise ValueError("unrecognized workflow conclusion")
    updated = _iso_utc(run.get("updated_at"))
    age = int((now - updated).total_seconds() // 60)
    if age < -2:
        raise ValueError("future-dated workflow run")
    return RunObservation(
        bot=bot, state=status.upper(), last_run=updated.isoformat(),
        conclusion=conclusion, age_minutes=max(0, age),
        note="Last GitHub run only; manual jobs may be idle by design; NOT a heartbeat",
    )


def _public_fetch(url):
    if url not in {_ROOT + wf + "/runs?per_page=1" for _, wf in _WORKFLOWS}:
        raise ValueError("unapproved workflow URL")
    req = urllib.request.Request(url, headers={
        "User-Agent": "crypto-yall-review-only-run-observer/1",
        "Accept": "application/vnd.github+json",
    }, method="GET")
    with urllib.request.urlopen(
        req, timeout=8, context=ssl.create_default_context()
    ) as resp:
        if resp.status != 200:
            raise ValueError("unexpected HTTP status")
        data = resp.read(_MAX_RESPONSE + 1)
        if len(data) > _MAX_RESPONSE:
            raise ValueError("oversized GitHub response")
        return json.loads(data.decode("utf-8"))


def observe_all(*, fetch=None, now=None):
    if fetch is None:
        fetch = _public_fetch
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    output = []
    for bot, workflow in _WORKFLOWS:
        try:
            output.append(interpret_workflow_response(
                bot, fetch(_ROOT + workflow + "/runs?per_page=1"), now=now
            ))
        except (OSError, ValueError, TypeError, UnicodeError, KeyError,
                json.JSONDecodeError):
            output.append(RunObservation(
                bot=bot, state="UNVERIFIED",
                note="Public workflow metadata unavailable or invalid; no heartbeat inferred",
            ))
    return tuple(output)


def main():
    observations = observe_all()
    for item in observations:
        print(
            f"{item.bot}: {item.state} "
            f"conclusion={item.conclusion or 'N/A'} "
            f"last_update={item.last_run or 'N/A'} "
            f"age_minutes={item.age_minutes if item.age_minutes is not None else 'N/A'}"
        )
    print("READ-ONLY RUN STATUS. NOT A SERVER HEARTBEAT. NO TRADING AUTHORITY.")
    return 1 if any(o.state == "UNVERIFIED" for o in observations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
