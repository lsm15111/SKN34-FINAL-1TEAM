"""v4 비서 의도 평가 도구 시험(LLM · DB 없음): 지표 계산 · 거의 같은 글 찾기 · dev/held-out 점검.

cd backend && uv run python ../evaluation/v4/tests/test_v4_intent_eval.py
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "intent"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend"))

import collect
import metrics as M

LABS = ("a", "b", "c")


class MetricTest(unittest.TestCase):
    def test_per_label_and_macro_f1(self):
        gold = ["a", "a", "b", "c"]
        pred = ["a", "b", "b", None]  # None은 라벨 없음(되묻기)
        rows = M.per_label(gold, pred, LABS)
        self.assertEqual((rows["a"]["p"], rows["a"]["r"]), (1.0, 0.5))
        self.assertEqual((rows["b"]["p"], rows["b"]["r"]), (0.5, 1.0))
        self.assertEqual(rows["c"]["f1"], 0.0)
        self.assertAlmostEqual(M.macro_f1(gold, pred, LABS), (2 / 3 + 2 / 3 + 0) / 3)
        self.assertEqual(M.accuracy(gold, pred), 0.5)
        self.assertEqual(M.recall_of(gold, pred, "c"), 0.0)

    def test_macro_f1_skips_labels_missing_from_gold(self):
        self.assertEqual(M.macro_f1(["a", "a"], ["a", "a"], LABS), 1.0)

    def test_lenient_takes_alt(self):
        got = M.lenient(["a", "b"], [["b"], []], ["b", "a"])
        self.assertEqual(got, ["b", "b"])

    def test_ece(self):
        self.assertAlmostEqual(M.ece([0.75] * 4, [True, True, True, False]), 0.0)
        # 0.9로 자신했는데 반만 맞음: |0.5 − 0.9| = 0.4
        self.assertAlmostEqual(M.ece([0.9, 0.9], [True, False]), 0.4)
        self.assertEqual(M.ece([], []), 0.0)

    def test_curve(self):
        rows = M.curve([0.2, 0.6, 0.9], [False, True, True], [0.5])
        self.assertAlmostEqual(rows[0]["answered"], 2 / 3)
        self.assertEqual(rows[0]["acc"], 1.0)

    def test_bootstrap_is_seeded_and_brackets_value(self):
        vals = [1, 0, 1, 1, 0, 1, 1, 1]
        stat = lambda i: sum(M.pick(vals, i)) / len(i)
        a = M.bootstrap(stat, len(vals), reps=500)
        self.assertEqual(a, M.bootstrap(stat, len(vals), reps=500))
        self.assertLessEqual(a[0], 0.75)
        self.assertGreaterEqual(a[1], 0.75)

    def test_card_hits(self):
        self.assertEqual(M.card_hits([{None}, {"today"}], [{None}, {"a", "today"}]), [True, True])
        self.assertEqual(M.card_hits([{"x"}], [{None}]), [False])


class NearTest(unittest.TestCase):
    def test_same_text_is_one_and_spacing_is_ignored(self):
        idx = collect.NearIndex(["업체 추천해 주세요", "공사 날짜 언제예요"])
        s, j = idx.best("업체 추천해 주세요")
        self.assertAlmostEqual(s, 1.0)
        self.assertEqual(j, 0)
        self.assertEqual(collect.norm("업체 추천해 주세요!"), collect.norm("업체추천해주세요"))

    def test_unrelated_is_low(self):
        idx = collect.NearIndex(["업체 추천해 주세요"])
        self.assertLess(idx.best("공정표 보여 줘")[0], 0.2)


class SetsTest(unittest.TestCase):
    def test_dev_heldout_pass_checks(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = collect.check()
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
