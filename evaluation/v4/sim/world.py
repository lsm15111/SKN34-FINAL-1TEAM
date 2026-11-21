"""시나리오 world를 시험 DB에 심고 events를 일으켜요. 공개 API(ASGI)로 하고, API로 만들 수 없는 앞 상태만 SQL로 넣어요.

- 사람: 고객 가입 → v3 집 정보로 공사 하나, 업체 가입 → 승인(SQL, 백엔드 시험과 같음) → 업체 정보 → 도배 단가 확인.
- 실측 · 견적서 · 확정 · 공사 날짜: 고객 · 업체 화면이 부르는 API 그대로예요(담기 → 요청 → 기간 답하기 → 고르기 →
  견적서 보내기 → 확정 → 날짜 내기 → 수락).
- SQL로 넣는 것(notes에 남겨요): 업체 승인, '실측 받음'(반나절이 지나야 누를 수 있어 시간 건너뜀), 목공 확정
  (v3 공사는 집 정보가 도배만이라 목공 요청을 API로 만들 수 없어요. 백엔드 test_dates.mokgong_scheduled와 같은 방법),
  공사 끝 전 공사 날짜 앞당기기(공사 날이 지나야 끝을 올릴 수 있어 시간 건너뜀).
- 시간 흐름(clock_tick): 그 시각으로 비서 시간 트리거(hourly)와 정리(sweep)만 한 차례 돌려요.
- 모든 사람 · 업체 · 번호는 합성 값이에요. 비밀번호는 시험 DB에만 있는 합성 값이에요.
"""

import hashlib
import math
import re
import uuid
from datetime import date, timedelta

PASSWORD = "eval-pass-1234"  # 합성 계정(시험 DB에만)
PDF = b"%PDF-1.4\n" + b"0" * 64
DEFAULT_AREA = "105.8"  # 면적을 모르는 시나리오: 32평 공급 면적 임시값(v3 집 정보는 면적 필수)
QUOTE_DEFAULT = {"total": 3_300_000, "vat": "included", "days": 3}
PAPER_MAX = 60  # 견적서 벽지 사양 칸(업체가 적는 글 칸)
INTRO_MAX = 60
WISH_FROM = 2  # 희망 기간은 실제 오늘 + 2일부터(백엔드 시험 도우미와 같음)


class SeedError(Exception):
    """world · event를 API로 만들지 못함. 메시지에는 오류 코드 · 정해 둔 문장만 둬요."""


