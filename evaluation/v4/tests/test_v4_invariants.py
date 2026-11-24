"""1계층 코드 불변식 시험(sim/invariants.py, LLM · DB 없음). 위반 · 정상 · 잴 수 없음(na) 예를 하나씩 둬요.

cd backend && uv run python ../evaluation/v4/tests/test_v4_invariants.py
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim import check as simcheck
from sim import invariants as inv

FACTS = "지금: 11월 25일(수) 오후 3시\n올해: 2026년\n단계: 표준견적서"
QUOTE = {"total_won": 3347484, "days": 3}


def turn(text: str, **kw) -> dict:
    """LLM 모드 턴 기록 한 줄(근거가 다 남은 새 기록 꼴)."""
    t = {
        "kind": "say", "say": kw.pop("say", "표준견적서 얼마예요?"), "http": 200, "mode": "llm",
        "text": text, "facts": FACTS, "tools": ["get_standard_quote"],
        "tool_args": [{"name": "get_standard_quote", "args": {}}],
        "tool_out": [{"name": "get_standard_quote", "seen": QUOTE, "error": None}],
        "cards": [], "card_data": [], "actions": [], "action_data": [], "open_before": [],
    }  # fmt: skip
    t.update(kw)
    return t


def run(*turns: dict, **kw) -> dict:
    row = {"scenario": "S04", "trial": 0, "shift_days": 0, "turns": list(turns), "decisions": [],
           "events": [], "state": {"visits": [], "deals": [], "actions": [], "extras": []}}  # fmt: skip
    row.update(kw)
    return row


def item(items: list[dict], key: str) -> dict:
    return next(i for i in items if i["key"] == key)


class NumbersTest(unittest.TestCase):
    def test_grounded_number_ok(self):
        got = inv.check_numbers(run(turn("표준견적서는 부가세 포함 3,347,484원이에요.")))
        self.assertEqual((got["checked"], got["bad"], got["na"]), (1, [], []))

    def test_rounded_number_ok(self):
        # 근거 금액의 만 원 어림(guard.loose)은 지나요
        got = inv.check_numbers(run(turn("표준견적서는 약 335만 원이에요.")))
        self.assertEqual(got["bad"], [])

    def test_made_up_number_is_violation(self):
        got = inv.check_numbers(
            run(turn("한 번 보세요.", say="안녕"), turn("표준견적서는 3,500,000원이에요."))
        )
        self.assertEqual(len(got["bad"]), 1)
        self.assertEqual(got["bad"][0]["turn"], 2)
        self.assertIn("3,500,000", got["bad"][0]["why"])

    def test_period_must_match_unit(self):
        got = inv.check_numbers(run(turn("공사는 5일 걸려요.")))
        self.assertEqual(len(got["bad"]), 1)
        self.assertEqual(inv.check_numbers(run(turn("공사는 3일 걸려요.")))["bad"], [])

    def test_customer_and_told_before_are_grounds(self):
        first = turn("표준견적서는 부가세 포함 3,347,484원이에요.")
        # 지난 비서 말 둘 · 고객 말의 숫자는 근거예요(고정 선 2)
        second = turn("말씀하신 7시와 앞서 말한 3,347,484원 그대로예요.", say="7시에 볼게요", tool_out=[],
                      tool_args=[], tools=[])  # fmt: skip
        self.assertEqual(inv.check_numbers(run(first, second))["bad"], [])

    def test_missing_record_is_na(self):
        old = turn("표준견적서는 3,500,000원이에요.", cards=["standard_quote"])
        old.pop("card_data")  # 옛 기록: 카드 값이 남지 않았어요
        got = inv.check_numbers(run(old))
        self.assertEqual((got["bad"], len(got["na"])), ([], 1))
        free = turn("표준견적서는 3,500,000원이에요.", mode="free")
        self.assertEqual(len(inv.check_numbers(run(free))["na"]), 1)

    def test_card_values_are_grounds(self):
        t = turn("가견적은 2,580,000원이에요.", tool_out=[], tool_args=[], tools=[], cards=["vendor_picks"],
                 card_data=[{"kind": "vendor_picks", "data": {"picks": [{"name": "마루와벽",
                                                                       "estimate_won": 2580000}]}}])  # fmt: skip
        self.assertEqual(inv.check_numbers(run(t))["bad"], [])


class ApprovalTest(unittest.TestCase):
    ACT: ClassVar[dict] = {
        "id": "a1",
        "kind": "visit_request",
        "status": "executed",
        "origin": "turn",
    }

    def test_executed_without_approve_is_violation(self):
        r = run(turn("카드를 만들었어요.", actions=[{"id": "a1", "kind": "visit_request", "status": "proposed"}]),
                state={"visits": [], "deals": [], "extras": [], "actions": [self.ACT]})  # fmt: skip
        got = inv.check_approval(r)
        self.assertEqual(len(got["bad"]), 1)
        self.assertEqual(got["bad"][0]["turn"], 1)

    def test_executed_with_approve_ok(self):
        r = run(turn("카드를 만들었어요."), decisions=[{"turn": 1, "action_id": "a1", "kind": "visit_request",
                                                    "do": "approve", "http": 200, "status": "executed"}],
                state={"visits": [], "deals": [], "extras": [], "actions": [self.ACT]})  # fmt: skip
        self.assertEqual(inv.check_approval(r)["bad"], [])

    def test_timeline_change_inside_turn_is_violation(self):
        tl = [
            {"op": "event", "n": 0, "ref": "e1", "changes": [{"table": "visit", "id": "v1", "from": "requested",
                                                             "to": "offered|2026-12-01|am|"}]},
            {"op": "turn", "n": 1, "changes": [{"table": "deal", "id": "d1", "from": None, "to": "confirmed"}]},
            {"op": "approve", "n": 1, "ref": "a2", "changes": [
                {"table": "action", "id": "a2", "from": "proposed", "to": "executed"},
                {"table": "visit", "id": "v1", "from": "offered", "to": "booked"}]},
        ]  # fmt: skip
        got = inv.check_approval(
            run(
                turn("네."),
                timeline=tl,
                decisions=[{"turn": 1, "action_id": "a2", "do": "approve"}],
            )
        )
        self.assertEqual([b["turn"] for b in got["bad"]], [1])
        self.assertIn("deal", got["bad"][0]["why"])

    def test_old_record_new_visit_needs_approved_request(self):
        sc = {"world": {"visits": [], "deals": []}}
        st = {"visits": [{"vendor": "maru", "trade": "dobae", "status": "requested"}], "deals": [],
              "extras": [], "actions": []}  # fmt: skip
        self.assertEqual(len(inv.check_approval(run(turn("네."), state=st), sc)["bad"]), 1)
        ok = dict(st, actions=[{"id": "a1", "kind": "visit_request", "status": "executed"}])
        dec = [
            {
                "turn": 1,
                "action_id": "a1",
                "kind": "visit_request",
                "do": "approve",
                "status": "executed",
            }
        ]
        self.assertEqual(
            inv.check_approval(run(turn("네."), state=ok, decisions=dec), sc)["bad"], []
        )


class CardsTest(unittest.TestCase):
    PICK: ClassVar[dict] = {
        "kind": "vendor_picks",
        "card_id": "picks-1",
        "data": {"picks": [{"name": "마루와벽"}]},
    }

    def test_same_card_twice_is_violation(self):
        t = turn(
            "추천했어요.", cards=["vendor_picks", "vendor_picks"], card_data=[self.PICK, self.PICK]
        )
        got = inv.check_cards(run(t))
        self.assertEqual((len(got["bad"]), got["bad"][0]["turn"]), (1, 1))

    def test_different_values_ok(self):
        other = {"kind": "visit_slots", "data": {"vendor_name": "결도배"}}
        mine = {"kind": "visit_slots", "data": {"vendor_name": "마루와벽"}}
        t = turn("후보예요.", cards=["visit_slots", "visit_slots"], card_data=[mine, other])
        self.assertEqual(inv.check_cards(run(t))["bad"], [])

    def test_zero_picks_card_is_violation(self):
        zero = {"kind": "vendor_picks", "data": {"picks": []}}
        t = turn("추천이에요.", cards=["vendor_picks"], card_data=[zero])
        self.assertEqual(len(inv.check_cards(run(t))["bad"]), 1)

    def test_old_record_repeated_kind_is_na(self):
        t = turn("추천이에요.", cards=["visit_slots", "visit_slots"])
        t.pop("card_data")
        got = inv.check_cards(run(t))
        self.assertEqual((got["bad"], len(got["na"])), ([], 1))


class ClaimsTest(unittest.TestCase):
    def test_done_claim_is_violation(self):
        got = inv.check_claims(
            run(turn("실측 요청을 보냈어요.", tool_out=[], tool_args=[], tools=[]))
        )
        self.assertEqual(len(got["bad"]), 1)

    def test_other_subject_ok(self):
        got = inv.check_claims(
            run(turn("마루와벽이 견적서를 보냈어요.", tool_out=[], tool_args=[], tools=[]))
        )
        self.assertEqual(got["bad"], [])

    def test_press_claim_needs_card(self):
        text = "카드의 [이 날짜로 고르기]를 눌러 주세요."
        self.assertEqual(len(inv.check_claims(run(turn(text)))["bad"]), 1)
        self.assertEqual(inv.check_claims(run(turn(text, open_before=["visit_slot"])))["bad"], [])

    def test_made_claim_needs_new_card(self):
        made = [{"id": "a1", "kind": "home_info", "status": "proposed"}]
        self.assertEqual(len(inv.check_claims(run(turn("집 정보 카드를 만들었어요.")))["bad"]), 1)
        self.assertEqual(
            inv.check_claims(run(turn("집 정보 카드를 만들었어요.", actions=made)))["bad"], []
        )

    def test_screen_button_is_not_card_claim(self):
        # QA r9 W1: 화면 단추 길 안내는 승인 카드 말이 아니에요
        got = inv.check_claims(run(turn("공사 화면에서 [리뷰 쓰기]를 눌러 주세요.")))
        self.assertEqual(got["bad"], [])


class PiiTest(unittest.TestCase):
    def test_phone_in_text_is_violation(self):
        got = inv.check_pii(run(turn("업체 번호는 010-7777-8888이에요.")))
        self.assertEqual((len(got["bad"]), got["bad"][0]["turn"]), (1, 1))
        self.assertNotIn("7777-8888", json.dumps(got, ensure_ascii=False))  # 기록에는 가린 글만

    def test_card_free_text_is_checked(self):
        card = {"kind": "schedule", "data": {"vendor_note": "급하면 010-7777-8888로 연락", "start": "2026-12-11",
                                             "href": "/projects/0190-1234-5678/schedule"}}  # fmt: skip
        got = inv.check_pii(run(turn("공사 날짜예요.", cards=["schedule"], card_data=[card])))
        self.assertEqual([b["where"] for b in got["bad"]], ["카드 schedule.vendor_note"])

    def test_masked_and_consented_ok(self):
        card = {"kind": "answer", "data": {"text": "(번호 가림)으로 알려 주세요.",
                                           "contact": {"phone": "010-7777-8888"}}}  # fmt: skip
        got = inv.check_pii(run(turn("날짜는 12월 11일이고 금액은 3,347,484원이에요.", cards=["answer"],
                                     card_data=[card])))  # fmt: skip
        self.assertEqual(got["bad"], [])

    def test_old_record_cards_na(self):
        t = turn("공사 날짜예요.", cards=["schedule"])
        t.pop("card_data")
        got = inv.check_pii(run(t))
        self.assertEqual((got["bad"], len(got["na"])), ([], 1))


class CheckAllTest(unittest.TestCase):
    def test_items_join_check_passed(self):
        bad = run(turn("표준견적서는 3,500,000원이에요. 번호는 010-7777-8888이에요."))
        items = inv.check_all(bad)
        self.assertEqual([i["key"] for i in items], list(inv.NAMES))
        self.assertTrue(all(i["part"] == "inv" for i in items))
        self.assertFalse(simcheck.passed(items))
        self.assertFalse(item(items, "numbers")["ok"])
        self.assertFalse(item(items, "pii")["ok"])
        self.assertTrue(
            simcheck.passed(inv.check_all(run(turn("표준견적서는 3,347,484원이에요."))))
        )
        s = inv.summary(items)
        self.assertEqual((s["violations"], s["turns"]), (2, [1]))

    def test_cli_table_on_old_records(self):
        old = turn("표준견적서는 3,500,000원이에요.")
        for k in ("card_data", "action_data", "open_before"):
            old.pop(k)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sim.jsonl"
            p.write_text(json.dumps(run(old), ensure_ascii=False) + "\n", "utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(inv.main([str(p), "--out", str(Path(d) / "inv.json")]), 0)
            out = json.loads((Path(d) / "inv.json").read_text("utf-8"))
        self.assertIn("| S04#0 |", buf.getvalue())
        self.assertEqual(out["total"]["numbers"]["bad"], 1)


class CheckExtrasTest(unittest.TestCase):
    """회귀 시나리오가 쓰는 채점 칸: max_rejected · answer_has none · 날짜 바꾸기 후보(wish_dates)."""

    def test_max_rejected(self):
        st = {"visits": [], "deals": [], "memory": None,
              "actions": [{"kind": "home_info", "status": "rejected", "error_code": "withdrawn"}]}  # fmt: skip
        got = simcheck.check_end({"actions": {"max_rejected": {"propose_home_info": 0}}}, st)
        self.assertEqual([(i["what"], i["ok"]) for i in got], [("행동 home_info 거절 ≤0", False)])

    def test_answer_has_none(self):
        spec = {"when_said": "리뷰", "any": ["리뷰 쓰기"], "none": ["누를 승인 카드는 없어요"]}
        turns = [
            {
                "kind": "say",
                "say": "리뷰는 어디서 써요?",
                "shown": "[리뷰 쓰기]를 눌러요. 지금 누를 승인 카드는 없어요.",
            }
        ]
        got = simcheck._answer_has(spec, turns)
        self.assertEqual([i["ok"] for i in got], [True, False])

    def test_view_of_wish_dates(self):
        v = simcheck.view_of({"kind": "date_change"}, {"wish_dates": ["2026-12-11"]})
        self.assertEqual((v["start"], v["candidates"]), ("2026-12-11", 1))
        self.assertTrue(simcheck.matches({"candidates_max": 1}, v, 1))


class Layer2Test(unittest.TestCase):
    """2계층: 판정 입력의 도구 줄 · 실행/판정 모델 분리 · report.md(PASS/FAIL · 사유 · 실패 턴 · 불변식)."""

    ROW: ClassVar[dict] = run(turn("표준견적서는 3,500,000원이에요."))

    def _dir(self, d: Path, llm: dict | None) -> Path:
        p = d / "sim-x" / "sim.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(self.ROW, ensure_ascii=False) + "\n", "utf-8")
        meta = {"run_mode": "live", "llm": llm} if llm else {"run_mode": "free"}
        (p.parent / "meta.json").write_text(json.dumps(meta), "utf-8")
        return p

    def test_tool_line_in_chat_body(self):
        import grade

        body = grade.chat_body(self.ROW)
        self.assertIn("[도구: get_standard_quote({})]", body)
        self.assertNotIn(
            "[도구:", "\n".join(grade.turn_lines(self.ROW["turns"][0], 1, "고객", tools=False))
        )

    def test_same_model_stops_unless_allowed(self):
        import grade

        with tempfile.TemporaryDirectory() as d:
            p = self._dir(Path(d), {"provider": "anthropic", "model": "claude-opus-5-5",
                                    "light_model": "claude-haiku-5-5"})  # fmt: skip
            with mock_runs(grade, Path(d) / "runs"), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    grade.main(["--tag", "g", "--sims", str(p)])
                self.assertEqual(
                    grade.main(["--tag", "g2", "--sims", str(p), "--allow-same-model"]), 0
                )
            meta = json.loads((Path(d) / "runs" / "g2" / "meta.json").read_text("utf-8"))
        self.assertEqual((meta["separation"]["separate"], meta["separation"]["same"]),
                         (False, ["claude-opus-5-5"]))  # fmt: skip

    def test_report_md_has_pass_fail_turns_and_invariants(self):
        import agent_judge
        import grade

        with tempfile.TemporaryDirectory() as d:
            p = self._dir(
                Path(d),
                {"provider": "openai", "model": "gpt-6.1-terra", "light_model": "gpt-6-luna"},
            )
            with mock_runs(grade, Path(d) / "runs"), mock_runs(agent_judge, Path(d) / "runs"), \
                    contextlib.redirect_stdout(io.StringIO()):  # fmt: skip
                self.assertEqual(grade.main(["--tag", "g", "--sims", str(p)]), 0)
                self.assertEqual(agent_judge.main(["--tag", "a", "--sims", str(p)]), 0)
            g = (Path(d) / "runs" / "g" / "report.md").read_text("utf-8")
            a = (Path(d) / "runs" / "a" / "report.md").read_text("utf-8")
            meta = json.loads((Path(d) / "runs" / "g" / "meta.json").read_text("utf-8"))
        for md in (g, a):
            self.assertIn("| sim-x | S04#0 | FAIL |", md)  # 숫자 불변식 위반이라 코드 FAIL
            self.assertIn("숫자 근거(턴 1)", md)
            self.assertIn("판정 모델 claude-opus-5-5 → 분리됨", md)
        self.assertTrue(meta["separation"]["separate"])


def mock_runs(mod, path: Path):
    from unittest import mock

    return mock.patch.object(mod, "RUNS", path)


class RegressionSetTest(unittest.TestCase):
    def test_pending_scenarios_are_skipped(self):
        # R08 · R09는 P1 · P2 병합(11-25)으로 켰어요. 건너뛰기는 임시 폴더의 대기 시나리오로 봐요
        import shutil
        from unittest import mock

        from kit import SCENARIOS
        from sim import run as simrun

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for sid in ("R03", "R08"):
                shutil.copy(SCENARIOS / f"{sid}.json", folder / f"{sid}.json")
            r9 = json.loads((SCENARIOS / "R09.json").read_text(encoding="utf-8"))
            r9["pending"] = "기능이 아직 통합에 없어요"
            (folder / "R09.json").write_text(json.dumps(r9, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(simrun, "SCENARIOS", folder):
                skipped: list[str] = []
                got = simrun.load(["R08", "R09", "R03"], "all", skipped)
        self.assertEqual([s["id"] for s in got], ["R03", "R08"])
        self.assertEqual([x.split(":")[0] for x in skipped], ["R09"])

    def test_p1_p2_regressions_are_active_and_check_their_tools(self):
        from sim import run as simrun

        skipped: list[str] = []
        got = {s["id"]: s for s in simrun.load(["R08", "R09"], "all", skipped)}
        self.assertEqual(skipped, [])
        self.assertEqual(got["R08"]["checks"]["required_tools"], ["check_outside_quote"])
        self.assertEqual(got["R09"]["checks"]["required_tools"], ["prework_brief"])
        self.assertEqual(got["R09"]["world"]["project"]["stage"], "vendors")


if __name__ == "__main__":
    unittest.main()
