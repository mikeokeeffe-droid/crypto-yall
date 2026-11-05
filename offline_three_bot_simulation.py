"""Offline three-bot simulation; never imports executors or connects to an exchange.

The fake durable coordinator is deliberately shared across simulated restarts.
Order submission is fake and only records synthetic events. No production proof.
"""
import threading
import uuid
from shared_entry_admission import claim_shared_entry

class FakeSharedCoordinator:
    def __init__(self):
        self.lock = threading.Lock()
        self.claims = {}
        self.counter = 0
        self.lose_confirmation_for = set()

    def claim_intent(self, *, bot, coin, action, request_id):
        with self.lock:
            if coin in self.claims:
                return {"status": "blocked"}
            self.counter += 1
            claim = dict(status="claimed", bot=bot, coin=coin, action=action,
                         request_id=request_id, intent_id=str(uuid.uuid4()),
                         fence_token=self.counter)
            self.claims[coin] = claim
            if coin in self.lose_confirmation_for:
                raise TimeoutError("synthetic response lost after commit")
            return dict(claim)

class FakeExchange:
    def __init__(self):
        self.submissions = []
        self.lock = threading.Lock()

    def submit_fake(self, *, bot, coin, action, intent_id, fence_token):
        with self.lock:
            self.submissions.append((bot, coin, action, intent_id, fence_token))

def simulate_entry(coordinator, exchange, *, bot, coin, action, request_id):
    decision = claim_shared_entry(
        coordinator, bot=bot, coin=coin, action=action, request_id=request_id)
    if not decision.accepted:
        return decision
    # The fake exchange never places orders. Production requires independent
    # authentication, fencing and exchange-side order reconciliation.
    exchange.submit_fake(bot=bot, coin=coin, action=action,
                         intent_id=decision.intent_id,
                         fence_token=decision.fence_token)
    return decision
