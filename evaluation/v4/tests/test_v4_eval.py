"""v4 평가 도구 시험(LLM · DB 없음).

cd backend && uv run python ../evaluation/v4/tests/test_v4_eval.py
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import budget
import build_sets
import judge
import kappa
import prices
from kit import est_tokens, wilson


class CombineTest(unittest.TestCase):
    def test_same_side_both_orders_wins(self):
        # 순서 1: 답 1 = A가 이김, 순서 2: 답 1 = B, 답 2(= A)가 이김 → A 승, 일관
        c = judge.combine("1", "A", "2", "B")
        self.assertEqual(
            (c["order1"], c["order2"], c["final"], c["consistent"]), ("A", "A", "A", True)
        )

    def test_position_bias_becomes_tie(self):
        # 두 번 모두 '답 1'을 고르면 위치만 따른 것 → 무승부, 불일치
        c = judge.combine("1", "A", "1", "B")
        self.assertEqual((c["final"], c["consistent"]), ("tie", False))

    def test_unknown_and_both_bad(self):
        self.assertEqual(judge.combine("unknown", "A", "unknown", "B")["final"], "unknown")
        self.assertEqual(judge.combine("both_bad", "A", "both_bad", "B")["final"], "both_bad")
        self.assertEqual(judge.combine("1", "A", "unknown", "B")["final"], "tie")

    def test_score_b(self):
        self.assertEqual(
            [judge.score_b(x) for x in ("B", "A", "tie", "both_bad")], [1.0, 0.0, 0.5, 0.5]
        )
        self.assertIsNone(judge.score_b("unknown"))


class PromptTest(unittest.TestCase):
    def item(self, a="답 가", b="답 나"):
        return judge.Item(
            id="t:1", source="core32", split="dev", group="knowledge", kind="", question="도배 며칠 걸려요?",
            history=[], home_text="32평", expect=["며칠"], avoid=["근거 없는 숫자"], ref={"gold": [], "gpt": ""},
            text={"A": a, "B": b}, facts={"A": "도배 2.5일", "B": "(없음)"}, labels={"A": "v2", "B": "v3"},
        )  # fmt: skip

    def test_labels_hidden_and_order_swapped(self):
        x = self.item()
        p1 = judge.shared_block(x) + judge.answers_block(x, "A")
        p2 = judge.answers_block(x, "B")
        self.assertNotIn("v2", p1)
        self.assertNotIn("v3", p1)
        self.assertLess(p1.index("답 가"), p1.index("답 나"))
        self.assertLess(p2.index("답 나"), p2.index("답 가"))

    def test_rubric_rules_present(self):
        text = judge.RUBRIC_PATH.read_text(encoding="utf-8")
        for must in ("길이로 점수 주지 말 것", "표준 대비 %", "unknown", "이유를 먼저"):
            self.assertIn(must, text)

    def test_stub_verdict_shape(self):
        v = judge.stub_verdict(self.item(), 1)
        self.assertEqual(set(v), set(judge.ALL))
        self.assertTrue(all(v[d]["pick"] in ("1", "2", "tie", "unknown") for d in judge.ALL))

    def test_flags(self):
        self.assertEqual(judge.flags("업체 견적이 표준견적서보다 6% 높아요"), ["std_compare"])
        self.assertEqual(judge.flags("부가세는 10%예요"), [])
        self.assertEqual(judge.flags("  "), ["empty"])


class KappaTest(unittest.TestCase):
    def test_perfect_and_chance(self):
        self.assertEqual(kappa.cohen_kappa(["A", "B", "tie"], ["A", "B", "tie"]), 1.0)
        self.assertIsNone(kappa.cohen_kappa(["A", "A"], ["A", "A"]))  # 우연 일치 1 → 정의 안 됨
        # 2 × 2 예: po = 0.7, pe = 0.5 → κ = 0.4
        a = ["B"] * 5 + ["A"] * 5
        b = ["B"] * 4 + ["A"] + ["A"] * 3 + ["B"] * 2
        self.assertAlmostEqual(kappa.cohen_kappa(a, b), 0.4, places=3)

    def test_rates_and_mapping(self):
        r = kappa.rates(["B", "B", "A", "tie"], ["B", "A", "A", "B"], "B")
        self.assertEqual((r["tp"], r["fn"], r["tn"], r["fp"]), (1, 1, 1, 1))
        self.assertEqual((r["tpr"], r["tnr"]), (0.5, 0.5))
        self.assertEqual(kappa.human_to_system("1", "B"), "B")
        self.assertEqual(kappa.human_to_system("2", "B"), "A")
        self.assertEqual(kappa.human_to_system("둘다나쁨", "A"), "tie")
        self.assertIsNone(kappa.human_to_system("모름", "A"))


class PriceTest(unittest.TestCase):
    def test_costs(self):
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", {"input": 1_000_000}), 4.0)
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", {"output": 1_000_000}), 20.0)
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", {"cache_read": 1_000_000}), 0.2)
        self.assertAlmostEqual(prices.cost_usd("claude-opus-5-5", {"cache_write": 1_000_000}), 5.0)
        self.assertAlmostEqual(
            prices.cost_usd("claude-haiku-5-5", {"input": 200_000}), 0.1
        )  # 긴 프롬프트 값
        self.assertIsNone(prices.cost_usd("모르는-모델", {"input": 10}))

    def test_usage_shapes(self):
        anth = {
            "input_tokens": 10,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 5,
            "output_tokens": 7,
        }
        self.assertEqual(
            prices.usage_of(anth), {"input": 10, "cache_write": 3, "cache_read": 5, "output": 7}
        )
        openai = {"input": 100, "cached": 40, "output": 9}
        self.assertEqual(
            prices.usage_of(openai), {"input": 60, "cache_write": 0, "cache_read": 40, "output": 9}
        )

    def test_cache_estimate(self):
        u1 = budget.judge_call_usage(3000, 1000, 2000, 1, True, 1800)
        u2 = budget.judge_call_usage(3000, 1000, 2000, 2, True, 1800)
        self.assertEqual((u1["cache_write"], u1["cache_read"]), (1000, 3000))
        self.assertEqual((u2["cache_write"], u2["cache_read"]), (0, 4000))


class KitTest(unittest.TestCase):
    def test_tokens_and_interval(self):
        self.assertEqual(est_tokens(""), 0)
        self.assertGreater(est_tokens("도배 며칠 걸려요?"), est_tokens("abc"))
        lo, hi = wilson(8, 10)
        self.assertTrue(0 < lo < 0.8 < hi <= 1)


class SetsTest(unittest.TestCase):
    def test_sets_pass_check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_sets.check_all(), 0)


if __name__ == "__main__":
    unittest.main()
