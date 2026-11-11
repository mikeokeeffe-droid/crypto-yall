"""Linux root-only CI proof: offline fixture collector uses a distinct real UID.

A collector process writes an owner-only synthetic evidence file; three
separate bot UIDs cannot read or list it. Does NOT prove network egress is
blocked, nor that an exchange origin, signer or position is authenticated.
No HTTP, exchange SDK, production paths, trading keys or database access.
Run ONLY with sudo in a disposable GitHub Actions runner.
"""
import json
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import unittest

COLLECTOR_CHILD = r"""
import json,os,sys,uuid
from offline_readonly_collector_contract import (
    OfflineCollectorScope,build_offline_info_plan)
from offline_readonly_collector_runner import (
    OfflineFixtureTransportResult,run_offline_info_capture)
account="0x"+"1"*40
cloid="0x"+"a"*32
scope=OfflineCollectorScope(
    environment="mainnet",account=account,
    token=uuid.UUID("12345678-1234-4234-8234-123456789abc"),
    fence=4,cloid=cloid)
plan=build_offline_info_plan(
    scope=scope,request_type="userFillsByTime",
    start_ms=1000,end_ms=1500)
assert plan.status=="query_only" and not plan.network_authorized
raw=json.dumps([{
    "coin":"SOL","oid":1001,"tid":42,"time":1100,
    "side":"B","dir":"Open Long","hash":"0x"+"a"*64,
    "sz":"0.025","px":"100",
}],separators=(",",":")).encode()
fixture=OfflineFixtureTransportResult(
    status_code=200,final_url="https://api.hyperliquid.xyz/info",
    elapsed_ms=100,content_type="application/json",body=raw)
review=run_offline_info_capture(
    plan=plan,fixture_result=fixture,captured_at_ms=1200,now_ms=1300)
assert review.state=="review_only"
assert review.response_sha256 and not review.origin_authenticated
assert not review.history_complete and not review.ownership_verified
assert not review.submit_authorized
path=sys.argv[1]
flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
if hasattr(os,"O_NOFOLLOW"):
    flags|=os.O_NOFOLLOW
fd=os.open(path,flags,0o600)
try:
    with os.fdopen(fd,"wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
except BaseException:
    raise
print(json.dumps({
    "uid":os.getuid(),"state":review.state,
    "submit_authorized":review.submit_authorized,
    "origin_authenticated":review.origin_authenticated,
    "ownership_verified":review.ownership_verified}),flush=True)
"""

BOT_CHILD = r"""
import errno,json,os,sys
directory,path=sys.argv[1],sys.argv[2]
denied=[]
for operation in (lambda:os.listdir(directory),
                  lambda:open(path,"rb").read()):
    try:
        operation()
    except PermissionError as exc:
        denied.append(exc.errno in (errno.EACCES,errno.EPERM))
    else:
        denied.append(False)
print(json.dumps({"uid":os.getuid(),"denied":denied}),flush=True)
if denied!=[True,True]:
    sys.exit(19)
"""


@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os,"geteuid")
    and os.geteuid()==0,
    "requires disposable Linux root for real UID isolation test",
)
class IsolatedOfflineCollectorUidTests(unittest.TestCase):
    @staticmethod
    def _users():
        selected=[]
        seen=set()
        for user in pwd.getpwall():
            if user.pw_uid>0 and user.pw_uid not in seen:
                selected.append(user)
                seen.add(user.pw_uid)
            if len(selected)==4:
                break
        if len(selected)!=4:
            raise AssertionError("four distinct non-root Linux UIDs required")
        return selected

    @staticmethod
    def _run_as(user,source,*arguments):
        def drop():
            os.setgroups([])
            os.setgid(user.pw_gid)
            os.setuid(user.pw_uid)
        # No GitHub tokens, database credentials, exchange keys or user env.
        env={
            "PATH":os.environ.get("PATH","/usr/bin:/bin"),
            "PYTHONPATH":os.getcwd(),
            "PYTHONDONTWRITEBYTECODE":"1",
        }
        return subprocess.run(
            [sys.executable,"-c",source,*map(str,arguments)],
            env=env,preexec_fn=drop,capture_output=True,
            text=True,timeout=15,check=False,cwd=os.getcwd(),
        )

    def test_collector_and_three_bots_have_distinct_uid_file_boundary(self):
        collector,*bots=self._users()
        self.assertEqual(
            len({x.pw_uid for x in (collector,*bots)}),4,
        )
        with tempfile.TemporaryDirectory(prefix="offline-collector-ci-") as root:
            os.chown(root,collector.pw_uid,collector.pw_gid)
            os.chmod(root,0o700)
            path=os.path.join(root,"synthetic-receipts.json")
            result=self._run_as(collector,COLLECTOR_CHILD,path)
            self.assertEqual(result.returncode,0,result.stderr)
            message=json.loads(result.stdout)
            self.assertEqual(message,{
                "uid":collector.pw_uid,
                "state":"review_only",
                "submit_authorized":False,
                "origin_authenticated":False,
                "ownership_verified":False,
            })
            metadata=os.stat(path)
            self.assertEqual(metadata.st_uid,collector.pw_uid)
            self.assertEqual(stat.S_IMODE(metadata.st_mode),0o600)
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode),0o700)
            with open(path,"rb") as original:
                evidence=original.read()
            self.assertIn(b'"tid":42',evidence)

            for bot in bots:
                with self.subTest(bot_uid=bot.pw_uid):
                    attempt=self._run_as(bot,BOT_CHILD,root,path)
                    self.assertEqual(
                        attempt.returncode,0,
                        attempt.stdout+" "+attempt.stderr,
                    )
                    reply=json.loads(attempt.stdout)
                    self.assertEqual(reply["uid"],bot.pw_uid)
                    self.assertEqual(reply["denied"],[True,True])
            with open(path,"rb") as original:
                self.assertEqual(original.read(),evidence)


if __name__=="__main__":
    unittest.main()
