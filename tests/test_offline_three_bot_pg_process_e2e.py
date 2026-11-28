"""Cross-process end-to-end CI-only entry -> fake dispatch -> review.

Each phase runs in a separate interpreter with a distinct restricted test
PostgreSQL login. The simulated exchange is only FakeExchange. No original
executor, Hyperliquid SDK, signing key, production DB or real orders.
These processes share an OS UID; separate OS UID proof is a different test.
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

import psycopg

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")

_CHILD = r"""
import json,os,sys,uuid
import psycopg
mode=sys.argv[1]
def conn(name, password):
    return psycopg.connect(
        host='localhost',port=5432,dbname='safety_test',
        user=name,password=password)
if mode=='bot':
    from offline_original_bot_to_ci_sender import admit_original_entry_to_ci_sender
    bot=sys.argv[2]
    # Synthetic immutable decisions only, not importing existing executors.
    actions={'daily':('open_long','long'),
             'intraday':('open_short','short'),
             'aggressive':('open_long','long')}
    action,side=actions[bot]
    result=admit_original_entry_to_ci_sender(
        connection_factory=lambda:conn(
            'entry_login_'+bot, 'disposable-'+bot+'-only'),
        verified_bot=bot,
        trade={'action':action,'side':side,'hl_coin':sys.argv[3]},
        rounded_size='0.025',pinned_environment='mainnet',
        pinned_account=sys.argv[4],request_id=uuid.uuid4())
    print(json.dumps({
        'state':result.state,
        'token':str(result.token) if result.token else None,
        'fence':result.fence,
        'submit_authorized':result.submit_authorized,
    }),flush=True)
elif mode in ('sender','sender_crash'):
    from offline_ci_pg_fake_sender import simulate_postgres_fake_dispatch_once
    from offline_shared_sender_prototype import FakeExchange
    token=uuid.UUID(sys.argv[2])
    fence=int(sys.argv[3])
    fake=FakeExchange()
    if mode=='sender_crash':
        def fake_effect_then_crash(token,cloid):
            # Fixture-only durable proof of fake callback invocation.
            with open(sys.argv[4],'w',encoding='utf-8') as output:
                output.write(token+' '+cloid)
                output.flush()
                os.fsync(output.fileno())
            os._exit(87)
        fake.record_fake_attempt=fake_effect_then_crash
    result=simulate_postgres_fake_dispatch_once(
        sender_connection_factory=lambda:conn(
            'ci_sender_worker','disposable-sender-only'),
        token=token,fence=fence,fake=fake)
    print(json.dumps({
        'state':result.state,'attempts':len(fake.attempts),
        'submit_authorized':result.submit_authorized,
    }),flush=True)
elif mode=='review':
    from offline_ci_pg_sender_reconciliation import review_sender_fake_evidence
    token=uuid.UUID(sys.argv[2])
    fence=int(sys.argv[3])
    evidence=json.loads(sys.argv[4])
    result=review_sender_fake_evidence(
        reviewer_connection_factory=lambda:conn(
            'ci_sender_reviewer','disposable-reviewer-only'),
        token=token,fence=fence,evidence=evidence)
    print(json.dumps({
        'state':result.state,'reason':result.reason,
        'submit_authorized':result.submit_authorized,
        'ownership_verified':result.ownership_verified,
    }),flush=True)
else:
    sys.exit(97)
