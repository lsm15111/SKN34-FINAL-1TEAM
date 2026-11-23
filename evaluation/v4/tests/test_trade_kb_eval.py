"""공정 지식 검색 기준선(trade_kb_eval) 시험: 문항 파일 꼴 · gold 비교 규칙 · 파일 색인(LLM · DB 없음).

cd backend && uv run python ../evaluation/v4/tests/test_trade_kb_eval.py
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend"))

import trade_kb_eval as ev


class SetsTest(unittest.TestCase):
    def test_sets_are_well_formed(self):
        self.assertEqual(ev.check_sets(), [])

    def test_each_trade_has_dev_and_heldout(self):
        for trade, path in ev.SET_FILES.items():
            rows = ev.jsonl(path)
            self.assertEqual(len(rows), 60, trade)
            self.assertEqual(sum(r["split"] == "heldout" for r in rows), 20, trade)


class MatchTest(unittest.TestCase):
    def test_norm_ignores_spaces_commas_units(self):
        text = "현관 바닥에서 1,200 mm까지, 5 ℃ 이상, 30 × 40cm, 40∼60 %, 140g/㎡"
        self.assertEqual(
            ev.found(["1200mm", "5℃ 이상", "30x40", "40~60%", "140g/m2"], text), [True] * 5
        )

    def test_alternatives_and_misses(self):
        self.assertEqual(
            ev.found(["맞댄이음|맞댐", "6mm", "톤온톤"], "맞댐으로 6mm 이하"), [True, True, False]
        )


class IndexTest(unittest.TestCase):
    def test_files_index_scores_both_ways(self):
        ix = ev.files_index(with_expert=True)
        rows = [r for p in ev.SET_FILES.values() for r in ev.jsonl(p)][:4]
        res = ev.score(ix, rows)
        self.assertEqual(len(res), 4)
        agg = ev.aggregate(res)
        self.assertIn("all/all", agg)
        self.assertTrue(all(0 <= v["top5_all"] <= 1 for v in agg.values()))


if __name__ == "__main__":
    unittest.main()
