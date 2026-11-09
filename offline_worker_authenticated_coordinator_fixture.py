"""Offline coordinator with signed-request verification inside worker process.

Still a disposable multiprocessing Pipe test, NOT production authenticated IPC:
same-UID parent can inspect keys, invoke underlying Pipe or access SQLite.
No SDK, network, signer, or live orders.
"""
from multiprocessing import get_context
from offline_sender_restart_journal import OfflineRestartJournal
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_protected_journal_fixture import OfflineProtectedJournalFixture
from offline_coordinator_boundary_fixture import (
    OfflineCoordinatorServerFixture,OfflineEntryIntent)
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_authenticated_envelope_fixture import OfflineAuthenticatedEnvelopeVerifier

def _authenticated_worker(pipe,journal_path,replay_path,principals,keys):
    try:
        journal=OfflineRestartJournal(journal_path)
        ledger=OfflinePersistentReplayLedger(replay_path)
        verifier=OfflineAuthenticatedEnvelopeVerifier(keys,ledger=ledger)
        identity=OfflineIdentityVerifier({
            principal:VerifiedFixtureIdentity(*scope)
            for principal,scope in principals.items()})
        server=OfflineCoordinatorServerFixture(
            OfflineProtectedJournalFixture(verifier=identity,journal=journal))
        pipe.send(("ready",None))
        while True:
            try:
                envelope=pipe.recv()
            except EOFError:
                break
            if envelope is None:
                break
            try:
                verified=verifier.verify(envelope)
                if verified is None:
                    pipe.send(("hold",False))
                    continue
                principal,operation,intent=verified
                if type(intent) is dict and set(intent)=={
                    "requested_bot","environment","account","dex","coin"}:
                    intent=OfflineEntryIntent(**intent)
                result=server.handle(principal=principal,operation=operation,intent=intent)
                pipe.send((result.state,result.submit_authorized))
            except Exception:
                pipe.send(("hold",False))
    except Exception:
        try:
            pipe.send(("error",False))
        except Exception:
            pass
    finally:
        pipe.close()

class OfflineWorkerAuthenticatedCoordinator:
    def __init__(self,journal_path,replay_path,principals,keys):
        ctx=get_context("spawn")
        self._pipe,child=ctx.Pipe()
        self._process=ctx.Process(
            target=_authenticated_worker,
            args=(child,journal_path,replay_path,principals,keys))
        self._process.start()
        child.close()
        if not self._pipe.poll(10) or self._pipe.recv()!=("ready",None):
            self.close()
            raise RuntimeError("offline authenticated worker unavailable")

    def request(self,envelope):
        try:
            self._pipe.send(envelope)
            if not self._pipe.poll(5):
                return ("hold",False)
            return self._pipe.recv()
        except (OSError,EOFError,BrokenPipeError):
            return ("hold",False)

    def close(self):
        try:
            self._pipe.send(None)
        except (OSError,EOFError,BrokenPipeError):
            pass
        self._process.join(timeout=3)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=3)
        self._pipe.close()
