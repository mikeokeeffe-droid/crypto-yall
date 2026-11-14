"""Root-only three distinct Linux UID socket admission audit.

Disposable SQLite only. Actual subprocess UIDs are kernel-verified, with no
exchange, signer, production credentials, or live trading.
"""
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_sender_restart_journal import OfflineRestartJournal
from offline_socket_journal_bridge_fixture import handle_offline_journal_socket

ACCOUNT="0x"+"1"*40
BOTS=("daily","intraday","aggressive")

@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os,"geteuid")
                     and os.geteuid()==0 and hasattr(socket,"SO_PEERCRED"),
                     "requires Linux root and SO_PEERCRED")
class OfflineThreeDistinctUidSocketTests(unittest.TestCase):
    def test_three_actual_uids_compete_for_one_disposable_scope(self):
        users=[]
        seen=set()
        for user in pwd.getpwall():
            if user.pw_uid>0 and user.pw_uid not in seen:
                users.append(user)
                seen.add(user.pw_uid)
            if len(users)==3:
                break
        if len(users)<3:
            self.fail("requires three distinct nonroot UIDs")
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory,0o711)
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            path=os.path.join(directory,"coordinator.sock")
            allowed={user.pw_uid:(bot,"mainnet",ACCOUNT)
                     for user,bot in zip(users,BOTS)}
            results=[]
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(path)
                os.chmod(path,0o666) # deliberately open: test kernel identity, not file ACL
                listener.listen(3)
                def serve():
                    for _ in range(3):
                        connection,_=listener.accept()
                        with connection:
                            results.append(handle_offline_journal_socket(
                                connection,allowed,replay,journal))
                thread=threading.Thread(target=serve,daemon=True)
                thread.start()
                code=("import json,socket,struct,sys;"
                      "s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);"
                      "p=dict(operation='request_entry',requested_bot=sys.argv[2],"
                      "environment='mainnet',account=sys.argv[3],dex='',"
                      "coin='SOL',nonce=sys.argv[4]);"
                      "b=json.dumps(p).encode();"
                      "s.sendall(struct.pack('!I',len(b))+b);s.close()")
                processes=[]
                for user,bot in zip(users,BOTS):
                    def drop(u=user):
                        os.setgroups([])
                        os.setgid(u.pw_gid)
                        os.setuid(u.pw_uid)
                    processes.append(subprocess.Popen(
                        [sys.executable,"-c",code,path,bot,ACCOUNT,"nonce-"+bot],
                        preexec_fn=drop,stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,text=True))
                for proc in processes:
                    _,stderr=proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode,0,stderr)
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
            self.assertEqual(results.count(("reserved_offline_only",False)),1)
            self.assertEqual(results.count(("hold",False)),2)
            claim=OfflineRestartJournal(journal).inspect(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL")
            self.assertIn(claim[0],BOTS)

if __name__=="__main__":
    unittest.main()
