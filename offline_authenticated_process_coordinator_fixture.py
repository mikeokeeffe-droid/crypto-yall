"""Offline authenticated process-coordinator adapter, not a production IPC boundary.

Uses the existing spawned-process fixture, validates signed envelopes with a
durable replay ledger before forwarding. The verifier runs in the parent test
harness, so this DOES NOT authenticate a remote peer or protect against a
compromised same-user parent. No exchange SDK, network or live orders.
"""
from offline_authenticated_envelope_fixture import OfflineAuthenticatedEnvelopeVerifier
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_process_coordinator_fixture import OfflineProcessCoordinator

class OfflineAuthenticatedProcessCoordinator:
    def __init__(self,journal_path,replay_path,principals,keys):
        self._verifier=OfflineAuthenticatedEnvelopeVerifier(
            keys,ledger=OfflinePersistentReplayLedger(replay_path))
        self._coordinator=OfflineProcessCoordinator(journal_path,principals)

    def request(self,envelope):
        verified=self._verifier.verify(envelope)
        if verified is None:
            return ("hold",False)
        principal,operation,intent=verified
        return self._coordinator.request(principal,operation,intent)

    def close(self):
        self._coordinator.close()
