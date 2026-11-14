"""Credential-free, in-memory sender prototype for CI review only.

Not a distributed lock, production order sender, or ownership proof.
No SDK, database, network, signer, credentials, or real order methods.
"""
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

_BOTS = frozenset(("daily", "intraday", "aggressive"))

@dataclass(frozen=True)
class SimulatedResult:
    state: str
    token: str | None = None
    cloid: str | None = None
    fence: int | None = None
    reason: str = ""
    submit_authorized: bool = False

class FakeExchange:
    """Fake recorder only; no real order methods or network access."""
    def __init__(self):
        self.attempts = []
    def record_fake_attempt(self, token, cloid):
        self.attempts.append((token, cloid))
        return {"fixture": True, "order_id": len(self.attempts)}

class OfflineSharedSender:
    def __init__(self):
        self._mutex = Lock()
        self._claims = {}
        self._next_fence = 0
        self._attempted = set()

    @staticmethod
    def _scope(environment, account, dex, coin):
        if (environment not in ("mainnet", "testnet")
                or type(account) is not str or len(account) != 42
                or not account.startswith("0x")
                or any(c not in "0123456789abcdef" for c in account[2:])
                or dex != ""
                or type(coin) is not str or not coin.isascii()
                or not coin.isalnum() or coin != coin.upper()):
            return None
        return (environment, account, dex, coin)

    def reserve(self, *, bot, environment, account, dex, coin, side, size):
        scope = self._scope(environment, account, dex, coin)
        if (scope is None or bot not in _BOTS
                or side not in ("long", "short")
                or type(size) is not str or not size.isdigit()
                or int(size) <= 0):
            return SimulatedResult("hold", reason="invalid synthetic intent")
        with self._mutex:
            if scope in self._claims:
                return SimulatedResult("hold", reason="scope already reserved")
            self._next_fence += 1
            token = str(uuid4())
            cloid = "0x" + uuid4().hex
            self._claims[scope] = (bot, token, cloid, self._next_fence)
            return SimulatedResult("reserved", token, cloid, self._next_fence,
                                   "offline fixture only")

    def simulate_once(self, *, environment, account, dex, coin, token, fence, fake):
        scope = self._scope(environment, account, dex, coin)
        if scope is None or type(fake) is not FakeExchange:
            return SimulatedResult("hold", reason="invalid fake exchange or scope")
        with self._mutex:
            claim = self._claims.get(scope)
            if (claim is None or type(token) is not str or type(fence) is not int
                    or claim[1] != token or claim[3] != fence
                    or token in self._attempted):
                return SimulatedResult("hold", reason="stale or replayed claim")
            self._attempted.add(token)  # mark unknown before fake side effect
            try:
                fake.record_fake_attempt(token, claim[2])
            except Exception:
                return SimulatedResult("hold", reason="fake outcome unknown")
            return SimulatedResult("observed_unverified", token, claim[2], fence,
                                   "synthetic attempt only; no ownership proof")