"""


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1"
    and os.getenv("PGDATABASE") == "safety_test"
    and os.getenv("PGHOST") in ("localhost", "127.0.0.1"),
    "requires localhost disposable PostgreSQL safety_test",
)
class CrossProcessThreeBotSenderReviewTests(unittest.TestCase):
    @staticmethod
    def admin():
        return psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="postgres",password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake_effect_path=os.path.join(self.tmp.name,"fake-effect.txt")
        with self.admin() as db:
            db.execute(
                "truncate public.ci_sender_attempts, "
                "public.ci_sender_intents restart identity"
            )

    def child(self, mode, *args):
        # Never pass PostgreSQL admin password or real CI secrets to children.
        env={
            "PATH":os.environ.get("PATH","/usr/bin:/bin"),
            "PYTHONPATH":os.getcwd(),
            "ISOLATED_POSTGRES_CI":"1",
            "PGDATABASE":"safety_test",
            "PGHOST":"localhost",
        }
        return subprocess.run(
            [sys.executable,"-c",_CHILD,mode,*map(str,args)],
            capture_output=True,text=True,timeout=18,check=False,env=env,
        )

    def parsed(self, mode, *args):
        result=self.child(mode,*args)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def journal(self):
        with self.admin() as db:
            return db.execute(
                "select i.token,i.fence_token,i.cloid,i.bot,i.coin,"
                "i.action,i.state,a.intent_token,a.cloid "
                "from public.ci_sender_intents i "
                "left join public.ci_sender_attempts a "
                "on a.intent_token=i.token order by i.coin"
            ).fetchall()

    @staticmethod
    def evidence(*, cloid, coin, action):
        side="long" if action=="open_long" else "short"
        return {
            "origin":"fixture","account":ACCOUNT,"environment":"mainnet",
            "coin":coin,"side":side,"cloid":cloid,"order_id":902,
            "status":"filled","requested_size":"0.025",
            "fills_complete":True,"position_provenance":"unverified",
            "fills":[
                {"fill_id":"f-1","order_id":902,"coin":coin,
                 "side":side,"size":"0.010"},
                {"fill_id":"f-2","order_id":902,"coin":coin,
                 "side":side,"size":"0.015"},
            ],
        }

    def test_three_bot_processes_one_coin_sender_then_readonly_review(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            admissions=list(pool.map(
                lambda bot:self.parsed("bot",bot,"SOL",ACCOUNT), BOTS,
            ))
        winners=[decision for decision in admissions
                 if decision["state"]=="reserved_offline_only"]
        self.assertEqual(len(winners),1,admissions)
        self.assertEqual(
            sum(decision["state"]=="hold" for decision in admissions),2,
        )
        self.assertTrue(all(not x["submit_authorized"] for x in admissions))
        token=uuid.UUID(winners[0]["token"])
        fence=winners[0]["fence"]
        rows=self.journal()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0:2],(token,fence))
        self.assertEqual(rows[0][6],"reserved")
        self.assertIsNone(rows[0][7])

        sent=self.parsed("sender",token,fence)
        self.assertEqual(sent,{
            "state":"observed_unverified","attempts":1,
            "submit_authorized":False,
        })
        self.assertEqual(self.parsed("sender",token,fence),{
            "state":"hold","attempts":0,"submit_authorized":False,
        })
        rows=self.journal()
        self.assertEqual(rows[0][6],"dispatch_unknown")
        self.assertEqual(rows[0][7],token)
        self.assertEqual(rows[0][8],rows[0][2])

        review=self.parsed(
            "review",token,fence,json.dumps(self.evidence(
                cloid=rows[0][2],coin="SOL",action=rows[0][5],
            )),
        )
        self.assertEqual(review["state"],"hold")
        self.assertIn("ownership unverified",review["reason"])
        self.assertFalse(review["submit_authorized"])
        self.assertFalse(review["ownership_verified"])
        self.assertEqual(self.parsed("bot","aggressive","SOL",ACCOUNT)["state"],
                         "hold")
        self.assertEqual(self.journal(),rows)

    def test_real_sender_process_exits_after_fake_effect_and_restarts_hold(self):
        admitted=self.parsed("bot","daily","SOL",ACCOUNT)
        self.assertEqual(admitted["state"],"reserved_offline_only")
        token=uuid.UUID(admitted["token"])
        fence=admitted["fence"]
        cloid=self.journal()[0][2]
        crashed=self.child("sender_crash",token,fence,self.fake_effect_path)
        self.assertEqual(crashed.returncode,87,crashed.stderr)
        with open(self.fake_effect_path,encoding="utf-8") as f:
            self.assertEqual(f.read(),str(token)+" "+cloid)
        row=self.journal()[0]
        self.assertEqual((row[6],row[7],row[8]),
                         ("dispatch_unknown",token,cloid))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            restarted=list(pool.map(
                lambda _:self.parsed("sender",token,fence),range(6),
            ))
        self.assertTrue(all(
            x=={"state":"hold","attempts":0,"submit_authorized":False}
            for x in restarted
        ))
        self.assertEqual(self.journal()[0],row)
        review=self.parsed(
            "review",token,fence,json.dumps(self.evidence(
                cloid=cloid,coin="SOL",action="open_long",
            )),
        )
        self.assertEqual(review["state"],"hold")
        self.assertFalse(review["ownership_verified"])

    def test_each_bot_process_can_enter_distinct_coin_and_stays_unverified(self):
        examples=(("daily","SOL"),("intraday","AVAX"),("aggressive","LINK"))
        for bot,coin in examples:
            with self.subTest(bot=bot,coin=coin):
                admission=self.parsed("bot",bot,coin,ACCOUNT)
                self.assertEqual(admission["state"],"reserved_offline_only")
                token=uuid.UUID(admission["token"])
                fence=admission["fence"]
                self.assertEqual(self.parsed("sender",token,fence)["attempts"],1)
                row=next(x for x in self.journal() if x[0]==token)
                review=self.parsed("review",token,fence,json.dumps(
                    self.evidence(cloid=row[2],coin=coin,action=row[5])
                ))
                self.assertEqual(review["state"],"hold")
                self.assertFalse(review["ownership_verified"])
        self.assertEqual(len(self.journal()),3)


if __name__=="__main__":
    unittest.main()