def digits(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d if len(d) in (10, 11) else "01000000000"


def phone_fmt(phone: str | None) -> str:
    d = digits(phone)
    return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"


def biz_no(email: str) -> str:
    """이메일마다 다른 합성 사업자등록번호 10자리(실제 번호 아님)."""
    return f"{int(hashlib.sha256(email.encode()).hexdigest(), 16) % 10**10:010d}"


def price_lines(fid: str, wall: int) -> dict:
    """도배 단가(근거 파일 연결). 업체마다 벽 단가를 조금씩 달리해 가견적 순서가 생겨요."""
    return {
        "lines": [
            {"key": "wall", "unit_price": wall, "source_file_id": fid},
            {"key": "ceiling", "unit_price": 6800, "source_file_id": fid},
            {"key": "paper_basic", "unit_price": 3400},
            {"key": "primer", "included_in": "paper_basic", "source_file_id": fid},
        ]
    }


def split_address(address: str | None) -> dict:
    """'서울 마포구 ○○아파트 101동 1203호' → 아파트 이름 · 동 · 호(연락처 나누기 칸)."""
    a = address or ""
    dong = re.search(r"(\d{1,4})동", a)
    ho = re.search(r"(\d{1,5})호", a)
    apt = re.search(r"(\S*아파트)", a)
    return {
        "apt_name": apt[1] if apt else "예시아파트",
        "dong": dong[1] if dong else None,
        "ho": ho[1] if ho else None,
    }


class World:
    def __init__(self, api, query, today: date, call=None) -> None:
        from app.config import settings

        self.api, self.q, self.today = api, query, today
        self.call = call  # 앱 루프에서 async 함수 돌리기(시간 흐름 event)
        self.cookie = settings.session_cookie
        self.vendors: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.visits: dict[str, dict] = {}
        self.deals: dict[str, dict] = {}
        self.notes: list[str] = []
        self._n = 0

    # ---- 바탕 ----

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def as_(self, who: dict) -> None:
        self.api.cookies.clear()
        self.api.cookies.set(self.cookie, who["token"])

    @staticmethod
    def need(r, what: str, ok=(200, 201, 204)) -> dict:
        if r.status_code not in ok:
            try:
                err = r.json().get("error") or {}
            except ValueError:
                err = {}
            msg = f"{what}: {r.status_code} {err.get('code', '')} {err.get('message', '')}"
            raise SeedError(msg.strip())
        if r.content and r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return {}

    def _upload(self, kind: str, name: str) -> str:
        r = self.api.post(
            "/files", data={"kind": kind}, files={"file": (name, PDF, "application/octet-stream")}
        )
        return self.need(r, f"파일 올리기({kind})")["id"]

    def _uid(self, email: str) -> uuid.UUID:
        return self.q("select id from users where email = $1", email)[0]["id"]

    # ---- 사람 ----

    def vendor(self, spec: dict, *, intro: str | None = None, phone: str | None = None) -> dict:
        ref = spec["ref"]
        if ref in self.vendors:
            return self.vendors[ref]
        email = f"v-{ref}@mitjip.test"
        trades = [t for t in spec.get("trades") or ["dobae"] if t in ("dobae", "mokgong")]
        trades = trades or ["dobae"]
        gus = list(dict.fromkeys(spec.get("areas") or [spec.get("gu") or "마포구"]))
        tel = phone or spec.get("phone") or "010-5937-2210"
        self.api.cookies.clear()
        data = {
            "name": "예시 담당자",
            "email": email,
            "password": PASSWORD,
            "biz_name": spec["name"],
            "owner_name": "예시 대표",
            "biz_no": biz_no(email),
            "phone": digits(tel),
            "trades": trades,
            "areas": [f"seoul/{g}" for g in gus],
        }
        lic = {"license_file": ("사업자등록증.pdf", PDF, "application/octet-stream")}
        self.need(self.api.post("/auth/vendor-signup", data=data, files=lic), "업체 가입")
        token = self.api.cookies.get(self.cookie)
        self.q(
            "update vendors set status = 'approved', reviewed_at = now(), approved_at = now()"
            " where user_id = (select id from users where email = $1)",
            email,
        )
        body = {
            "updated_at": None,
            "phone": phone_fmt(tel),
            "address": "서울특별시 마포구 예시로 1",
            "site_url": "www.example.com",
            "trades": trades,
            "areas": [{"sido": "seoul", "sgg": g} for g in gus],
            "contact_method": "phone",
            "call_start": "09:00",
            "call_end": "18:00",
            "visit_fee": 0,
            "interior_license": "등록했어요",
            "faqs": [],
            "links": [],
        }
        if intro:
            body["intro"] = intro[:INTRO_MAX]
            if len(intro) > INTRO_MAX:
                self.note(f"업체 소개는 {INTRO_MAX}자까지라 앞부분만 넣었어요")
        self.need(self.api.put("/vendor/profile", json=body), "업체 정보")
        if "dobae" in trades and spec.get("price_confirmed", True):
            fid = self._upload("price_doc", "단가근거.pdf")
            r = self.api.post("/vendor/price-files", json={"file_id": fid, "trade": "dobae"})
            self.need(r, "단가 근거 파일")
            r = self.api.put("/vendor/prices/dobae", json=price_lines(fid, 6650 + 350 * self._n))
            self.need(r, "도배 단가")
            self.need(self.api.post("/vendor/prices/dobae/confirm"), "도배 단가 확인")
        uid = self._uid(email)
        self.q("update vendors set biz_name = $1 where user_id = $2", spec["name"], uid)
        self._n += 1
        if "mokgong" in trades:
            self.note("목공 단가는 넣지 않았어요(도배 단가만)")
        if any(k in spec for k in ("rating", "reviews", "done")):
            self.note("업체 별점 · 후기 · 시공 수는 심지 않았어요(지난 공사가 있어야 생겨요)")
        if spec.get("free_halves"):
            self.note("업체 빈 반나절은 따로 심지 않았어요(예약이 없으면 모두 빈칸이에요)")
        got = {"ref": ref, "email": email, "token": token, "id": str(uid), "name": spec["name"],
               "areas": gus, "profile": body}  # fmt: skip
        self.vendors[ref] = got
        return got

    def set_areas(self, ref: str, gus: list[str]) -> None:
        """업체 정보 화면에서 다니는 지역을 바꾼 것처럼(본 updated_at을 같이 보내요)."""
        v = self.vendors[ref]
        self.as_(v)
        cur = self.need(self.api.get("/vendor/profile"), "업체 정보 읽기")
        body = {**v["profile"], "updated_at": cur.get("updated_at")}
        body["areas"] = [{"sido": "seoul", "sgg": g} for g in gus]
        self.need(self.api.put("/vendor/profile", json=body), "업체 지역 바꾸기")

    def customer(self, spec: dict, home: dict, *, name: str = "고객") -> dict:
        ref = spec.get("ref") or "c1"
        if ref in self.customers:
            return self.customers[ref]
        email = f"c-{ref}@mitjip.test"
        self.api.cookies.clear()
        body = {
            "name": spec.get("name") or name,
            "email": email,
            "password": PASSWORD,
            "phone": digits(spec.get("phone")),
        }
        self.need(self.api.post("/auth/signup", json=body), "고객 가입")
        token = self.api.cookies.get(self.cookie)
        area, basis = home.get("area_m2"), home.get("area_basis") or "supply"
        if area is None and home.get("pyeong"):
            area, basis = round(float(home["pyeong"]) * 3.3058, 1), "supply"
            self.note("면적을 몰라 평형 × 3.3058㎡(공급)로 넣었어요(v3 집 정보는 면적 필수)")
        elif area is None:
            area, basis = DEFAULT_AREA, "supply"
            self.note(
                f"면적을 몰라 {DEFAULT_AREA}㎡(공급) 임시값으로 넣었어요(v3 집 정보는 면적 필수)"
            )
        project = {
            "sido": "seoul",
            "sgg": spec.get("gu") or "마포구",
            "area_m2": str(area),
            "area_basis": basis,
            "occupied": home.get("living") == "living",
            "grade": home.get("grade") or "basic",
        }
        start = home.get("start_wish")
        if start:
            project["start_date"] = start
        if home.get("budget_won"):
            project["budget_won"] = home["budget_won"]
        r = self.api.post("/projects", json=project)
        if r.status_code == 422 and start:
            project.pop("start_date")
            self.note("공사 시작 희망일이 맞지 않아 비우고 만들었어요")
            r = self.api.post("/projects", json=project)
        pid = self.need(r, "공사 만들기")["id"]
        if home.get("diy") is not None:  # 반셀프 직접 할 일 칩(기본 정보 갈래의 칩 화면 대신)
            self.set_chips(pid, home["diy"])
        if "mokgong" in (home.get("trades") or []) or home.get("mokgong"):
            self.note("v3 집 정보는 도배만이라 목공 공정은 공사에 넣지 못했어요")
        got = {"ref": ref, "email": email, "token": token, "id": str(self._uid(email)), "pid": pid,
               "gu": project["sgg"]}  # fmt: skip
        self.customers[ref] = got
        return got

    def set_chips(self, pid: str, keys: list[str]) -> None:
        """반셀프 직접 할 일 칩을 저장 약속(project.diy.set_diy)으로 넣어요. 빈 목록은 '없어요'예요."""
        from app.db import SessionLocal
        from app.project.diy import set_diy

        if self.call is None:
            raise SeedError("직접 할 일 칩은 앱 루프가 있어야 심을 수 있어요")

        async def go():
            async with SessionLocal() as s:
                await set_diy(s, uuid.UUID(pid), list(keys))
                await s.commit()

        self.call(go)

    # ---- 실측 ----

    def wish(self, wish: list[str] | None) -> tuple[str, str]:
        lo = self.today + timedelta(days=WISH_FROM)
        if wish:
            a, b = date.fromisoformat(wish[0]), date.fromisoformat(wish[1])
        else:
            a, b = lo, lo + timedelta(days=14)
        if a < lo:
            n = max((b - a).days, 7)
            a, b = lo, lo + timedelta(days=n)
            self.note("지난 희망 기간은 실제 오늘 + 2일부터로 옮겼어요")
        return a.isoformat(), b.isoformat()

    def request(
        self,
        cust: dict,
        vendors: list[dict],
        trade: str = "dobae",
        *,
        wish: list[str] | None = None,
        message: str | None = None,
        share: dict | None = None,
    ) -> dict[str, str]:
        """담기 → 실측 요청. 업체 ref → 요청 id."""
        if trade != "dobae":
            raise SeedError("목공 실측 요청은 v3 공사(집 정보 도배만)에서 만들 수 없어요")
        self.as_(cust)
        for v in vendors:
            r = self.api.post(
                f"/projects/{cust['pid']}/shortlist", json={"trade": trade, "vendor_id": v["id"]}
            )
            if (
                r.status_code not in (200, 201)
                and r.json().get("error", {}).get("code") != "already"
            ):
                self.need(r, "업체 담기")
        a, b = self.wish(wish)
        body = {
            "trade": trade,
            "vendor_ids": [v["id"] for v in vendors],
            "wish_start": a,
            "wish_end": b,
        }
        if message:
            body["message"] = message[:300]
        if share:
            from app.visit.service import CONSENT_VER

            body.update(
                share_contact_ids=[v["id"] for v in vendors], consent_ver=CONSENT_VER, **share
            )
        r = self.api.post(f"/projects/{cust['pid']}/visits", json=body)
        if r.status_code == 422 and share:
            for k in ("share_contact_ids", "consent_ver", "apt_name", "dong", "ho"):
                body.pop(k, None)
            self.note("연락처 나누기 칸을 v3 요청이 받지 않아 빼고 보냈어요")
            r = self.api.post(f"/projects/{cust['pid']}/visits", json=body)
        self.need(r, "실측 요청")
        out = {}
        for v in vendors:
            rows = self.q(
                "select id from visits where project_id = $1 and vendor_id = $2 and trade = $3"
                " order by attempt desc limit 1",
                uuid.UUID(cust["pid"]),
                uuid.UUID(v["id"]),
                trade,
            )
            out[v["ref"]] = str(rows[0]["id"])
        return out

    def visit(self, spec: dict, cust_ref: str) -> str:
        """world.visits 한 줄을 그 상태까지 만들어요. 요청 ref를 돌려줘요."""
        ref, trade = spec["ref"], spec.get("trade") or "dobae"
        vendor = self.vendors[spec["vendor"]]
        cref = spec.get("customer") if spec.get("customer") in self.customers else cust_ref
        cust = self.customers[cref]
        outside = cust["gu"] not in vendor["areas"]
        if outside:  # 지역 밖 요청은 API가 막아요: 잠깐 지역을 넓혀 요청을 받고 되돌려요
            self.set_areas(vendor["ref"], vendor["areas"] + [cust["gu"]])
        try:
            vid = self.request(
                cust,
                [vendor],
                trade,
                wish=spec.get("wish"),
                message=spec.get("note"),
                share=spec.get("share"),
            )[vendor["ref"]]
        finally:
            if outside:
                self.set_areas(vendor["ref"], vendor["areas"])
        if outside:
            self.note(
                "지역 밖 요청은 API가 막아서, 업체 지역을 잠깐 넓혀 요청을 받은 뒤 되돌렸어요"
            )
        self.visits[ref] = {
            "id": vid,
            "vendor": vendor["ref"],
            "customer": cust["ref"],
            "trade": trade,
        }
        status = spec.get("status") or "requested"
        if status not in ("requested", "offered", "booked", "visited", "quoted"):
            raise SeedError(f"앞 상태 {status}는 아직 못 심어요")
        if status in ("offered", "booked", "visited", "quoted"):
            self.answer_window(ref)
        if status in ("booked", "visited", "quoted"):  # v3 견적서는 실측 확정 뒤에만 보내요
            self.pick(ref)
        if status == "visited":
            self.mark_visited(ref)
        if status == "quoted":
            self.send_quote(ref, spec.get("quote") or {})
        return ref

    def visit_ref(self, args: dict, cust_ref: str) -> str:
        """event 인자 → 요청 ref. 비서가 만든 요청(승인 실행)은 DB에서 찾아 이름을 붙여요."""
        if args.get("visit"):
            return args["visit"]
        vendor, trade = args["vendor"], args.get("trade") or "dobae"
        for ref, v in self.visits.items():
            if v["vendor"] == vendor and v["trade"] == trade:
                return ref
        cust = self.customers[cust_ref]
        rows = self.q(
            "select id from visits where project_id = $1 and vendor_id = $2 and trade = $3"
            " order by attempt desc limit 1",
            uuid.UUID(cust["pid"]),
            uuid.UUID(self.vendors[vendor]["id"]),
            trade,
        )
        if not rows:
            raise SeedError(f"{vendor} {trade} 실측 요청이 없어요")
        ref = f"{vendor}-{trade}"
        self.visits[ref] = {"id": str(rows[0]["id"]), "vendor": vendor, "customer": cust_ref}
        self.visits[ref]["trade"] = trade
        return ref

    def _status(self, ref: str) -> str:
        v = self.visits[ref]
        return self.q("select status from visits where id = $1", uuid.UUID(v["id"]))[0]["status"]

    def answer_window(self, ref: str, halves: list[str] | None = None, instant: bool = True):
        v = self.visits[ref]
        if halves:
            days = sorted({date.fromisoformat(h[:10]) for h in halves})
            a, b = days[0], days[-1]
            excluded = [
                (a + timedelta(n)).isoformat()
                for n in range((b - a).days + 1)
                if a + timedelta(n) not in days
            ]
            if any(":" in h for h in halves):
                self.note("업체 기간 답하기는 날 단위라 오전 · 오후 구분은 넣지 못했어요")
        else:
            a, b = self.today + timedelta(days=3), self.today + timedelta(days=10)
            excluded = []
        self.as_(self.vendors[v["vendor"]])
        body = {"start": a.isoformat(), "end": b.isoformat(), "excluded": excluded}
        body["instant"] = instant
        self.need(self.api.post(f"/vendor/visits/{v['id']}/window", json=body), "기간 답하기")

    def pick(self, ref: str, day: str | None = None, half: str = "am") -> None:
        v = self.visits[ref]
        if day is None:
            w = self.q(
                "select start_date, end_date, excluded from visit_windows where visit_id = $1"
                " order by answered_at desc limit 1",
                uuid.UUID(v["id"]),
            )
            if not w:
                raise SeedError("업체 기간 답이 없어 고를 수 없어요")
            skip = set(w[0]["excluded"] or [])
            taken = self.q(  # 같은 집의 다른 실측과 겹치지 않게 하루씩 미뤄요
                "select count(*) as n from visits where project_id = $1 and booked_day is not null",
                uuid.UUID(self.customers[v["customer"]]["pid"]),
            )[0]["n"]
            d = max(w[0]["start_date"], self.today + timedelta(days=1)) + timedelta(days=taken)
            while d in skip and d < w[0]["end_date"]:
                d += timedelta(days=1)
            day = min(d, w[0]["end_date"]).isoformat()
        self.as_(self.customers[v["customer"]])
        cust = self.customers[v["customer"]]
        r = self.api.post(
            f"/projects/{cust['pid']}/visits/{v['id']}/pick", json={"day": day, "half": half}
        )
        self.need(r, "실측 반나절 고르기")

    def accept_pick(self, ref: str) -> None:
        if self._status(ref) == "booked":
            return  # 바로 확정이라 이미 잡혔어요
        v = self.visits[ref]
        self.as_(self.vendors[v["vendor"]])
        self.need(self.api.post(f"/vendor/visits/{v['id']}/accept"), "고른 시간 수락")

    def mark_visited(self, ref: str) -> None:
        v = self.visits[ref]
        rows = self.q(
            "update visits set status = 'visited', visited_at = now()"
            " where id = $1 and status = 'booked' returning id",
            uuid.UUID(v["id"]),
        )
        if not rows:
            raise SeedError("실측이 확정되지 않아 '실측 받음'으로 바꿀 수 없어요")
        self.note("'실측 받음'은 반나절이 지나야 누를 수 있어 SQL로 바꿨어요(시간 건너뜀)")

    def send_quote(self, ref: str, q: dict) -> int:
        v = self.visits[ref]
        self.as_(self.vendors[v["vendor"]])
        fid = self._upload("quote_doc", "실측견적.pdf")
        days = q.get("days") or QUOTE_DEFAULT["days"]
        if days != int(days):
            self.note("견적서 공사 기간은 정수 일이라 반나절은 올렸어요")
        body = {
            "file_ids": [fid],
            "entered_amount": int(q.get("total") or QUOTE_DEFAULT["total"]),
            "vat_mode": q.get("vat") or QUOTE_DEFAULT["vat"],
            "measured_on": (self.today - timedelta(days=1)).isoformat(),
            "days": math.ceil(days),
            "valid_until": q.get("valid_until") or (self.today + timedelta(days=14)).isoformat(),
        }
        memo = q.get("memo")
        if memo:
            body["paper_spec"] = memo[:PAPER_MAX]
            self.note("견적서 메모는 업체가 적는 칸(벽지 사양 paper_spec)에 넣었어요")
            if len(memo) > PAPER_MAX:
                self.note(f"업체 메모가 {PAPER_MAX}자를 넘어 앞부분만 넣었어요")
        self.need(self.api.put(f"/vendor/visits/{v['id']}/quote", json=body), "견적서 저장")
        got = self.need(self.api.post(f"/vendor/visits/{v['id']}/quote/send"), "견적서 보내기")
        ver = int(got.get("version") or 0)
        if q.get("version") and ver and ver != q["version"]:
            self.note(f"견적서 판이 대본({q['version']})과 달라요({ver})")
        return ver

    # ---- 확정 · 공사 날짜 ----

    def confirm(self, ref: str) -> str:
        v = self.visits[ref]
        cust = self.customers[v["customer"]]
        self.as_(cust)
        got = self.need(
            self.api.get(f"/projects/{cust['pid']}/quotes", params={"trade": v["trade"]}),
            "견적서 비교",
        )
        row = next((x for x in got.get("vendors") or [] if x.get("visit_id") == v["id"]), None)
        if row is None or not row.get("seen_ver"):
            raise SeedError("확정할 견적서가 없어요")
        r = self.api.post(
            f"/projects/{cust['pid']}/quotes/{v['id']}/confirm", json={"seen_ver": row["seen_ver"]}
        )
        return self.need(r, "업체 확정")["deal"]["id"]

    def deal_id(self, args: dict, cust_ref: str) -> tuple[str, str]:
        """event 인자 → (확정 id, 업체 ref)."""
        if args.get("deal"):
            d = self.deals[args["deal"]]
            return d["id"], d["vendor"]
        vref = self.visit_ref(args, cust_ref)
        v = self.visits[vref]
        rows = self.q(
            "select id from deals where visit_id = $1 order by created_at desc limit 1",
            uuid.UUID(v["id"]),
        )
        if not rows:
            raise SeedError("확정이 없어요")
        return str(rows[0]["id"]), v["vendor"]

    def propose_dates(
        self, did: str, vendor_ref: str, start: str, end: str, kind: str, reason: str | None
    ) -> None:
        self.as_(self.vendors[vendor_ref])
        body = {"start": start, "end": end, "crew": 2, "method": "app", "kind": kind}
        if reason:
            body["reason"] = reason
        self.need(self.api.post(f"/vendor/jobs/{did}/dates", json=body), "공사 날짜 내기")

    def accept_dates(self, cust: dict, trade: str) -> None:
        self.as_(cust)
        sch = self.need(self.api.get(f"/projects/{cust['pid']}/schedule"), "공정표")
        row = next(
            (
                t
                for t in sch.get("trades") or []
                if (t.get("deal") or {}).get("trade") == trade and t.get("proposal")
            ),
            None,
        )
        if row is None:
            raise SeedError("수락할 공사 날짜가 없어요")
        url = f"/projects/{cust['pid']}/deals/{row['deal']['id']}/dates/{row['proposal']['id']}/accept"
        r = self.api.post(url, json={"seen_version": sch.get("final_version") or 0})
        self.need(r, "공사 날짜 수락")

    def deal(self, spec: dict, cust_ref: str) -> None:
        cust = self.customers[cust_ref]
        vendor = self.vendors[spec["vendor"]]
        if spec.get("trade") == "mokgong":
            self._mokgong_deal(spec, cust, vendor)
            return
        vref = self.visit(
            {
                "ref": f"_{spec['ref']}",
                "vendor": vendor["ref"],
                "trade": "dobae",
                "status": "booked",
            },
            cust_ref,
        )
        q = {"total": spec.get("total") or QUOTE_DEFAULT["total"], "vat": "included"}
        if spec.get("start") and spec.get("end"):
            span = (date.fromisoformat(spec["end"]) - date.fromisoformat(spec["start"])).days
            q["days"] = max(span + 1, 1)
        for _ in range(int(spec.get("quote_version") or 1)):
            self.send_quote(vref, q)
        did = self.confirm(vref)
        self.deals[spec["ref"]] = {"id": did, "vendor": vendor["ref"], "trade": "dobae"}
        if spec.get("status") == "scheduled":
            self.propose_dates(did, vendor["ref"], spec["start"], spec["end"], "initial", None)
            self.accept_dates(cust, "dobae")
        elif spec.get("status") not in (None, "confirmed"):
            raise SeedError(f"확정 상태 {spec['status']}는 아직 못 심어요")

    def _mokgong_deal(self, spec: dict, cust: dict, vendor: dict) -> None:
        pid = uuid.UUID(cust["pid"])
        if not self.q("select id from deals where project_id = $1", pid):
            raise SeedError("목공 확정은 도배 확정을 먼저 심어야 SQL로 넣을 수 있어요")
        vid, did = uuid.uuid4(), uuid.uuid4()
        self.q(
            "insert into visits (id, project_id, trade, vendor_id, vendor_name, slot, status)"
            " values ($1, $2, 'mokgong', $3, $4, 1, 'chosen')",
            vid,
            pid,
            uuid.UUID(vendor["id"]),
            vendor["name"],
        )
        start = date.fromisoformat(spec["start"]) if spec.get("start") else None
        end = date.fromisoformat(spec["end"]) if spec.get("end") else None
        self.q(
            "insert into deals (id, project_id, trade, vendor_id, vendor_name, visit_id, quote_id,"
            " status, dates_due_at, start_date, end_date)"
            " select $1, $2, 'mokgong', $3, $4, $5, quote_id, $6, now(), $7, $8"
            " from deals where project_id = $2 limit 1",
            did,
            pid,
            uuid.UUID(vendor["id"]),
            vendor["name"],
            vid,
            spec.get("status") or "confirmed",
            start,
            end,
        )
        self.visits[f"_{spec['ref']}"] = {
            "id": str(vid),
            "vendor": vendor["ref"],
            "customer": cust["ref"],
            "trade": "mokgong",
        }
        self.deals[spec["ref"]] = {"id": str(did), "vendor": vendor["ref"], "trade": "mokgong"}
        self.note("목공 확정은 SQL로 넣었어요(v3 공사는 목공 요청을 API로 못 만들어요)")

    # ---- world 전체 ----

    def seed(self, world: dict) -> None:
        for v in world.get("vendors") or []:
            self.vendor(v)
        cust = world.get("customer") or {"ref": "c1"}
        self.customer(cust, world.get("home") or {})
        cref = cust.get("ref") or "c1"
        for v in world.get("visits") or []:
            self.visit(v, cref)
        for d in sorted(world.get("deals") or [], key=lambda x: x.get("trade") == "mokgong"):
            self.deal(d, cref)
        for p in world.get("date_proposals") or []:
            d = self.deals[p["deal"]]
            if p.get("status", "pending") != "pending":
                raise SeedError("열린(pending) 날짜 제안만 심을 수 있어요")
            self.propose_dates(
                d["id"],
                d["vendor"],
                p["start"],
                p["end"],
                p.get("kind") or "initial",
                p.get("reason"),
            )
        if world.get("memory"):
            self.note("기억(memory) 앞 상태는 심지 않았어요(근거 고객 메시지가 있어야 해요)")
        if world.get("web"):
            self.note("웹 검색 결과는 심을 수 없어요(Claude 서버 쪽 웹 검색)")

    # ---- events ----

    def event(self, do: str, args: dict, cust_ref: str) -> None:
        fn = getattr(self, f"ev_{do}", None)
        if fn is None:
            raise SeedError(f"모르는 event {do}")
        fn(args or {}, cust_ref)

    def ev_vendor_answer_window(self, a: dict, cref: str) -> None:
        self.answer_window(self.visit_ref(a, cref), a.get("halves"), a.get("instant", True))

    def ev_customer_pick_slot(self, a: dict, cref: str) -> None:
        h = a.get("half") or ""
        day, half = (h.split(":") + ["am"])[:2] if ":" in h else (a.get("day"), h or "am")
        self.pick(self.visit_ref(a, cref), day, half)

    def ev_vendor_accept_pick(self, a: dict, cref: str) -> None:
        self.accept_pick(self.visit_ref(a, cref))

    def ev_vendor_mark_visited(self, a: dict, cref: str) -> None:
        self.mark_visited(self.visit_ref(a, cref))

    def ev_vendor_send_quote(self, a: dict, cref: str) -> None:
        ref = self.visit_ref(a, cref)
        self.ensure_booked(ref)
        self.send_quote(ref, a)

    def ensure_booked(self, ref: str) -> None:
        """v3 견적서는 실측 확정(booked · visited) 뒤에만 내요. 아직이면 화면에서 잡은 것처럼 기간 답 · 고르기 · 수락."""
        st = self._status(ref)
        if st not in ("requested", "offered", "picked"):
            return
        if st == "requested":
            self.answer_window(ref)
        if st in ("requested", "offered"):
            self.pick(ref)
        if self._status(ref) == "picked":
            self.accept_pick(ref)
        self.note("견적서를 내기 전에 실측 반나절을 대본 밖(고객 · 업체 화면)에서 잡았어요")

    def ev_customer_confirm_deal(self, a: dict, cref: str) -> None:
        self.confirm(self.visit_ref(a, cref))

    def ev_vendor_propose_dates(self, a: dict, cref: str) -> None:
        did, vendor = self.deal_id(a, cref)
        kind = a.get("kind") or "initial"
        self.propose_dates(did, vendor, a["start"], a["end"], kind, a.get("reason"))

    def ev_customer_accept_dates(self, a: dict, cref: str) -> None:
        trade = a.get("trade") or self.visits[self.visit_ref(a, cref)]["trade"]
        self.accept_dates(self.customers[cref], trade)

    def ev_customer_delete_memory(self, a: dict, cref: str) -> None:
        """고객이 내 정보 > 비서 기억에서 지워요(GET /assistant/memory → DELETE /assistant/memory/{id})."""
        self.as_(self.customers[cref])
        rows = self.need(self.api.get("/assistant/memory"), "기억 보기")
        hit = [m for m in rows if not a.get("key") or m.get("key") == a["key"]]
        if not hit:
            self.note(f"지울 기억({a.get('key') or '전부'})이 없었어요")
            return
        for m in hit:
            self.need(self.api.delete(f"/assistant/memory/{m['id']}"), "기억 지우기")

    # ---- events: 공사 뒤 일 · 시간 흐름(07-automation 4.6) ----

    def ev_vendor_decline(self, a: dict, cref: str) -> None:
        """업체가 요청을 못 받아요(POST /vendor/visits/{id}/decline, code: full · out_of_area · other)."""
        v = self.visits[self.visit_ref(a, cref)]
        self.as_(self.vendors[v["vendor"]])
        r = self.api.post(
            f"/vendor/visits/{v['id']}/decline", json={"code": a.get("code") or "full"}
        )
        self.need(r, "업체 못 받아요")

    def ev_vendor_add_extra(self, a: dict, cref: str) -> None:
        """업체가 공사 중 추가 금액을 올려요(업체가 적은 금액 · 부가세 방식, 합계는 계산 엔진)."""
        did, vendor = self.deal_id(a, cref)
        self.as_(self.vendors[vendor])
        body = {
            "title": a.get("title") or "추가 공사",
            "reason": a.get("reason") or "현장에서 추가로 할 일이 생겼어요.",
            "entered_amount": int(a.get("amount") or 100_000),
            "vat_mode": a.get("vat") or "included",
        }
        self.need(self.api.post(f"/vendor/jobs/{did}/extras", json=body), "추가 금액 올리기")

    def ev_vendor_finish_work(self, a: dict, cref: str) -> None:
        """업체가 공사를 끝냈다고 올려요. 공사 날이 지나야 올릴 수 있어 공사 날짜를 먼저 앞당겨요(SQL)."""
        did, vendor = self.deal_id(a, cref)
        rows = self.q(
            "update deals set start_date = $1, end_date = $2"
            " where id = $3 and status = 'scheduled' returning id",
            self.today - timedelta(days=3),
            self.today,
            uuid.UUID(did),
        )
        if not rows:
            raise SeedError("공사 날짜를 잡은 확정이 없어 공사 끝을 올릴 수 없어요")
        self.note(
            "공사 끝은 공사 날이 지나야 올릴 수 있어 공사 날짜를 SQL로 앞당겼어요(시간 건너뜀)"
        )
        self.as_(self.vendors[vendor])
        self.need(self.api.post(f"/vendor/jobs/{did}/done", json={}), "공사 끝 올리기")

    def ev_customer_request_dates(self, a: dict, cref: str) -> None:
        """고객이 공사 날짜 바꾸기를 요청해요(희망 시작일 1~3개)."""
        did, _ = self.deal_id(a, cref)
        cust = self.customers[cref]
        self.as_(cust)
        body: dict = {"wish_dates": a["wish_dates"]}
        if a.get("reason"):
            body["reason"] = a["reason"]
        r = self.api.post(f"/projects/{cust['pid']}/deals/{did}/date-requests", json=body)
        self.need(r, "날짜 바꾸기 요청")

    def ev_clock_tick(self, a: dict, cref: str) -> None:
        """시간 흐름: at(시나리오 날짜, 날짜 옮김을 따라요) 또는 days(실제 오늘부터)의 hour시로 비서 시간 트리거
        (hourly)와 정리(sweep: 만료 · 닫기 · 아웃박스 · 평가)를 한 차례 돌려요. 다른 기한 일은 돌리지 않아요."""
        from datetime import datetime, time

        from app.assistant import service as assistant_service
        from app.shared.clock import SEOUL

        if self.call is None:
            raise SeedError("시간 흐름 event는 앱 루프가 있어야 해요")
        if a.get("at"):
            day = date.fromisoformat(a["at"])
        else:
            day = self.today + timedelta(days=int(a.get("days") or 0))
        now = datetime.combine(day, time(int(a.get("hour", 14))), SEOUL)
        self.call(assistant_service.hourly, now)
        self.call(assistant_service.sweep, now)
        self.note("시간 흐름 event는 그 시각으로 비서 시간 트리거 · 정리만 돌렸어요")

    # ---- 끝 상태 ----

    def memory(self) -> list[dict] | None:
        """기억 표가 있으면 (key, value)를 읽어요. 없으면 None(기능 없음)."""
        for t in self.q(
            "select tablename from pg_tables where schemaname = 'public' and tablename like '%memor%'"
        ):
            name = t["tablename"]
            cols = {
                c["column_name"]
                for c in self.q(
                    "select column_name from information_schema.columns where table_name = $1",
                    name,
                )
            }
            if {"key", "value"} <= cols:
                rows = self.q(f'select key, value::text as value from "{name}"')
                return [{"key": r["key"], "value": r["value"]} for r in rows]
        return None

    def collect(self) -> dict:
        pids = [uuid.UUID(c["pid"]) for c in self.customers.values()]
        vmap = {v["id"]: ref for ref, v in self.vendors.items()}
        visits = self.q(
            "select trade, status, vendor_id, decline_code, diy from visits"
            " where project_id = any($1::uuid[])",
            pids,
        )
        deals = self.q(
            "select d.id, d.trade, d.status, d.vendor_id, d.start_date, d.end_date, q.version"
            " from deals d left join vendor_quotes q on q.id = d.quote_id"
            " where d.project_id = any($1::uuid[])",
            pids,
        )
        pending = {
            r["deal_id"]
            for r in self.q(
                "select deal_id from date_proposals where status = 'pending' and kind = 'change'"
            )
        }
        acts = self.q(
            "select id, kind, status, error_code, surface, origin from assistant_actions"
            " order by created_at"
        )
        extras = self.q(
            "select e.ack, e.total, d.vendor_id from extra_charges e join deals d on d.id = e.deal_id"
            " where d.project_id = any($1::uuid[])",
            pids,
        )
        return {
            "visits": [
                {
                    "trade": r["trade"],
                    "status": r["status"],
                    "vendor": vmap.get(str(r["vendor_id"])),
                    "decline_code": r["decline_code"],
                    "diy": list(r["diy"] or []),
                }
                for r in visits
            ],
            "deals": [
                {
                    "trade": r["trade"],
                    "status": r["status"],
                    "vendor": vmap.get(str(r["vendor_id"])),
                    "start": r["start_date"].isoformat() if r["start_date"] else None,
                    "end": r["end_date"].isoformat() if r["end_date"] else None,
                    "quote_version": r["version"],
                    "pending_change": r["id"] in pending,
                }
                for r in deals
            ],
            "actions": [
                {
                    "id": str(r["id"]),
                    "kind": r["kind"],
                    "status": r["status"],
                    "error_code": r["error_code"],
                    "surface": r["surface"],
                    "origin": r["origin"],
                }
                for r in acts
            ],
            "extras": [
                {"status": r["ack"], "total": r["total"], "vendor": vmap.get(str(r["vendor_id"]))}
                for r in extras
            ],
            "nudges": self.nudges(),
            "memory": self.memory(),
        }

    def nudges(self) -> list[dict]:
        """먼저 말 건 줄. sent: 사람에게 보낸 적 있음(보낸 뒤 승인 · 화면 처리로 닫힌 줄도). late: 그 일을 끝내는
        행동(repository.SETTLES)이 같은 사람 · 같은 대상(공사가 대상인 행동은 그 사람 줄 모두)에서 실행된 뒤에 보낸
        줄(거짓 경보)."""
        from app.assistant.repository import SETTLES

        done = self.q(
            "select kind, user_id, target_kind, target_id, executed_at from assistant_actions"
            " where status = 'executed' and executed_at is not null"
        )
        rows = self.q(
            "select trigger, channel, status, reason, surface, user_id, ref_id, sent_at"
            " from assistant_nudges order by created_at"
        )
        out = []
        for r in rows:
            late = r["sent_at"] is not None and any(
                a["user_id"] == r["user_id"]
                and r["trigger"] in SETTLES.get(a["kind"], ())
                and (a["target_kind"] == "project" or a["target_id"] == r["ref_id"])
                and a["executed_at"] < r["sent_at"]
                for a in done
            )
            out.append({k: r[k] for k in ("trigger", "channel", "status", "reason", "surface")}
                       | {"sent": r["sent_at"] is not None, "late": late})  # fmt: skip
        return out
