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


# These are conservative alert windows based on recorded historical GitHub
# dispatch cadence, NOT verified operator-approved schedules or service SLAs.
# Missing dispatches do not establish whether any trading server is running.
_HISTORICAL_GAP_MINUTES = {
    "daily": 2160,       # observed once per day; 36-hour alert
    "intraday": 180,     # observed once per hour; 3-hour alert
    "aggressive": 120,   # observed twice per hour; 2-hour alert
}


@dataclass(frozen=True)
class DispatchHistoryReview:
    bot: str
    verdict: str = "UNVERIFIED"
    age_minutes: int | None = None
    schedule_authoritatively_verified: bool = False
    live_bot_running_verified: bool = False
    open_position_protection_verified: bool = False
    restart_authorized: bool = False
    note: str = (
        "GitHub run history only; external dispatcher and account state unknown"
    )


def assess_dispatch_history_offline(observation):
    """Only classify recorded GitHub dispatch history; no network or authority."""
    if type(observation) is not RunObservation:
        return DispatchHistoryReview(bot="unknown")
    bot = observation.bot
    result = DispatchHistoryReview(bot=bot)
    max_age = _HISTORICAL_GAP_MINUTES.get(bot)
    if max_age is None:
        return result
    if observation.state == "NO_RUNS":
        return DispatchHistoryReview(bot=bot, verdict="NO_GITHUB_RUNS")
    if (observation.state == "UNVERIFIED"
            or type(observation.age_minutes) is not int
            or observation.age_minutes < 0):
        return result
    if observation.state == "COMPLETED" and observation.conclusion != "success":
        return DispatchHistoryReview(
            bot=bot, verdict="LAST_GITHUB_RUN_NOT_SUCCESSFUL",
            age_minutes=observation.age_minutes,
        )
    if observation.state != "COMPLETED":
        return DispatchHistoryReview(
            bot=bot, verdict="GITHUB_JOB_NOT_COMPLETED",
            age_minutes=observation.age_minutes,
        )
    if observation.age_minutes > max_age:
        return DispatchHistoryReview(
            bot=bot, verdict="HISTORICAL_DISPATCH_GAP",
            age_minutes=observation.age_minutes,
        )
    return DispatchHistoryReview(
        bot=bot, verdict="RECENT_GITHUB_RUN_ONLY",
        age_minutes=observation.age_minutes,
    )


def main():
    observations = observe_all()
    for item in observations:
        print(
            f"{item.bot}: {item.state} "
            f"conclusion={item.conclusion or 'N/A'} "
            f"last_update={item.last_run or 'N/A'} "
            f"age_minutes={item.age_minutes if item.age_minutes is not None else 'N/A'}"
        )
    reviews = tuple(assess_dispatch_history_offline(o) for o in observations)
    for reviewed in reviews:
        print(f"{reviewed.bot}: github_dispatch_evidence={reviewed.verdict}")
    print("GITHUB HISTORY ONLY. NO SERVER HEARTBEAT, POSITION OR TRADE AUTHORITY.")
    return 1 if any(
        reviewed.verdict != "RECENT_GITHUB_RUN_ONLY" for reviewed in reviews
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
