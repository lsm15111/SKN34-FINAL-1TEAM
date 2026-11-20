"""run_compare가 Claude 관문(_guard → 호출 → _sink → llm_usage)을 타는지 대본으로 확인해요(유료 호출 0회).

시험 DB(mitjip_eval_gate)와 Redis 10번을 써요. Docker DB가 없으면 건너뛰어요.
cd backend && uv run python ../evaluation/v4/tests/test_v4_gate.py
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import apienv

ROW = {"id": "gate-1", "turns": ["도배 기간은 보통 며칠 걸려요?"], "home": "H32"}


class GateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apienv.free_mode()
        apienv.load_db_env()
        try:
            cls.app = apienv.App("mitjip_eval_gate", 10).boot()
        except Exception as e:  # noqa: BLE001 - DB · Redis가 없으면 이 시험은 건너뛰어요
            raise unittest.SkipTest(f"시험 DB를 못 올려요({type(e).__name__})") from None
        import home as homes
        import run_compare as rc

        from app.agent import llm

        cls.rc, cls.llm, cls.home = rc, llm, homes.HOMES["H32"]
        cls.tap = rc.UsageTap(llm)
        rc.patch_v2_store()
        rc.patch_v2_repo_kb()

    @classmethod
    def tearDownClass(cls):
        cls.llm.clear_stubs()
        cls.app.close()

    def setUp(self):
        self.app.reset()
        self.tap.take()

    def test_v2_goes_through_the_ledger(self):
        self.llm.set_claude_script(
            [{"text": "보통 이틀이에요.", "usage": {"input": 1000, "output": 200}}]
        )
        with self.llm.call_ctx() as ctx:
            asyncio.run(self.rc.V2().answer(ROW, self.home))
        rows = self.tap.take()
        self.assertEqual([r["purpose"] for r in rows], ["v2_chat"])
        self.assertTrue(rows[0]["model"].startswith("claude-"))
        # Sonnet 5.5: 입력 1,000 × $2/M + 출력 200 × $10/M = $0.004
        self.assertAlmostEqual(rows[0]["ledger_usd"], 0.004, places=9)
        self.assertEqual(ctx.spent_micros, 4000)
        got = self.app.query("select purpose, model, cost_micros, ok from llm_usage")
        self.assertEqual([(g["purpose"], g["cost_micros"], g["ok"]) for g in got],
                         [("v2_chat", 4000, True)])  # fmt: skip

    def test_v3_llm_mode_goes_through_the_ledger(self):
        # 꼴이 틀린 답 · 대본 끝도 장부에 실패로 남아요(유료였다면 낸 돈이 빠지지 않게)
        self.llm.set_claude_script([{"text": "{}", "usage": {"input": 500, "output": 50}}] * 3)
        res = asyncio.run(self.rc.V3("repo", "llm", False).answer(ROW, self.home))
        rows = self.tap.take()
        self.assertTrue(rows, "v3 llm 모드가 장부 관문을 지나지 않았어요")
        ledger = self.app.query("select purpose from llm_usage")
        self.assertEqual(len(ledger), len(rows))
        self.assertTrue(all(r["purpose"] in self.llm.PURPOSES for r in rows))
        self.assertIn("text", res)

    def test_auto_mode_follows_available(self):
        self.assertFalse(self.llm.available())
        self.assertEqual(self.rc.v3_mode("auto"), "free")
        self.assertEqual(self.rc.v3_mode("llm"), "llm")
        self.assertIsNone(asyncio.run(self.rc.ledger_ready()))


if __name__ == "__main__":
    unittest.main()
