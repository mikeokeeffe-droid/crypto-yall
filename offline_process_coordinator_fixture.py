"""Disposable offline coordinator in a separate Python process.

Uses multiprocessing Pipe for tests, not authenticated IPC or OS isolation.
Never loads exchange SDK, signing keys or network clients. The parent test
harness retains filesystem access, so this is NOT a security boundary.
"""
from multiprocessing import get_context
from offline_sender_restart_journal import OfflineRestartJournal
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_protected_journal_fixture import OfflineProtectedJournalFixture
from offline_coordinator_boundary_fixture import (
    OfflineCoordinatorServerFixture, OfflineEntryIntent)

def _worker(pipe, path, principals):
    try:
        journal=OfflineRestartJournal(path)
        verifier=OfflineIdentityVerifier({
            principal:VerifiedFixtureIdentity(*identity)
            for principal,identity in principals.items()})
        server=OfflineCoordinatorServerFixture(
            OfflineProtectedJournalFixture(verifier=verifier,journal=journal))
        pipe.send(("ready",None))
        while True:
            try:
                message=pipe.recv()
            except EOFError:
                break
            if message is None:
                break
            if type(message) is not dict:
                pipe.send(("hold",False))
                continue
            try:
                intent=message.get("intent")
                if type(intent) is dict and set(intent)=={
                    "requested_bot","environment","account","dex","coin"}:
                    intent=OfflineEntryIntent(**intent)
                result=server.handle(
                    principal=message.get("principal"),
                    operation=message.get("operation"),intent=intent)
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

class OfflineProcessCoordinator:
    def __init__(self,path,principals):
        ctx=get_context("spawn")
        self._pipe,child=ctx.Pipe()
        self._process=ctx.Process(target=_worker,args=(child,path,principals))
        self._process.start()
        child.close()
        if not self._pipe.poll(10) or self._pipe.recv()!=("ready",None):
            self.close()
            raise RuntimeError("offline coordinator unavailable")

    def request(self,principal,operation,intent=None):
        try:
            self._pipe.send(dict(principal=principal,operation=operation,intent=intent))
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
