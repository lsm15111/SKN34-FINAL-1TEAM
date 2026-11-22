"""믿집 v4 비서 QA 명령 도구. QA 에이전트가 고객 · 업체 역할로 실제와 같은 API를 불러요(사용법은 README.md).

    bash evaluation/v4/qa/qa.sh [--api URL] [--tag 이름] <명령> ...

- 고객 · 업체 화면이 보내는 요청 그대로예요(Origin · 멱등 키 · 카드 고르기 context). 사람 IP는 운영의 Caddy처럼
  X-Forwarded-For로 계정마다 다른 합성 IP를 보내요(가입 · 로그인 한도가 사람마다 따로 세져요).
- 비밀(비밀번호 · 세션)은 비밀 폴더(scratchpad)의 파일에만 두고 출력하지 않아요. 기록(원본 SSE 이벤트)은
  runs/<태그>/<키>/log.jsonl이에요(비밀 없음).
- 프로세스 안 일(시간 당기기 · 비밀번호 없는 업체 세션 · 시간 당긴 공사 끝 · 비용 장부)은 worker와 같은 설정으로
  .claude/run-qa-worker.sh <갈래> once ...를 불러요(inproc.py).
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = HERE / "runs"
SETTINGS = RUNS / "settings.json"
WORKER = ROOT / ".claude" / "run-qa-worker.sh"
COOKIE = "mj_sid"  # APP_ENV=local(https 아님)의 세션 쿠키 이름
UA = "mitjip-qa/1"
SEOUL = timezone(timedelta(hours=9))
TIMEOUT = httpx.Timeout(connect=10, read=300, write=60, pool=10)
# 갈래: API 포트 → (갈래, DB, 화면 Origin 포트). .claude/qa-env.sh와 같은 값이에요
PROFILES = {"qa": ("mitjip_qa", 8050, 3050), "dev": ("mitjip_qa_dev", 8051, 3051)}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")

SRC = {"calc": "믿집 계산", "ai": "AI 답변", "guide": "믿집 안내"}
HALF = {"am": "오전", "pm": "오후"}
WEEK = "월화수목금토일"
STEPS = ["집 정보", "표준견적서", "업체", "실측", "견적서", "공정표", "공사"]
CARD_KO = {
    "home_info": "집 정보", "standard_quote": "표준견적서", "vendor_picks": "업체 추천",
    "visit_slots": "실측 시간", "quote_compare": "견적 비교", "schedule": "공정표",
    "knowledge": "알아 두기", "answer": "답", "floorplan_links": "도면 찾기", "today": "오늘 정할 일",
    "vendor_brief": "요청 브리핑", "quote_checklist": "견적서 체크리스트", "extra": "추가 금액",
    "notice": "이웃 안내문",
}  # fmt: skip
ACTION_KO = {
    "home_info": "집 정보 고치기", "visit_request": "실측 요청", "visit_slot": "실측 시간 고르기",
    "vendor_confirm": "업체 확정", "dates_accept": "공사 날짜 수락", "delay_accept": "바뀐 날짜 수락",
    "date_change": "날짜 바꾸기 요청", "window_answer": "기간 답하기", "decline": "못 받아요",
    "dates": "공사 날짜 보내기", "extra_answer": "추가 금액 답", "work_check": "공사 끝 확인",
    "visit_again": "한 번 더 요청",
}  # fmt: skip
STATUS_KO = {
    "proposed": "승인 기다림", "approved": "처리 중", "executed": "실행함", "rejected": "거절함",
    "expired": "닫힘", "failed": "실패",
}  # fmt: skip
ROW_KO = {"running": "진행 중", "waiting": "기다림", "done": "끝", "failed": "실패",
          "cancelled": "취소", "need": "할 일"}  # fmt: skip
DEMO_KO = {"full": "전체 철거", "partial": "부분 철거", "none": "철거 안 함"}
VAT_KO = {"included": "포함", "excluded": "별도", "exempt": "면세"}
DECLINE_TEXT = {
    "full": "일정이 꽉 차서 이 요청은 못 받아요",
    "out_of_area": "다니는 지역이 아니라 이 요청은 못 받아요",
    "other": "이 요청은 못 받아요",
}
DEMOLITION_SAY = {  # 화면 HomeInfoCard SAY
    "full": "철거는 전체 철거로 할게요", "partial": "철거는 일부만 할게요", "none": "철거는 안 할게요",
}  # fmt: skip
EXTRA_SAY = {  # 화면 ExtraCard 단추 말
    "approve": "추가 금액 승인할래요", "reject": "추가 금액 거절할래요",
    "ask": "추가 금액을 채팅으로 물어볼래요",
}  # fmt: skip


class QaError(Exception):
    """사람이 읽을 오류(비밀 없음)."""


def redact(text: str) -> str:
    """오류 꼬리에 섞일 수 있는 접속 문자열 · 키를 가려요."""
    text = re.sub(r"://[^/\s:@]+:[^@\s]+@", "://***:***@", text or "")
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)


# ---- 글 꼴 ----


def won(n) -> str:
    return "-" if n is None else f"{int(n):,}원"


def day(iso) -> str:
    """'2026-12-01' → '12.1(화)'."""
    if not iso:
        return "-"
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.month}.{d.day}({WEEK[d.weekday()]})"


def span(a, b) -> str:
    return f"{day(a)}~{day(b)}"


def when(ts) -> str:
    """ISO 시각 → 서울 '11.21(금) 14:02'."""
    if not ts:
        return "-"
    t = datetime.fromisoformat(str(ts))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    t = t.astimezone(SEOUL)
    return f"{t.month}.{t.day}({WEEK[t.weekday()]}) {t:%H:%M}"


def euro(word: str) -> str:
    """받침 보고 '로/으로'(화면 lib/format euro와 같음)."""
    c = ord(word[-1]) - 0xAC00 if word else -1
    if not 0 <= c < 11172:
        return f"{word}(으)로"
    return f"{word}{'로' if c % 28 in (0, 8) else '으로'}"


def short(x, n: int = 300) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def id8(x) -> str:
    """짧은 이름: uuid7은 앞자리가 시각이라 같은 분에 만든 id끼리 겹쳐요. 뒤(무작위) 8자리를 보여요."""
    return str(x or "")[-8:]


def match(ids, part: str) -> list[str]:
    """앞 · 뒤 어느 쪽 일부든(4자 이상) 맞는 id."""
    part = part.strip().lower()
    if len(part) < 4:
        raise QaError("id는 4자 이상 적어요.")
    return [str(x) for x in ids if str(x).startswith(part) or str(x).endswith(part)]


# ---- 비밀 · 기록 ----


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


class Lock:
    """여러 QA 에이전트가 같은 파일(계정 목록)을 고칠 때 한 번에 하나만(잠금 파일)."""

    def __init__(self, p: Path, stale: int = 30, wait: float = 10, busy: str = "") -> None:
        self.p = p.with_name(p.name + ".lock")
        self.stale, self.wait = stale, wait
        self.busy = busy or "계정 파일 잠금을 얻지 못했어요. 잠시 뒤 다시 해요."

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        end = time.monotonic() + self.wait
        while time.monotonic() < end:
            try:
                os.close(os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > self.stale:  # 멈춘 잠금
                        self.p.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.05)
        raise QaError(self.busy)

    def __exit__(self, *exc):
        self.p.unlink(missing_ok=True)


class Ctx:
    """명령 한 번의 환경: API · 갈래 · 태그 · 비밀 폴더 · 시계."""

    def __init__(self, a) -> None:
        self.api = a.api.rstrip("/")
        port = httpx.URL(self.api).port
        self.profile = a.profile or next((k for k, v in PROFILES.items() if v[1] == port), None)
        if self.profile not in PROFILES or PROFILES[self.profile][1] != port:
            # 미리보기(8040) 같은 다른 서버에 QA 계정 · 사건을 만들지 않게 QA 포트에만 보내요
            raise QaError("QA API(8050 qa · 8051 dev)에만 보내요. --api 포트를 확인해요.")
        self.db, _, self.web = PROFILES[self.profile]
        if not NAME_RE.match(a.tag):
            raise QaError("태그는 영어 소문자 · 숫자 · 하이픈 24자까지예요.")
        self.tag = a.tag
        sec = (
            a.secrets
            or os.environ.get("QA_SECRETS_DIR")
            or read_json(SETTINGS, {}).get("secrets_dir")
        )
        self.secrets = Path(sec) if sec else None
        self.http = httpx.Client(base_url=self.api, timeout=TIMEOUT)

    # 비밀 폴더
    def sec(self, name: str) -> Path:
        if self.secrets is None or not self.secrets.is_dir():
            raise QaError(
                "비밀 폴더를 몰라요. 먼저 'qa.sh init --secrets <scratchpad 폴더>'를 해요."
            )
        return self.secrets / name

    def accounts(self) -> dict:
        return read_json(self.sec("qa_accounts.json"), {}).get("accounts", {})

    def password(self, email: str) -> str | None:
        got = self.accounts().get(email.lower())
        if got and got.get("db") == self.db:
            return got.get("password")
        for v in read_json(self.sec("e2e_accounts.json"), {}).values():
            if isinstance(v, dict) and str(v.get("email", "")).lower() == email.lower():
                return v.get("password")
        return None

    def session_file(self, email: str) -> Path:
        safe = re.sub(r"[^a-z0-9@._-]", "_", email.lower())
        return self.sec(f"qa_sessions/{self.db}/{safe}.json")

    # 기록
    def folder(self, key: str) -> Path:
        return RUNS / self.tag / key

    def clock_file(self) -> Path:
        return RUNS / f"clock-{self.db}.json"

    def offset(self) -> timedelta:
        return timedelta(seconds=int(read_json(self.clock_file(), {}).get("offset_s", 0)))

    def now(self) -> datetime:
        return datetime.now(SEOUL) + self.offset()

    def origin(self, role: str) -> str:
        return f"http://{'vendor.' if role == 'vendor' else ''}localhost:{self.web}"


class Who:
    """요청하는 사람(고객 키 또는 업체)."""

    def __init__(self, role: str, email: str, label: str, *, pid=None, vid=None, name=None):
        self.role, self.email, self.label = role, email.lower(), label
        self.pid, self.vid, self.name = pid, vid, name or label

    @property
    def ip(self) -> str:
        """계정마다 다른 합성 IP(10.x.y.z, 운영 Caddy가 넘기는 사람 IP 자리)."""
        h = hashlib.sha256(self.email.encode()).digest()
        return f"10.{h[0]}.{h[1]}.{max(h[2], 1)}"


# ---- HTTP ----


class Api:
    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    def _token(self, who: Who) -> str | None:
        return read_json(self.ctx.session_file(who.email), {}).get("token")

    def _save(self, who: Who, token: str) -> None:
        write_json(self.ctx.session_file(who.email), {"email": who.email, "token": token})

    def _drop(self, who: Who) -> None:
        self.ctx.session_file(who.email).unlink(missing_ok=True)

    def headers(self, who: Who | None, extra: dict | None = None, cookie: bool = True) -> dict:
        h = {"User-Agent": UA, "Accept": "application/json"}
        if who is not None:
            h["Origin"] = self.ctx.origin(who.role)
            h["X-Forwarded-For"] = who.ip
            tok = self._token(who) if cookie else None
            if tok:
                h["Cookie"] = f"{COOKIE}={tok}"
        h.update(extra or {})
        return h

    def login(self, who: Who) -> None:
        pw = self.ctx.password(who.email)
        if pw is None:
            if who.role != "vendor":
                raise QaError(f"{who.label} 비밀번호가 비밀 파일에 없어요.")
            self.mint(who)
            return
        r = self.ctx.http.post(
            "/auth/login",
            json={"email": who.email, "password": pw},
            headers=self.headers(who, cookie=False),
        )
        tok = r.cookies.get(COOKIE)
        if r.status_code != 200 or not tok:
            raise QaError(f"{who.label} 로그인 실패: {r.status_code} {err_text(r)}")
        self._save(who, tok)

    def mint(self, who: Who) -> None:
        """비밀번호를 모르는 업체: 로그인과 같은 세션 함수(auth.service.start_session)로 세션을 만들어요."""
        got = inproc(self.ctx, "vendor", who.email, str(self.ctx.session_file(who.email)), "")
        if got.get("error"):
            raise QaError(got["error"].get("message") or "업체 세션을 만들지 못했어요.")

    def req(
        self, who: Who | None, method: str, path: str, *, headers=None, retry=True, auth=True, **kw
    ):
        if auth and who is not None and self._token(who) is None:
            self.login(who)
        r = self.ctx.http.request(
            method, path, headers=self.headers(who, headers, cookie=auth), **kw
        )
        if r.status_code == 401 and auth and who is not None and retry:
            self._drop(who)
            self.login(who)
            return self.req(who, method, path, headers=headers, retry=False, **kw)
        return r

    def get(self, who, path, **kw):
        r = self.req(who, "GET", path, **kw)
        if r.status_code != 200:
            raise QaError(f"GET {path.split('?')[0]}: {r.status_code} {err_text(r)}")
        return r.json()

    def stream(self, who: Who, path: str, body: dict) -> tuple[int, list, str]:
        """SSE 턴 하나를 끝까지 읽어요. 돌려주는 것: (HTTP, [(이벤트, data)], 오류 글).
        503(턴 자리 다 참 · DB 연결 기다림 초과)이면 화면처럼 Retry-After만큼 기다렸다 같은 몸통(같은 client_key)으로
        두 번까지 다시 보내요."""
        if self._token(who) is None:
            self.login(who)
        relogged, busy = False, 0
        while True:
            h = self.headers(who, {"Accept": "text/event-stream"})
            with self.ctx.http.stream("POST", path, json=body, headers=h) as r:
                if r.status_code == 401 and not relogged:
                    relogged = True
                    self._drop(who)
                    self.login(who)
                    continue
                if r.status_code == 503 and busy < 2:
                    busy += 1
                    r.read()
                    wait = r.headers.get("Retry-After", "5")
                    time.sleep(min(int(wait) if wait.isdigit() else 5, 15))
                    continue
                if r.status_code != 200:
                    r.read()
                    return r.status_code, [], err_text(r)
                return 200, parse_sse(r.iter_lines()), ""


def err_text(r) -> str:
    try:
        e = r.json().get("error") or {}
        extra = "; ".join(
            f"{'.'.join(map(str, f.get('loc') or []))}: {f.get('msg')}"
            for f in e.get("fields") or []
        )
        return f"{e.get('code', '')} {e.get('message', '')}{' (' + extra + ')' if extra else ''}".strip()
    except ValueError:
        return short(r.text, 200)


def parse_sse(lines) -> list[tuple[str, dict]]:
    out, ev, data = [], None, []
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if ev is not None and data:
                try:
                    out.append((ev, json.loads("\n".join(data))))
                except ValueError:
                    out.append((ev, {"raw": "\n".join(data)}))
            ev, data = None, []
            continue
        if line.startswith(":"):
            continue
        k, _, v = line.partition(":")
        v = v.removeprefix(" ")
        if k == "event":
            ev = v
        elif k == "data":
            data.append(v)
    if ev is not None and data:
        try:
            out.append((ev, json.loads("\n".join(data))))
        except ValueError:
            pass
    return out


# ---- 프로세스 안 일(worker와 같은 설정) ----


def find_bash() -> str:
    want = os.environ.get("QA_BASH")
    cands = [want] if want else []
    cands += [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]
    w = shutil.which("bash")
    if w and "system32" not in w.lower() and "windowsapps" not in w.lower():
        cands.append(w)
    for c in cands:
        if c and Path(c).exists():
            return c
    raise QaError("Git Bash를 못 찾았어요. 환경변수 QA_BASH에 bash.exe 경로를 넣어요.")


def inproc(ctx: Ctx, *args: str) -> dict:
    cmd = [find_bash(), WORKER.as_posix(), ctx.profile, "once", *args]
    p = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=1800, cwd=str(ROOT))  # fmt: skip
    line = next((x for x in reversed(p.stdout.splitlines()) if x.startswith("QA-JSON: ")), None)
    if line is None:
        tail = "\n".join((p.stderr or p.stdout).strip().splitlines()[-6:])
        raise QaError(f"프로세스 안 일이 실패했어요(종료 {p.returncode}).\n{redact(tail)}")
    return json.loads(line[len("QA-JSON: ") :])


# ---- 사람 찾기 ----


def customer(ctx: Ctx, key: str) -> Who:
    st = read_json(ctx.folder(key) / "state.json", None)
    if not st or st.get("role") != "customer":
        raise QaError(f"태그 {ctx.tag}에 고객 {key}가 없어요. 'new {key} --persona …'부터 해요.")
    return Who("customer", st["email"], key, pid=st["project_id"])


def vendor(ctx: Ctx, ref: str) -> Who:
    """업체 키(e2e_accounts.json의 키, 예: vendor) · 상호 · 이메일 → 업체. 처음 한 번은 DB에서 찾아 적어 둬요."""
    e2e = read_json(ctx.sec("e2e_accounts.json"), {})
    look = e2e[ref]["email"] if isinstance(e2e.get(ref), dict) else ref
    book_p = RUNS / f"vendors-{ctx.db}.json"
    book = read_json(book_p, {})
    got = book.get(look) or book.get(ref)
    if got is None:
        known = [str(v.get("email", "")).lower() for v in e2e.values() if isinstance(v, dict)]
        known += [e for e, v in ctx.accounts().items() if v.get("db") == ctx.db]
        email_guess = look if "@" in look else ""
        sess = ctx.session_file(
            email_guess or f"{hashlib.sha256(look.encode()).hexdigest()[:12]}@pending"
        )
        res = inproc(ctx, "vendor", look, str(sess), ",".join(known))
        if res.get("error"):
            raise QaError(res["error"]["message"])
        if res["how"] == "session":  # 세션 파일 이름을 이메일로 맞춰요
            real = ctx.session_file(res["email"])
            if sess != real:
                real.parent.mkdir(parents=True, exist_ok=True)
                os.replace(sess, real)
        got = {"email": res["email"], "name": res["name"], "id": res["id"], "how": res["how"]}
        with Lock(book_p):  # 여러 에이전트가 같이 적어도 줄을 잃지 않게
            book = read_json(book_p, {})
            book[look] = book[res["name"]] = book[res["email"]] = got
            write_json(book_p, book)
    return Who("vendor", got["email"], got["name"], vid=got["id"], name=got["name"])


# ---- 상태(키마다 하나, 한 키는 한 에이전트만 써요) ----


class State:
    def __init__(self, ctx: Ctx, key: str) -> None:
        self.p = ctx.folder(key) / "state.json"
        self.log_p = ctx.folder(key) / "log.jsonl"
        self.d = read_json(self.p, {})
        self.d.setdefault("cards", {})

    def save(self) -> None:
        write_json(self.p, self.d)

    def log(self, row: dict) -> None:
        self.log_p.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": datetime.now(SEOUL).isoformat(timespec="seconds"), **row}
        with self.log_p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def card(self, c: dict) -> None:
        if c.get("card_id"):
            self.d["cards"][c["card_id"]] = {"kind": c.get("kind"), "data": c.get("data"),
                                             "at": time.time()}  # fmt: skip


def refs_in(data, keys=("ref", "proposal_ref")) -> set[str]:
    got: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in keys and isinstance(v, str):
                got.add(v)
            else:
                got |= refs_in(v, keys)
    elif isinstance(data, list):
        for v in data:
            got |= refs_in(v, keys)
    return got


def find_card(st: State, kinds: tuple[str, ...] | None, ref: str | None) -> tuple[str, dict] | None:
    """가장 나중에 받은 카드 중 그 종류 · 그 이름표가 든 것."""
    rows = sorted(st.d["cards"].items(), key=lambda x: x[1].get("at", 0), reverse=True)
    for cid, c in rows:
        if kinds and c.get("kind") not in kinds:
            continue
        if ref is None or ref in refs_in(c.get("data")):
            return cid, c
    return None


# ---- 그리기 ----


def p(*lines: str) -> None:
    for line in lines:
        print(line)


def action_lines(a: dict, key: str, surface: str) -> list[str]:
    s = a.get("summary") or {}
    head = (f"{id8(a.get('action_id'))} {ACTION_KO.get(a.get('kind'), a.get('kind'))}"
            f" [{STATUS_KO.get(a.get('status'), a.get('status'))}] {s.get('title', '')}")  # fmt: skip
    out = [head]
    bits = []
    if s.get("amount_won") is not None:
        bits.append(f"금액 {won(s['amount_won'])}")
    bits += [f"{x.get('label')} {won(x.get('won'))}" for x in s.get("amounts") or []]
    if s.get("diff"):
        d = s["diff"]
        bits.append(
            f"{d.get('label')} {won(d.get('from_won'))}→{won(d.get('to_won'))}(차액 {won(d.get('diff_won'))})"
        )
    if s.get("version"):
        bits.append(f"판 {s['version']}")
    bits += [f"{x.get('label')}: {x.get('value')}{' (' + x['sub'] + ')' if x.get('sub') else ''}"
             for x in s.get("rows") or []]  # fmt: skip
    if s.get("note"):
        bits.append(f"메모: {s['note']}")
    if s.get("file"):
        bits.append(f"파일: {s['file'].get('label')}")
    if bits:
        out.append("  " + " · ".join(bits))
    tail = [f"승인 단추 '{s.get('approve_label', '')}'"]
    if a.get("status") == "proposed":
        tail.append(f"기한 {when(a.get('expires_at'))}")
    if a.get("error_code"):
        tail.append(f"까닭 {a['error_code']}")
    if (a.get("result") or {}).get("text"):
        tail.append(f"결과: {a['result']['text']}")
    if a.get("replaced_by"):
        tail.append(f"새 카드 {id8(a['replaced_by'])}")
    if a.get("supersedes"):
        tail.append(f"옛 카드 {id8(a['supersedes'])} 대신")
    out.append("  " + " · ".join(tail))
    if a.get("status") == "proposed":
        v = "v" if surface == "vendor" else ""
        out.append(
            f"  → {v}approve {key} {id8(a.get('action_id'))}  |  {v}reject {key} {id8(a.get('action_id'))}"
        )
    return out


def task_line(t: dict) -> str:
    rows = " · ".join(f"{r.get('label')} {ROW_KO.get(r.get('state'), r.get('state'))}"
                      f"{' ' + r['text'] if r.get('text') else ''}" for r in t.get("rows") or [])  # fmt: skip
    return f"작업: {t.get('title')} ({ROW_KO.get(t.get('state'), t.get('state'))}){' — ' + rows if rows else ''}"


def card_lines(c: dict, key: str, surface: str, full: bool = True) -> list[str]:
    """카드 하나: 머리 줄 + 핵심 값 + 단추(press 명령). full=False면 머리 줄 + 한 줄."""
    k, d = c.get("kind"), c.get("data") or {}
    vp = "vpress" if surface == "vendor" else "press"
    out = [f"{CARD_KO.get(k, k)} ({k} · {c.get('card_id')})"]
    if c.get("say"):
        out.append(f"  카드 위 한 줄: {c['say']}")
    body: list[str] = []
    btn: list[str] = []
    if k == "home_info":
        body.append(" · ".join(d.get("facts") or []))
        if d.get("area"):
            a = d["area"]
            body.append(
                f"면적 {'공급' if a.get('basis') == 'supply' else '전용'} {a.get('m2')}㎡ (약 {a.get('pyeong')}평)"
            )
        body.append(f"철거 범위 {d.get('demolition') or '안 정함'} · 저장 {'됨' if d.get('saved') else '안 됨'}"
                    f"{' · 잠김(실측 요청함)' if d.get('locked') else ''}")  # fmt: skip
        body += [
            f"바뀜: {x.get('label')} {x.get('before') or '-'} → {x.get('after')}"
            for x in d.get("changes") or []
        ]
        if d.get("action_id"):
            body.append(f"승인 카드 {id8(d['action_id'])}")
        if not d.get("locked"):
            btn.append(f'{vp} {key} "demolition:full" | "demolition:partial" | "demolition:none"')
    elif k == "standard_quote":
        body.append(f"{d.get('label')} · 합계 {won(d.get('total_won'))}(부가세 포함) · 예상 {d.get('days')}일"
                    f"{' · 부분 공사' if d.get('partial') else ''}")  # fmt: skip
        body += [f"{x.get('name')} {won(x.get('won'))}" for x in (d.get("lines") or [])[:8]]
    elif k == "vendor_picks":
        body.append(
            f"{d.get('area_name')} · {len(d.get('picks') or [])}곳 · 기준: {' · '.join(d.get('basis') or [])}"
        )
        for x in d.get("picks") or []:
            star = (
                f"별점 {x.get('rating')}({x.get('reviews')})"
                if x.get("rating") is not None
                else f"후기 {x.get('reviews')}"
            )
            body.append(f"{x.get('ref')} {x.get('name')} · 가견적 {won(x.get('estimate_won'))} · {star} · 시공 {x.get('done_jobs')}"
                        f"{' · ' + x['badge'] if x.get('badge') else ''}{' · 담음' if x.get('picked') else ''}")  # fmt: skip
            if x.get("reasons"):
                body.append(f"   까닭: {' / '.join(x['reasons'])}")
        refs = [x.get("ref") for x in d.get("picks") or []]
        if refs:
            btn.append(
                f'{vp} {key} "visit_request:{",".join(refs[:2])}"  (업체 1~3곳, 희망 기간을 고르면 끝에 r#)'
            )
    elif k == "visit_slots":
        w = d.get("window")
        body.append(f"{d.get('vendor_name')}{' · 업체가 답한 기간 ' + span(w['start'], w['end']) if w else ''}"
                    f" · {'고르면 바로 확정' if d.get('instant') else '고르면 업체가 수락할 때 확정'}"
                    f"{' · 고른 것 ' + d['chosen'] if d.get('chosen') else ''}")  # fmt: skip
        for x in d.get("wishes") or []:
            body.append(
                f"{x.get('ref')} 희망 기간 {span(x.get('start'), x.get('end'))} · 업체 빈 반나절 {x.get('open_count')}칸"
            )
            btn.append(f'{vp} {key} "visit_request:<업체 v#>,{x.get("ref")}"')
        for x in d.get("candidates") or []:
            body.append(
                f"{x.get('ref')} {day(x.get('day'))} {HALF.get(x.get('half'), '')} · {' / '.join(x.get('why') or [])}"
            )
            btn.append(f'{vp} {key} "visit_slot:{x.get("ref")}"')
        if not d.get("wishes") and not d.get("candidates"):
            body.append("지금 고를 수 있는 시간이 없어요")
        if d.get("vendor_note"):
            body.append(f"업체가 적은 말: {d['vendor_note']}")
    elif k == "quote_compare":
        for x in d.get("cols") or []:
            if x.get("state") != "quoted":
                body.append(
                    f"{x.get('ref')} {x.get('vendor_name')} · 견적서 기다림{' · ' + x['wait_note'] if x.get('wait_note') else ''}"
                )
                continue
            ch = x.get("changed")
            body.append(
                f"{x.get('ref')} {x.get('vendor_name')} · {x.get('version')}판 · {won(x.get('total_won'))} · {x.get('days')}일"
                f" · 유효 {day(x.get('valid_until'))}{' (곧 끝나요)' if x.get('valid_soon') else ''}{' (지남)' if x.get('expired') else ''}"
                f" · 철거 {'포함' if x.get('demolish') else '빠짐' if x.get('demolish') is False else '-'}"
                f" · 폐기물 {'포함' if x.get('waste') else '빠짐' if x.get('waste') is False else '-'}"
                f"{' · 보증 ' + str(x['warranty_months']) + '개월' if x.get('warranty_months') else ''}"
                f"{' · 앞 판보다 ' + won(ch.get('diff_won')) if ch else ''}"
                f"{' · 받은 날 ' + day(x['received_on']) if x.get('received_on') else ''}"
            )
            if x.get("vendor_note"):
                body.append(f"   업체가 적은 말: {x['vendor_note']}")
            if not x.get("expired"):
                btn.append(
                    f'{vp} {key} "vendor_confirm:{x.get("ref")}"  ({euro(x.get("vendor_name") or "")} 확정)'
                )
        if d.get("gap_won") is not None:
            body.append(f"견적 차이 {won(d['gap_won'])}")
        if d.get("ask_chips"):
            body.append(f"물어볼 말: {' / '.join(d['ask_chips'])}")
    elif k == "schedule":
        body.append(f"{'공사 날짜(수락 전)' if d.get('phase') == 'dates' else '확정 공정표'} · {d.get('vendor_name')}"
                    f" · {span(d.get('start'), d.get('end'))} · 일하는 날 {d.get('work_days')}일 · 공정표 {d.get('plan_version')}판")  # fmt: skip
        days_ = [
            f"{day(x.get('day'))}{' 쉼' if x.get('off') else ''}"
            for x in (d.get("days") or [])[:10]
        ]
        if days_:
            body.append("날: " + " · ".join(days_))
        body += [f"겹침: {x}" for x in d.get("conflicts") or []]
        if d.get("vendor_note"):
            body.append(f"업체가 적은 말: {d['vendor_note']}")
        if d.get("action_id"):
            body.append(f"수락 승인 카드 {id8(d['action_id'])}가 열려 있어요")
        if d.get("proposal_ref") and d.get("proposal_kind"):
            btn.append(f'{vp} {key} "{d["proposal_kind"]}:{d["proposal_ref"]}"  (이 날짜로 수락)')
    elif k == "knowledge":
        body.append(f"{d.get('title')} · 출처 {d.get('source')}")
        body += [f"- {x}" for x in (d.get("lines") or [])[:8]]
        body += [
            f"[{'x' if x.get('done') else ' '}] {x.get('label')}" for x in d.get("checklist") or []
        ]
    elif k == "answer":
        body.append(f"({SRC.get(d.get('src'), d.get('src'))}) {d.get('text')}")
        body += [f"링크: {x.get('label')} {x.get('href')}" for x in d.get("links") or []]
    elif k == "floorplan_links":
        body.append(f"{d.get('complex')} · {d.get('note')}")
        body += [
            f"- {x.get('label')} ({x.get('source')}) {x.get('href')}" for x in d.get("links") or []
        ]
    elif k == "today":
        body += today_lines(d, key, surface)
    elif k == "vendor_brief":
        body += brief_lines(d, key)
        btn += [
            f'vpress {key} "window_answer:{x.get("ref")}" --visit <고객 키>'
            for x in d.get("windows") or []
        ]
        btn.append(
            f'vpress {key} "decline:full" --visit <고객 키>  (까닭 full · out_of_area · other)'
        )
    elif k == "quote_checklist":
        body += checklist_lines(d)
    elif k == "extra":
        body.append(
            f"{d.get('ref')} {d.get('vendor_name')} · {d.get('trade')} · {d.get('title')} · {d.get('version')}판 · 답 {d.get('answer')}"
        )
        body.append(f"공급가 {won(d.get('supply_won'))} · 부가세 {won(d.get('vat_won'))} · 합계 {won(d.get('total_won'))}({d.get('vat_label')})"
                    f" · 확정 금액 {won(d.get('deal_total_won'))} · 지금 공사 금액 {won(d.get('grand_total_won'))}"
                    f" · 승인하면 {won(d.get('after_total_won'))} · 사진 {d.get('photo_count')}장")  # fmt: skip
        if d.get("vendor_note"):
            body.append(f"업체가 적은 말: {d['vendor_note']}")
        if d.get("answer") == "pending":
            r = d.get("ref")
            btn.append(
                f'{vp} {key} "extra_answer:{r}" | "extra_answer:{r},reject" | "extra_answer:{r},ask"'
            )
    elif k == "notice":
        body.append(
            f"{d.get('title')} · {span(d.get('start'), d.get('end')) if d.get('start') else ''}"
        )
        body += [f"| {x}" for x in (d.get("text") or "").splitlines()[:6]]
        if d.get("blanks"):
            body.append(f"채울 칸: {' · '.join(d['blanks'])}")
    else:
        body.append(short(d, 400))
    body = [x for x in body if x]
    if not full:
        return [out[0] + (f" — {body[0]}" if body else "")]
    out += [f"  {x}" for x in body]
    out += [f"  단추: {x}" for x in btn]
    return out


def today_lines(d: dict, key: str, surface: str) -> list[str]:
    out = [(f"{day(d.get('date'))}{' · 오늘은 그만(닫음)' if d.get('dismissed') else ''}"
            f"{' · 열린 먼저 말 건 줄 ' + id8(d['nudge_id']) if d.get('nudge_id') else ''}")]  # fmt: skip
    groups = [("할 일", d.get("todo")), ("기다림", d.get("waiting")), ("새 소식", d.get("news")),
              ("알아 두기", d.get("know")), ("", d.get("rows"))]  # fmt: skip
    for name, rows in groups:
        for r in rows or []:
            a = r.get("action") or {}
            act = ""
            if a:
                act = f" [{a.get('label')}"
                if a.get("choice"):
                    act += (
                        f' → vpress {key} "{a["choice"]}"'
                        if surface == "vendor"
                        else f' → press {key} "{a["choice"]}"'
                    )
                elif a.get("say"):
                    act += f' → say {key} "{a["say"]}"'
                act += "]"
            out.append(f"{name + ': ' if name else ''}{r.get('title')}{' · ' + r['sub'] if r.get('sub') else ''}"
                       f"{' (기한)' if r.get('due') else ''}{act}")  # fmt: skip
    return out


def brief_lines(d: dict, key: str) -> list[str]:
    out = [d.get("title") or "", " · ".join(d.get("facts") or [])]
    out += [f"{'맞음' if x.get('state') == 'ok' else '확인 필요' if x.get('state') == 'check' else '안 맞음'} {x.get('label')}: {x.get('text')}"
            for x in d.get("fit") or []]  # fmt: skip
    if d.get("estimate"):
        out.append(f"가견적 {won(d['estimate'].get('total_won'))} · {d['estimate'].get('basis')}")
    out.append(
        f"빈 반나절 {(d.get('halves') or {}).get('open_count')}칸 · 답 기한 {when(d.get('due_at'))}"
    )
    sug = d.get("suggest")
    if sug:
        ex = (
            f" · 빼는 날 {', '.join(day(x) for x in sug.get('excluded') or [])}"
            if sug.get("excluded")
            else ""
        )
        out.append(f"추천 응답: {span(sug.get('start'), sug.get('end'))}{ex} · {'바로 확정' if sug.get('instant') else '수락 뒤 확정'}"
                   f" · 고객이 고를 칸 {sug.get('open_count')} · 승인 카드 {id8(sug.get('action_id'))} → vapprove {key} {id8(sug.get('action_id'))}")  # fmt: skip
    out += [
        f"{x.get('ref')} 기간 후보 {span(x.get('start'), x.get('end'))} · 칸 {x.get('open_count')}"
        for x in d.get("windows") or []
    ]
    if d.get("memo"):
        out.append(f"고객이 남긴 말: {d['memo']}")
    if d.get("sentence"):
        out.append(f"비서 한 줄: {d['sentence']}")
    return out


def checklist_lines(d: dict) -> list[str]:
    mark = {"ok": "됨", "check": "확인", "missing": "빠짐"}
    out = [f"[{mark.get(x.get('state'), x.get('state'))}] {x.get('label')}{' — ' + x['hint'] if x.get('hint') else ''}"
           for x in d.get("items") or []]  # fmt: skip
    out += [f"{x.get('label')}: {x.get('value') or '-'}" for x in d.get("fields") or []]
    if d.get("easy_miss"):
        out.append(f"빠지기 쉬운 것: {' / '.join(d['easy_miss'])}")
    if d.get("prev"):
        out.append(f"앞 판 {d['prev'].get('version')}판 {won(d['prev'].get('total_won'))}")
    return out


def suggest_lines(sug: list[dict], key: str, surface: str) -> list[str]:
    cmd = "vsay" if surface == "vendor" else "say"
    return [f"{i}) {x.get('text')} — 까닭: {x.get('why')}{' · 먼저 말 건 줄 ' + id8(x['nudge_id']) if x.get('nudge_id') else ''}"
            f" → {cmd} {key} --pick {i}" for i, x in enumerate(sug, 1)]  # fmt: skip


def feed_item_lines(it: dict, key: str, surface: str, full: bool) -> list[str]:
    who = "업체" if surface == "vendor" else "고객"
    if it.get("role") == "user":
        return [f"[{when(it.get('at'))}] {who}: {it.get('text')}"]
    head = f"[{when(it.get('at'))}] 비서"
    if it.get("nudge_id"):
        head += f" 먼저 말 건 줄 {id8(it['nudge_id'])}{' (완료)' if it.get('settled') else ''}"
    if it.get("turn_id"):
        head += f" · 턴 {id8(it['turn_id'])}"
    if it.get("mode"):
        head += f" · {'LLM' if it['mode'] == 'llm' else '무료'} 모드"
    if it.get("status"):
        head += f" · {it['status']}"
    out = [head]
    for part in it.get("parts") or []:
        t = part.get("t")
        if t == "text":
            out.append(f"  ({SRC.get(part.get('src'), part.get('src'))}) {part.get('text')}")
        elif t == "card":
            out += ["  카드 " + x if i == 0 else "  " + x
                    for i, x in enumerate(card_lines(part["card"], key, surface, full=full))]  # fmt: skip
        elif t == "action":
            out += ["  승인 카드 " + x if i == 0 else "  " + x
                    for i, x in enumerate(action_lines(part["action"], key, surface))]  # fmt: skip
        elif t == "task":
            out.append("  " + task_line(part["task"]))
        elif t == "suggest":
            s = part["suggest"]
            out.append(
                f"  다음에 물을 말: {s.get('text')} — 까닭: {s.get('why')} (말: {s.get('say')})"
            )
        elif t == "note":
            out.append(f"  메모: {part.get('text')}")
    if it.get("error"):
        out.append(f"  오류: {it['error'].get('code')} {it['error'].get('message')}")
    return out


# ---- 턴 ----


def turn(ctx: Ctx, api: Api, st: State, who: Who, surface: str, text: str, context: dict | None,
         visit_id: str | None, cmd: str) -> None:  # fmt: skip
    body: dict = {"client_key": uuid.uuid4().hex, "text": text}
    if context:
        body["context"] = context
    if surface == "customer":
        body["project_id"] = who.pid
        path = "/assistant/turns"
    else:
        if visit_id:
            body["visit_id"] = visit_id
        path = "/vendor/assistant/turns"
    t0 = time.monotonic()
    code, events, err = api.stream(who, path, body)
    secs = time.monotonic() - t0
    st.log({"cmd": cmd, "text": text, "context": context, "visit_id": visit_id, "http": code,
            "error": err or None, "secs": round(secs, 2), "events": events})  # fmt: skip
    key = st.d.get("key") or who.label
    p(f"━━ {key} · {'업체' if surface == 'vendor' else '고객'} 말: {text}"
      + (f"  [카드 고르기 {context.get('choice')}]" if context and context.get("choice") else "")
      + clock_tag(ctx))  # fmt: skip
    if code != 200:
        p(f"보내지 못했어요: HTTP {code} {err}")
        return
    ack = next((d for n, d in events if n == "ack"), {})
    done = next((d for n, d in events if n == "done"), None)
    error = next((d for n, d in events if n == "error"), None)
    if ack.get("chat_id"):
        st.d["chat_id"] = ack["chat_id"]
    cards = [d for n, d in events if n == "card"]
    for c in cards:
        st.card(c)
    actions: dict[str, dict] = {}
    for n, d in events:
        if n == "action":
            actions[str(d.get("action_id"))] = d
    tasks = [d["task"] for n, d in events if n == "status" and d.get("task")]
    statuses = [d.get("text") for n, d in events if n == "status" and d.get("text")]
    tokens = "".join(d.get("text") or "" for n, d in events if n == "token")
    mode = (done or {}).get("mode")
    p(f"비서 [{'LLM' if mode == 'llm' else '무료' if mode == 'free' else '?'} 모드 · 턴 {id8(ack.get('turn_id'))} · {secs:.1f}초"
      f"{' · 멈춤(상한)' if (done or {}).get('stopped') else ''}]")  # fmt: skip
    if statuses:
        p(f"  진행 줄: {' → '.join(dict.fromkeys(statuses))}")
    parts = text_parts(api, who, surface, ack.get("turn_id"))
    if parts:
        p(*[f"  ({SRC.get(x.get('src'), x.get('src'))}) {x.get('text')}" for x in parts])
    elif tokens:
        p(f"  (출처 모름) {tokens}")
    if error:
        p(f"  오류: {error.get('code')} {error.get('message')}")
    if cards:
        p(f"카드 {len(cards)}개")
        for c in cards:
            p(
                *[
                    "  ▸ " + x if i == 0 else "  " + x
                    for i, x in enumerate(card_lines(c, key, surface))
                ]
            )
    if actions:
        p("승인 카드")
        for a in actions.values():
            p(
                *[
                    "  ▸ " + x if i == 0 else "  " + x
                    for i, x in enumerate(action_lines(a, key, surface))
                ]
            )
    for t in tasks[-1:]:
        p(task_line(t))
    if done:
        sug = done.get("suggest") or []
        st.d["suggest"] = sug
        if sug:
            p("다음에 물을 말", *["  " + x for x in suggest_lines(sug, key, surface)])
        if done.get("chips"):
            p(f"칩: {' / '.join(done['chips'])}")
    st.save()


def text_parts(api: Api, who: Who, surface: str, turn_id) -> list[dict]:
    """방금 턴의 글 묶음과 출처(대화 기록에서 읽어요)."""
    if not turn_id:
        return []
    try:
        if surface == "customer":
            page = api.get(who, "/assistant/feed", params={"project_id": who.pid, "limit": 6})
        else:
            page = api.get(who, "/vendor/assistant/feed", params={"limit": 6})
    except QaError:
        return []
    for it in reversed(page.get("items") or []):
        if str(it.get("turn_id")) == str(turn_id):
            return [x for x in it.get("parts") or [] if x.get("t") == "text"]
    return []


def clock_tag(ctx: Ctx) -> str:
    off = ctx.offset()
    if not off:
        return ""
    return f"  (가상 시각 {when(ctx.now().isoformat())}, +{dur_text(off)})"


def dur_text(td: timedelta) -> str:
    s = int(td.total_seconds())
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (
        " ".join(
            x for x in (f"{d}일" if d else "", f"{h}시간" if h else "", f"{m}분" if m else "") if x
        )
        or "0"
    )


# ---- 카드 단추 → 화면과 같은 고르기 ----


def press_plan(st: State, choice: str) -> tuple[str | None, str]:
    """고르기 값 → (card_id, 보낼 말). 화면 카드가 보내는 말과 같게 만들어요."""
    kind, _, rest = choice.partition(":")
    args = [x.strip() for x in rest.split(",") if x.strip()]
    if kind == "demolition":
        hit = find_card(st, ("home_info",), None)
        return (hit[0] if hit else None), DEMOLITION_SAY.get(rest, f"철거 범위 {rest}")
    if kind == "visit_request":
        vrefs = [a for a in args if a.startswith("v")]
        wish = next((a for a in args if a.startswith("r")), None)
        if vrefs:
            hit = find_card(st, ("vendor_picks",), vrefs[0])
            if hit:
                picks = {x.get("ref"): x.get("name") for x in hit[1]["data"].get("picks") or []}
                return hit[0], f"{' · '.join(picks.get(r, r) for r in vrefs)}에 요청할래요"
        if wish:
            hit = find_card(st, ("visit_slots",), wish)
            if hit:
                w = next(x for x in hit[1]["data"].get("wishes") or [] if x.get("ref") == wish)
                return hit[0], f"{span(w['start'], w['end'])}로 할래요"
        return None, "실측 요청할래요"
    if kind == "visit_slot" and args:
        hit = find_card(st, ("visit_slots",), args[0])
        if hit:
            s = next(x for x in hit[1]["data"].get("candidates") or [] if x.get("ref") == args[0])
            return hit[
                0
            ], f"{day(s['day'])} {HALF.get(s.get('half'), '')}로 할래요"  # 화면 글 그대로
        return None, "이 시간으로 할래요"
    if kind == "vendor_confirm" and args:
        hit = find_card(st, ("quote_compare",), args[0])
        if hit:
            col = next(x for x in hit[1]["data"].get("cols") or [] if x.get("ref") == args[0])
            return hit[0], f"{euro(col.get('vendor_name') or '')} 확정할래요"
        return None, "이 업체로 확정할래요"
    if kind in ("dates_accept", "delay_accept") and args:
        hit = find_card(st, ("schedule",), args[0])
        return (hit[0] if hit else None), "이 날짜로 수락할래요"
    if kind == "extra_answer" and args:
        hit = find_card(st, ("extra",), args[0])
        ans = args[1] if len(args) > 1 else "approve"
        return (hit[0] if hit else None), EXTRA_SAY.get(ans, "추가 금액 답할래요")
    if kind == "window_answer":
        ref = next((a for a in args if a.startswith("w")), None)
        hit = find_card(st, ("vendor_brief",), ref)
        return (hit[0] if hit else None), "이 기간으로 답할래요"
    if kind == "decline":
        return None, DECLINE_TEXT.get(args[-1] if args else "other", DECLINE_TEXT["other"])
    if kind == "dates":
        return "today", "이 날짜로 보낼래요"
    ref = next((a for a in args if a[:1].isalpha() and a[1:].isdigit()), None)
    hit = find_card(st, None, ref) if ref else None
    return (hit[0] if hit else None), f"{ACTION_KO.get(kind, kind)} 할래요"


def refresh_cards(api: Api, st: State, who: Who, surface: str) -> None:
    """대화 기록(먼저 말 건 줄 포함)의 카드를 이름표 찾기에 더해요."""
    try:
        if surface == "customer":
            page = api.get(who, "/assistant/feed", params={"project_id": who.pid, "limit": 30})
        else:
            page = api.get(who, "/vendor/assistant/feed", params={"limit": 30})
    except QaError:
        return
    for it in page.get("items") or []:
        at = datetime.fromisoformat(str(it.get("at"))).timestamp() if it.get("at") else 0
        for part in it.get("parts") or []:
            if part.get("t") == "card":
                c = part["card"]
                old = st.d["cards"].get(c.get("card_id"))
                if old is None or old.get("data") != c.get("data"):
                    st.d["cards"][c["card_id"]] = {"kind": c.get("kind"), "data": c.get("data"),
                                                   "at": max(at, (old or {}).get("at") or 0)}  # fmt: skip


# ---- 명령: 준비 · 고객 ----


def cmd_init(ctx: Ctx, a) -> None:
    sec = Path(a.secrets_dir).resolve()
    if not sec.is_dir():
        raise QaError("그 폴더가 없어요.")
    write_json(SETTINGS, {"secrets_dir": str(sec)})
    has = (sec / "e2e_accounts.json").exists()
    p(
        f"비밀 폴더를 적었어요(runs/settings.json, 저장소에 안 올라가요). 업체 계정 파일 e2e_accounts.json: {'있음' if has else '없음'}"
    )


def home_body(a) -> dict:
    area = a.area
    basis = a.basis
    if area is None:
        area, basis = round(float(a.pyeong) * 3.3058, 1), "supply"
    body = {
        "trade": "dobae",
        "scope": a.scope,
        "spaces": [x for x in (a.spaces or "").split(",") if x] if a.scope == "partial" else [],
        "faces": ["wall", "ceiling"] if a.scope == "full" else [x for x in a.faces.split(",") if x],
        "rooms": a.rooms,
        "housing": "apt",
        "sido": a.sido,
        "sgg": a.sgg,
        "area_m2": f"{float(area):.1f}",
        "area_basis": basis,
        "occupied": a.occupied == "yes",
        "grade": a.grade,
        "budget_won": a.budget * 10_000 if a.budget else None,
        "start_date": a.start,
    }
    if a.demolition:
        body["demolition"] = a.demolition
    return body


def cmd_new(ctx: Ctx, api: Api, a) -> None:
    key = a.key
    if not NAME_RE.match(key):
        raise QaError("키는 영어 소문자 · 숫자 · 하이픈 24자까지예요(예: c1).")
    st = State(ctx, key)
    if st.d.get("project_id") and not a.again:
        raise QaError(
            f"태그 {ctx.tag}에 {key}가 이미 있어요. 다른 키를 쓰거나 --again(DB를 다시 만든 뒤)을 붙여요."
        )
    email = f"qa-{ctx.tag}-{key}@mitjip.test"
    who = Who("customer", email, key)
    body = home_body(a)
    # 1) 손님 표준견적서(로그인 전, 저장 안 함)
    r = api.req(who, "POST", "/guest/standard", json=body, auth=False)
    if r.status_code != 200:
        raise QaError(f"손님 표준견적서: {r.status_code} {err_text(r)}")
    std = r.json()
    # 2) 가입. 무작위 비밀번호는 가입이 된 뒤 비밀 파일에만 적어요(출력하지 않아요)
    abc = string.ascii_letters + string.digits
    pw = "Mj-" + "".join(secrets.choice(abc) for _ in range(14)) + "9a"
    acc_p = ctx.sec("qa_accounts.json")
    r = api.ctx.http.post("/auth/signup", json={"name": a.persona[:50], "email": email, "password": pw},
                          headers=api.headers(who, cookie=False))  # fmt: skip
    if r.status_code == 409:
        raise QaError(f"이 DB에 {email}가 이미 있어요. 다른 키나 태그를 써요.")
    if r.status_code != 201 or not r.cookies.get(COOKIE):
        raise QaError(f"가입: {r.status_code} {err_text(r)}")
    with Lock(acc_p):
        book = read_json(acc_p, {"accounts": {}})
        book.setdefault("accounts", {})[email] = {"password": pw, "tag": ctx.tag, "key": key,
                                                  "persona": a.persona, "db": ctx.db,
                                                  "created": datetime.now(SEOUL).isoformat(timespec="seconds")}  # fmt: skip
        write_json(acc_p, book)
    api._save(who, r.cookies.get(COOKIE))
    # 3) 공사 만들기(가입 뒤 기기 답 옮기기와 같은 요청: POST /projects + Idempotency-Key)
    r = api.req(who, "POST", "/projects", json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
    if r.status_code not in (200, 201):
        raise QaError(f"공사 만들기: {r.status_code} {err_text(r)}")
    proj = r.json()
    st.d.update(role="customer", key=key, email=email, persona=a.persona, project_id=proj["id"],
                home=body, created=datetime.now(SEOUL).isoformat(timespec="seconds"))  # fmt: skip
    st.save()
    st.log({"cmd": "new", "home": body, "guest_total": std.get("total"), "project_id": proj["id"]})
    p(f"{key} 가입 · 공사를 만들었어요{clock_tag(ctx)}",
      f"  이메일 {email} · 페르소나 {a.persona} · 공사 {proj['id']}",
      f"  집: {body['sgg']} · {'공급' if body['area_basis'] == 'supply' else '전용'} {body['area_m2']}㎡ · "
      f"{'사는 중' if body['occupied'] else '빈 집'} · {'실크' if body['grade'] == 'basic' else '합지'}"
      f"{' · 시작 희망 ' + day(body['start_date']) if body['start_date'] else ''}"
      f"{' · 예산 ' + won(body['budget_won']) if body['budget_won'] else ''}"
      f"{' · 철거 ' + DEMO_KO[body['demolition']] if body.get('demolition') else ''}",
      f"  손님 표준견적서 {won(std.get('total'))}(부가세 포함) · 예상 {std.get('days')}일",
      f"  다음: say {key} \"<첫 말>\"")  # fmt: skip


def cmd_say(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    st = State(ctx, a.key)
    text = a.text
    if a.pick:
        text = picked(api, st, who, a.pick, "customer")
    if not text:
        raise QaError("보낼 말이 없어요.")
    turn(ctx, api, st, who, "customer", text, None, None, "say")


def picked(api: Api, st: State, who: Who, n: int, surface: str) -> str:
    """다음에 물을 말 n번: 화면처럼 먼저 말 건 줄이면 열기(open)를 알리고 그 말을 보내요."""
    sug = st.d.get("suggest") or []
    if not 1 <= n <= len(sug):
        raise QaError(f"다음에 물을 말 {n}번이 없어요(지난 턴의 제안 {len(sug)}개).")
    s = sug[n - 1]
    if s.get("nudge_id"):
        pre = "/vendor/assistant" if surface == "vendor" else "/assistant"
        api.req(who, "POST", f"{pre}/nudges/{s['nudge_id']}/open")
    return s.get("say") or s.get("text") or ""


def cmd_press(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    st = State(ctx, a.key)
    refresh_cards(api, st, who, "customer")
    card_id, text = press_plan(st, a.choice)
    card_id = a.card or card_id
    if card_id is None:
        p("(그 이름표가 든 카드를 못 찾아 카드 id 없이 보내요)")
    turn(
        ctx,
        api,
        st,
        who,
        "customer",
        a.text or text,
        {"card_id": card_id, "choice": a.choice},
        None,
        "press",
    )


def find_action(api: Api, who: Who, surface: str, prefix: str) -> dict:
    pre = "/vendor/assistant" if surface == "vendor" else "/assistant"
    params = {} if surface == "vendor" else {"project_id": who.pid}
    rows = api.get(who, f"{pre}/actions", params=params)
    got = match([x.get("action_id") for x in rows], prefix)
    if not got:
        raise QaError(f"{prefix}가 든 승인 카드가 없어요(actions 명령으로 봐요).")
    if len(got) > 1:
        raise QaError(f"{prefix}가 든 승인 카드가 {len(got)}개예요. 더 길게 적어요.")
    return next(x for x in rows if str(x.get("action_id")) == got[0])


def decide(ctx: Ctx, api: Api, who: Who, surface: str, prefix: str, do: str, key: str) -> None:
    a = find_action(api, who, surface, prefix)
    st = State(ctx, key)
    key = who.name if surface == "vendor" else key
    pre = "/vendor/assistant" if surface == "vendor" else "/assistant"
    p(f"━━ {key} · 승인 카드 {'누름' if do == 'approve' else '거절'}{clock_tag(ctx)}",
      *["  " + x for x in action_lines(a, key, surface)[:-1]])  # fmt: skip
    if do == "approve":  # 화면처럼 본 판(seen)과 누름 키를 같이 보내요
        body = {"client_key": uuid.uuid4().hex, "seen": a.get("target_ver")}
        r = api.req(who, "POST", f"{pre}/actions/{a['action_id']}/approve", json=body)
    else:
        r = api.req(who, "POST", f"{pre}/actions/{a['action_id']}/{do}")
    st.log({"cmd": do, "action_id": a["action_id"], "http": r.status_code,
            "out": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text})  # fmt: skip
    if r.status_code != 200:
        p(f"결과: HTTP {r.status_code} {err_text(r)}")
        return
    out = r.json()
    p("결과:", *["  " + x for x in action_lines(out, key, surface)])


def cmd_decide(ctx: Ctx, api: Api, a, do: str) -> None:
    decide(ctx, api, customer(ctx, a.key), "customer", a.prefix, do, a.key)


def cmd_nudge(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    page = api.get(who, "/assistant/feed", params={"project_id": who.pid, "limit": 30})
    ids = {str(it["nudge_id"]) for it in page.get("items") or [] if it.get("nudge_id")}
    hit = match(ids, a.prefix)
    if len(hit) != 1:
        raise QaError(f"{a.prefix}가 든 먼저 말 건 줄이 {len(hit)}개예요.")
    r = api.req(who, "POST", f"/assistant/nudges/{hit[0]}/{a.do}")
    if r.status_code != 200:
        raise QaError(f"{r.status_code} {err_text(r)}")
    d = r.json()
    p(f"먼저 말 건 줄 {id8(hit[0])} {a.do}: 지금 상태 {d.get('status')} · {d.get('body')}")


def cmd_feed(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    feed_print(api, who, "customer", a.key, a.full, a.pages)


def feed_print(api: Api, who: Who, surface: str, key: str, full: bool, pages: int) -> None:
    path = "/vendor/assistant/feed" if surface == "vendor" else "/assistant/feed"
    base = {} if surface == "vendor" else {"project_id": who.pid}
    got: list[dict] = []
    before = None
    for _ in range(max(pages, 1)):
        page = api.get(
            who, path, params={**base, "limit": 30, **({"before": before} if before else {})}
        )
        got = (page.get("items") or []) + got
        before = page.get("before")
        if not before:
            break
    p(f"━━ {key} 대화 기록 {len(got)}줄{' (더 앞 쪽 있음: --pages 늘리기)' if before else ''}")
    for it in got:
        p(*feed_item_lines(it, key, surface, full))
    if page.get("chips"):
        p(f"칩: {' / '.join(page['chips'])}")


def cmd_bell(ctx: Ctx, api: Api, a) -> None:
    who = (
        customer(ctx, a.key) if (ctx.folder(a.key) / "state.json").exists() else vendor(ctx, a.key)
    )
    page = api.get(who, "/notifications")
    items = page.get("items") or []
    if a.read is not None:
        if not 1 <= a.read <= len(items):
            raise QaError("그 번호의 알림이 없어요.")
        n = items[a.read - 1]
        r = api.req(who, "POST", f"/notifications/{n['id']}/read")
        p(f"알림 {a.read}번 읽음: HTTP {r.status_code} · 화면은 {n.get('link')}로 가요")
        return
    p(f"━━ {a.key} 종 알림 {len(items)}개 · 안 읽음 {page.get('unread')}{clock_tag(ctx)}")
    for i, n in enumerate(items[: a.limit], 1):
        p(
            f"{i:>2}) {'  ' if n.get('read') else '새'} [{when(n.get('created_at'))}] {n.get('kind')} · {n.get('body')} → {n.get('link')}"
        )


def cmd_board(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    b = api.get(who, "/assistant/board", params={"project_id": who.pid})
    t = api.get(who, "/assistant/today", params={"project_id": who.pid})
    step = int(b.get("step") or 0)
    bar = " > ".join(f"[{x}]" if i == step else x for i, x in enumerate(STEPS))
    p(f"━━ {a.key} 공사 한눈에: {b.get('project_name')}{clock_tag(ctx)}", f"단계: {bar}",
      f"집: {' · '.join(b.get('facts') or [])}",
      f"할 일 {b.get('todo')} · 기다림 {b.get('waiting')} · 집 정보 {'있음' if b.get('confirmed') else '없음'} · 오늘 정할 일 핀 {b.get('today_pin')}")  # fmt: skip
    m = b.get("money")
    if m:
        rng = f" (업체 금액 {won(m['range'][0])}~{won(m['range'][1])})" if m.get("range") else ""
        p(f"돈: {m.get('label')} {won(m.get('won'))}{rng}")
    v = b.get("vendors")
    if v:
        p(f"{v.get('title')}:", *[f"  {r.get('name')} · {ROW_KO.get(r.get('state'), r.get('state'))} · {r.get('text')}"
                                   f"{' · ' + won(r['won']) if r.get('won') else ''}" for r in v.get("rows") or []])  # fmt: skip
    if b.get("period"):
        pr = b["period"]
        p(f"기간: {pr.get('label')} {pr.get('value')}{' · ' + pr['sub'] if pr.get('sub') else ''}")
    if b.get("docs"):
        p(f"서류: {' · '.join(x.get('label') for x in b['docs'])}")
    if b.get("memory"):
        p(
            "비서가 기억한 것: "
            + " · ".join(f"{x.get('label')} {x.get('value')}" for x in b["memory"])
        )
    p("오늘 정할 일:", *["  " + x for x in today_lines(t, a.key, "customer")])


def cmd_memory(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    rows = api.get(who, "/assistant/memory")
    p(f"━━ {a.key} 비서가 기억한 것 {len(rows)}개")
    for x in rows:
        p(
            f'- {x.get("label")}({x.get("key")}): {x.get("value")} · 근거 "{x.get("evidence_quote")}" · {when(x.get("updated_at"))}'
        )


def cmd_actions(ctx: Ctx, api: Api, a) -> None:
    who = customer(ctx, a.key)
    params = {"project_id": who.pid}
    if not a.all:
        params["status"] = "proposed"
    rows = api.get(who, "/assistant/actions", params=params)
    p(f"━━ {a.key} 승인 카드 {len(rows)}개{' (열린 것만, --all이면 모두)' if not a.all else ''}")
    for x in rows:
        p(*["▸ " + y if i == 0 else y for i, y in enumerate(action_lines(x, a.key, "customer"))])


# ---- 명령: 업체 ----


def visit_of(api: Api, cust: Who, v: Who, prefix: str | None = None) -> dict:
    """고객 화면의 실측 요청 목록에서 그 업체 요청(가장 새것, 닫힌 것은 뒤로)."""
    rows = api.get(cust, f"/projects/{cust.pid}/visits").get("visits") or []
    mine = [x for x in rows if str(x.get("vendor_id")) == str(v.vid)]
    if prefix:
        mine = [x for x in mine if str(x.get("id")).startswith(prefix)]
    if not mine:
        raise QaError(f"{cust.label}의 공사에 {v.name} 실측 요청이 없어요.")
    mine.sort(key=lambda x: (x.get("closed_at") is None, x.get("created_at") or ""), reverse=True)
    return mine[0]


def deal_of(api: Api, cust: Who, v: Who) -> dict:
    rows = api.get(cust, f"/projects/{cust.pid}/deals")
    mine = [x for x in rows if str(x.get("vendor_id")) == str(v.vid)]
    if not mine:
        raise QaError(f"{cust.label}의 공사에 {v.name} 업체 확정이 없어요.")
    return mine[0]


def pdf_bytes(total: int) -> bytes:
    """작은 PDF 한 장(견적서 파일 자리)."""
    text = f"BT /F1 16 Tf 60 780 Td (QA vendor quote - wallpaper - {total:,} KRW) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]  # fmt: skip
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return (
        out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    )


def workdays(start: date, n: int, weekend: bool, off: set[str]) -> list[str]:
    got, d = [], start
    while len(got) < n and (d - start).days < 120:
        if (weekend or d.weekday() < 5) and d.isoformat() not in off:
            got.append(d.isoformat())
        d += timedelta(days=1)
    return got


def cmd_vendor(ctx: Ctx, api: Api, a) -> None:
    v = vendor(ctx, a.vendor)
    st = vendor_state(ctx, v)
    real_today = datetime.now(SEOUL).date()
    act = a.act
    if act in ("today", "feed", "actions"):  # 업체 비서 화면(고객 키 없음)
        if act == "today":
            d = api.get(v, "/vendor/assistant/today")
            p(
                f"━━ {v.name} 오늘 할 일{clock_tag(ctx)}",
                *["  " + x for x in today_lines(d, a.vendor, "vendor")],
            )
        elif act == "feed":
            feed_print(api, v, "vendor", a.vendor, a.full, a.pages)
        else:
            rows = api.get(v, "/vendor/assistant/actions", params={"status": "proposed"})
            p(f"━━ {v.name} 열린 승인 카드 {len(rows)}개")
            for x in rows:
                p(
                    *[
                        "▸ " + y if i == 0 else y
                        for i, y in enumerate(action_lines(x, a.vendor, "vendor"))
                    ]
                )
        return
    if not a.cust:
        raise QaError(f"'{act}'에는 고객 키가 필요해요: vendor {a.vendor} {act} <고객 키>")
    cust = customer(ctx, a.cust)
    head = f"━━ {v.name} → {a.cust} · {act}{clock_tag(ctx)}"
    idem = {"Idempotency-Key": uuid.uuid4().hex}
    if act in ("window", "decline", "accept", "quote", "brief", "checklist", "seen"):
        vis = visit_of(api, cust, v, a.visit)
        vid = vis["id"]
        if act == "brief":
            d = api.get(v, f"/vendor/assistant/briefs/{vid}")
            st.card({"card_id": f"brief-{vid}", "kind": "vendor_brief", "data": d})
            st.save()
            p(head, *["  " + x for x in brief_lines(d, a.vendor)])
            return
        if act == "checklist":
            d = api.get(v, f"/vendor/assistant/checklists/{vid}")
            p(head, *["  " + x for x in checklist_lines(d)])
            return
        if act == "seen":
            r = api.req(v, "POST", f"/vendor/visits/{vid}/seen")
        elif act == "window":
            det = api.get(v, f"/vendor/visits/{vid}")
            lo = real_today + timedelta(days=1)
            ws = date.fromisoformat(det["wish_start"]) if det.get("wish_start") else lo
            we = (
                date.fromisoformat(det["wish_end"])
                if det.get("wish_end")
                else ws + timedelta(days=13)
            )
            start = date.fromisoformat(a.start) if a.start else max(ws, lo)
            end = (
                date.fromisoformat(a.end)
                if a.end
                else max(min(we, start + timedelta(days=13)), start)
            )
            instant = {"yes": True, "no": False}.get(
                a.instant,
                det.get("instant_default") if det.get("instant_default") is not None else True,
            )
            body = {"start": start.isoformat(), "end": end.isoformat(),
                    "excluded": [x for x in (a.exclude or "").split(",") if x], "instant": instant}  # fmt: skip
            r = api.req(v, "POST", f"/vendor/visits/{vid}/window", json=body, headers=idem)
            if r.status_code == 200:
                o = r.json()
                p(head, f"  기간 답했어요: {span(body['start'], body['end'])}"
                        f"{' · 빼는 날 ' + ', '.join(day(x) for x in body['excluded']) if body['excluded'] else ''}"
                        f" · {'바로 확정' if instant else '업체 수락 뒤 확정'} · 고객이 고를 칸 {o.get('open_halves')}"
                        f" · 고를 기한 {when(o.get('pick_due_at'))} · 상태 {o.get('status')}")  # fmt: skip
        elif act == "decline":
            body = {"code": a.code}
            if a.note:
                body["note"] = a.note
            r = api.req(v, "POST", f"/vendor/visits/{vid}/decline", json=body)
            if r.status_code == 200:
                p(head, f"  못 받아요(까닭 {a.code}) 보냈어요 · 상태 {r.json().get('status')}")
        elif act == "accept":
            r = api.req(v, "POST", f"/vendor/visits/{vid}/accept")
            if r.status_code == 200:
                p(head, f"  고객이 고른 반나절을 수락했어요 · {short(r.json(), 200)}")
        else:  # quote: 파일 올리기 → 임시 저장 → 보내기(업체 화면 순서)
            r = api.req(v, "POST", "/files", data={"kind": "quote_doc"},
                        files={"file": ("견적서.pdf", pdf_bytes(a.amount), "application/pdf")})  # fmt: skip
            if r.status_code != 201:
                raise QaError(f"파일 올리기: {r.status_code} {err_text(r)}")
            draft = {"file_ids": [r.json()["id"]], "measured_on": (a.measured or real_today.isoformat()),
                     "entered_amount": a.amount, "vat_mode": a.vat, "days": a.days,
                     "valid_until": a.valid or (real_today + timedelta(days=14)).isoformat(),
                     "incl_removal": a.removal == "yes", "incl_waste": a.waste == "yes",
                     "warranty_months": a.warranty}  # fmt: skip
            if a.spec:
                draft["paper_spec"] = a.spec
            r = api.req(v, "PUT", f"/vendor/visits/{vid}/quote", json=draft)
            if r.status_code != 200:
                raise QaError(f"견적서 임시 저장: {r.status_code} {err_text(r)}")
            r = api.req(v, "POST", f"/vendor/visits/{vid}/quote/send")
            if r.status_code == 200:
                o = r.json()
                sent = (o.get("sent") or [{}])[-1] if isinstance(o.get("sent"), list) else {}
                p(head, f"  견적서를 보냈어요: {won(a.amount)}(부가세 {VAT_KO[a.vat]}) · 공사 {a.days}일 · 유효 {day(draft['valid_until'])}"
                        f"{' · 벽지 사양 ' + a.spec if a.spec else ''} · 판 {sent.get('version', '?')} · 요청 상태 {o.get('visit_status')}")  # fmt: skip
    elif act in ("dates", "extra", "done", "job"):
        deal = deal_of(api, cust, v)
        did = deal["id"]
        job = api.get(v, f"/vendor/jobs/{did}")
        if act == "job":
            p(head, f"  상태 {job.get('status')} · 날짜 상태 {job.get('dates_state')} · 수락한 날 {span(job.get('start_date'), job.get('end_date')) if job.get('start_date') else '-'}"
                    f" · 견적서 공사 {(job.get('quote') or {}).get('days')}일 · 날짜 낼 기한 {when(job.get('dates_due_at'))}"
                    f" · 공사 금액 {won(job.get('grand_total'))} · 끝낼 수 있음 {job.get('can_finish')}"
                    f"{' · 고객 날짜 요청 ' + ', '.join(day(x) for x in (job.get('request') or {}).get('wish_dates') or []) if job.get('request') else ''}")  # fmt: skip
            return
        if act == "dates":
            need = int(
                (job.get("quote") or {}).get("days") or (job.get("need") or {}).get("days") or 1
            )
            if a.days_list:
                days = [x for x in a.days_list.split(",") if x]
            else:
                req = job.get("request") or {}
                first = (
                    (req.get("wish_dates") or [None])[0]
                    or a.start
                    or job.get("plan_start")
                    or (job.get("visit") or {}).get("work_wish_on")
                    or (real_today + timedelta(days=7)).isoformat()
                )
                start = max(date.fromisoformat(a.start or first), real_today + timedelta(days=1))
                off = {h.get("day") for h in job.get("holidays") or []}
                days = workdays(start, need, bool(job.get("weekend_work")), off)
            kind = (
                "change"
                if job.get("dates_state") in ("change_requested", "scheduled")
                else "initial"
            )
            body = {"days": days, "crew": a.crew or (job.get("need") or {}).get("crew") or 2, "method": "app",
                    "kind": kind, "request_id": (job.get("request") or {}).get("id")}  # fmt: skip
            r = api.req(v, "POST", f"/vendor/jobs/{did}/dates", json=body, headers=idem)
            if r.status_code == 200:
                o = r.json()
                p(head, f"  공사 날짜를 보냈어요({'바꾸기' if kind == 'change' else '처음'}): {', '.join(day(x) for x in days)}"
                        f" · {body['crew']}명 · 날짜 상태 {o.get('dates_state')}")  # fmt: skip
        elif act == "extra":
            ck = str(uuid.uuid4())
            body = {"client_key": ck, "title": a.title, "reason": a.reason, "entered_amount": a.amount,
                    "vat_mode": a.vat, "file_ids": []}  # fmt: skip
            r = api.req(
                v, "POST", f"/vendor/jobs/{did}/extras", json=body, headers={"Idempotency-Key": ck}
            )
            if r.status_code in (200, 201):
                ex = (r.json().get("extras") or {}).get("items") or []
                p(head, f"  추가 금액을 올렸어요: {a.title} · 적은 금액 {won(a.amount)}(부가세 {VAT_KO[a.vat]}) · 이유 {a.reason}"
                        f"{' · 추가 금액 ' + str(len(ex)) + '줄' if ex else ''}")  # fmt: skip
        else:  # done
            body = {"note": a.note or None, "photo_file_ids": []}
            r = api.req(v, "POST", f"/vendor/jobs/{did}/done", json=body, headers=idem)
            code = ""
            try:
                code = (r.json().get("error") or {}).get("code", "")
            except ValueError:
                pass
            if r.status_code == 409 and code == "too_early" and ctx.offset():
                # API는 실제 오늘을 써서, 당긴 시각의 오늘로 같은 service 함수를 불러요
                vt = ctx.now().date()
                got = inproc(ctx, "done", v.email, did, vt.isoformat(), a.note or "")
                st.log({"cmd": f"vendor {act}", "cust": a.cust, "via": "inproc", "out": got})
                if got.get("error"):
                    p(
                        head,
                        f"  공사 끝 올리기 실패: {got['error'].get('code')} {got['error'].get('message')}",
                    )
                else:
                    p(head, f"  공사 끝냈다고 올렸어요(가상 오늘 {day(vt)}, 같은 service 함수) · 상태 {got.get('status')}"
                            f" · 끝낸 날 {day(got.get('work_done_on'))} · 자동 끝 {when(got.get('auto_done_at'))}")  # fmt: skip
                return
            if r.status_code == 200:
                o = r.json()
                p(head, f"  공사 끝냈다고 올렸어요 · 상태 {o.get('status')} · 끝낸 날 {day(o.get('work_done_on'))}"
                        f" · 자동 끝 {when(o.get('auto_done_at'))}")  # fmt: skip
    else:
        raise QaError(f"모르는 업체 동작이에요: {act}")
    st.log({"cmd": f"vendor {act}", "cust": a.cust, "http": r.status_code,
            "out": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text})  # fmt: skip
    st.save()
    if r.status_code not in (200, 201, 204):
        p(head, f"  실패: HTTP {r.status_code} {err_text(r)}")
        if act == "done" and "too_early" in err_text(r):
            p("  마지막 공사일이 지나야 해요. tick으로 시간을 당긴 뒤 다시 해요.")
    elif act == "seen":
        p(head, "  요청을 열어 봤어요")


def vendor_state(ctx: Ctx, v: Who) -> State:
    """업체 기록 폴더 runs/<태그>/_v-<상호>(같은 업체를 키 · 상호 · 이메일 어느 것으로 불러도 하나)."""
    st = State(ctx, f"_v-{re.sub(r'[^0-9a-z가-힣]', '', v.name.lower()) or 'vendor'}")
    st.d["key"] = v.name
    return st


def vendor_visit_id(ctx: Ctx, api: Api, v: Who, cust_key: str | None) -> str | None:
    if not cust_key:
        return None
    return visit_of(api, customer(ctx, cust_key), v)["id"]


def cmd_vsay(ctx: Ctx, api: Api, a) -> None:
    v = vendor(ctx, a.vendor)
    st = vendor_state(ctx, v)
    text = a.text
    if a.pick:
        text = picked(api, st, v, a.pick, "vendor")
    if not text:
        raise QaError("보낼 말이 없어요.")
    turn(ctx, api, st, v, "vendor", text, None, vendor_visit_id(ctx, api, v, a.visit), "vsay")


def cmd_vpress(ctx: Ctx, api: Api, a) -> None:
    v = vendor(ctx, a.vendor)
    st = vendor_state(ctx, v)
    refresh_cards(api, st, v, "vendor")
    card_id, text = press_plan(st, a.choice)
    if a.choice.startswith("dates:"):  # 오늘 할 일 [공사 날짜 보내기]가 보내는 말
        rows = api.get(v, "/vendor/assistant/today").get("rows") or []
        row = next((r for r in rows if (r.get("action") or {}).get("choice") == a.choice), None)
        if row:
            text = row["action"].get("say") or row["action"].get("label") or row.get("title")
    visit_id = vendor_visit_id(ctx, api, v, a.visit)
    if visit_id and card_id is None and a.choice.split(":")[0] in ("window_answer", "decline"):
        card_id = f"brief-{visit_id}"
    turn(ctx, api, st, v, "vendor", a.text or text, {"card_id": a.card or card_id, "choice": a.choice},
         visit_id, "vpress")  # fmt: skip


def cmd_vdecide(ctx: Ctx, api: Api, a, do: str) -> None:
    v = vendor(ctx, a.vendor)
    decide(ctx, api, v, "vendor", a.prefix, do, vendor_state(ctx, v).p.parent.name)


# ---- 명령: 시간 · 비용 ----


def parse_dur(text: str) -> timedelta:
    if text.strip() in ("0", "now"):
        return timedelta(0)
    m = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", text.strip())
    if not m or not any(m.groups()):
        raise QaError("시간은 2d · 3h · 1d12h · 30m · 0 꼴로 적어요.")
    d, h, mi = (int(x or 0) for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


def cmd_tick(ctx: Ctx, api: Api, a) -> None:
    step = parse_dur(a.dur)
    if step > timedelta(days=31):
        raise QaError("한 번에 31일까지 당겨요.")
    every_h = max(1, min(int(a.every), 24))
    clock_p = ctx.clock_file()
    with Lock(
        clock_p, stale=1800, busy="다른 QA 에이전트가 시간을 당기는 중이에요. 끝난 뒤 다시 해요."
    ):
        book = read_json(clock_p, {"offset_s": 0, "history": []})
        start = datetime.now(SEOUL) + timedelta(seconds=book.get("offset_s", 0))
        end = start + step
        got = inproc(ctx, "tick", start.isoformat(), end.isoformat(), str(every_h))
        if got.get("error"):
            raise QaError(got["error"].get("message"))
        book["offset_s"] = int(book.get("offset_s", 0) + step.total_seconds())
        book.setdefault("history", []).append({"at": datetime.now(SEOUL).isoformat(timespec="seconds"),
                                               "tag": ctx.tag, "step_s": int(step.total_seconds())})  # fmt: skip
        write_json(clock_p, book)
    p(f"━━ 시간 당기기 +{dur_text(step)} → 가상 시각 {when(end.isoformat())} (누적 +{dur_text(timedelta(seconds=book['offset_s']))}, DB {ctx.db} 전체)",
      f"  돌린 차례 {got.get('steps')}번({every_h}시간마다 5분 + 끝 시각): 기한 일 → assistant_hourly → assistant_sweep",
      f"  기한 일: {fmt_counts(got.get('jobs'))}", f"  시간 트리거: {fmt_counts(got.get('hourly'))}",
      f"  정리 · 먼저 말 걸기: {fmt_counts(got.get('sweep'))}")  # fmt: skip


def fmt_counts(d: dict | None) -> str:
    return " · ".join(f"{k} {v}" for k, v in (d or {}).items()) or "없음"


def cmd_clock(ctx: Ctx, api: Api, a) -> None:
    off = ctx.offset()
    p(f"DB {ctx.db} 가상 시각 {when(ctx.now().isoformat())} (실제보다 +{dur_text(off)})")


def cmd_cost(ctx: Ctx, api: Api, a) -> None:
    got = inproc(ctx, "cost")
    p(
        f"━━ DB {ctx.db} LLM 비용(장부 llm_usage, make_db 뒤): ${got['usd']:.4f} · 호출 {got['calls']}번"
    )
    for x in got.get("by_purpose") or []:
        p(
            f"  목적 {x['purpose']} · {x['model']}: {x['calls']}번 · ${x['usd']:.4f}{' · 실패 ' + str(x['failed']) if x['failed'] else ''}"
        )
    for x in got.get("by_user") or []:
        p(f"  {x['email']}({x['role']}): {x['calls']}번 · ${x['usd']:.4f}")


# ---- 입구 ----


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qa.sh", description="믿집 v4 비서 QA 명령 도구(README.md)")
    ap.add_argument("--api", default=os.environ.get("QA_API", "http://127.0.0.1:8050"))
    ap.add_argument(
        "--tag", default=os.environ.get("QA_TAG", "default"), help="기록 폴더 이름(runs/<태그>)"
    )
    ap.add_argument("--profile", choices=list(PROFILES), help="API 포트로 못 정할 때(qa · dev)")
    ap.add_argument("--secrets", help="비밀 폴더(기본: init으로 적은 곳)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="비밀 폴더(scratchpad) 적기")
    s.add_argument("--secrets", dest="secrets_dir", required=True)

    s = sub.add_parser("new", help="QA 고객 가입 + 공사 만들기(손님 표준견적서 → 가입 → 공사)")
    s.add_argument("key")
    s.add_argument("--persona", required=True)
    s.add_argument("--sido", default="seoul")
    s.add_argument("--sgg", default="노원구")
    s.add_argument("--area", type=float, help="면적 ㎡(안 주면 --pyeong으로)")
    s.add_argument("--pyeong", type=float, default=32)
    s.add_argument("--basis", choices=["supply", "exclusive"], default="supply")
    s.add_argument("--occupied", choices=["yes", "no"], default="no", help="공사할 때 사는 중")
    s.add_argument("--grade", choices=["basic", "economy"], default="basic", help="실크 · 합지")
    s.add_argument("--scope", choices=["full", "partial"], default="full")
    s.add_argument("--spaces", help="부분 공사 공간(쉼표)")
    s.add_argument("--faces", default="wall,ceiling")
    s.add_argument("--rooms", type=int)
    s.add_argument("--budget", type=int, help="예산(만 원)")
    s.add_argument("--start", help="공사 시작 희망일 YYYY-MM-DD")
    s.add_argument("--demolition", choices=["full", "partial", "none"])
    s.add_argument("--again", action="store_true", help="DB를 다시 만든 뒤 같은 키로 다시 가입")

    s = sub.add_parser("say", help="고객 말 한 턴(SSE를 끝까지)")
    s.add_argument("key")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--pick", type=int, help="지난 턴 '다음에 물을 말' n번을 누름")

    s = sub.add_parser("press", help="고객 카드 단추(context.choice)")
    s.add_argument("key")
    s.add_argument("choice")
    s.add_argument("--card", help="카드 id(안 주면 이름표로 찾음)")
    s.add_argument("--text", help="같이 보낼 말(안 주면 화면 단추 말)")

    for name in ("approve", "reject"):
        s = sub.add_parser(name, help=f"고객 승인 카드 {'누르기' if name == 'approve' else '거절'}")
        s.add_argument("key")
        s.add_argument("prefix")

    s = sub.add_parser("nudge", help="먼저 말 건 줄 열기 · 닫기(괜찮아요)")
    s.add_argument("key")
    s.add_argument("do", choices=["open", "dismiss"])
    s.add_argument("prefix")

    s = sub.add_parser("feed", help="고객 대화 기록(먼저 말 건 줄 포함)")
    s.add_argument("key")
    s.add_argument("--full", action="store_true", help="카드를 다 그림")
    s.add_argument("--pages", type=int, default=1)

    s = sub.add_parser("bell", help="종 알림(고객 키 · 업체)")
    s.add_argument("key")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--read", type=int, help="n번 알림 읽음")

    for name, hlp in (
        ("board", "공사 한눈에 · 단계 · 오늘 정할 일"),
        ("memory", "비서가 기억한 것"),
    ):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("key")
    s = sub.add_parser("actions", help="고객 승인 카드 목록")
    s.add_argument("key")
    s.add_argument("--all", action="store_true")

    s = sub.add_parser("vendor", help="업체 사건(v3 업체 화면과 같은 API) · 업체 비서 화면 읽기")
    s.add_argument("vendor", help="업체 키(e2e_accounts.json, 예: vendor) · 상호 · 이메일")
    s.add_argument("act", choices=["window", "decline", "accept", "quote", "dates", "extra", "done", "job",
                                   "brief", "checklist", "seen", "today", "feed", "actions"])  # fmt: skip
    s.add_argument("cust", nargs="?", help="고객 키")
    s.add_argument("--visit", help="실측 요청 id 앞자리(같은 업체 요청이 여럿일 때)")
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--exclude", help="빼는 날(쉼표)")
    s.add_argument("--instant", choices=["yes", "no"])
    s.add_argument("--code", choices=["full", "out_of_area", "other"], default="full")
    s.add_argument("--note")
    s.add_argument("--amount", type=int, default=3_300_000)
    s.add_argument("--vat", choices=["included", "excluded", "exempt"], default="included")
    s.add_argument("--days", type=int, default=3, help="견적서 공사 기간(일)")
    s.add_argument("--valid", help="견적 유효기간 YYYY-MM-DD")
    s.add_argument("--measured", help="실측한 날 YYYY-MM-DD")
    s.add_argument("--spec", help="벽지 사양(업체가 적는 칸, 60자)")
    s.add_argument("--warranty", type=int, default=12)
    s.add_argument("--removal", choices=["yes", "no"], default="yes")
    s.add_argument("--waste", choices=["yes", "no"], default="yes")
    s.add_argument(
        "--days-list", dest="days_list", help="공사 날(쉼표, 안 주면 --start부터 일하는 날)"
    )
    s.add_argument("--crew", type=int)
    s.add_argument("--title", default="추가 공사")
    s.add_argument("--reason", default="현장에서 추가로 할 일이 생겼어요.")
    s.add_argument("--full", action="store_true")
    s.add_argument("--pages", type=int, default=1)

    s = sub.add_parser("vsay", help="업체 비서 한 턴")
    s.add_argument("vendor")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--visit", help="보던 요청: 고객 키")
    s.add_argument("--pick", type=int)

    s = sub.add_parser(
        "vpress", help="업체 카드 단추(window_answer:w1 · decline:full · dates:d1,n1)"
    )
    s.add_argument("vendor")
    s.add_argument("choice")
    s.add_argument("--visit", help="보던 요청: 고객 키")
    s.add_argument("--card")
    s.add_argument("--text")

    for name in ("vapprove", "vreject"):
        s = sub.add_parser(name, help="업체 승인 카드 누르기 · 거절")
        s.add_argument("vendor")
        s.add_argument("prefix")

    s = sub.add_parser("tick", help="시간 당기기(DB 전체): 2d · 3h · 1d12h · 0(시간 그대로 정리만)")
    s.add_argument("dur")
    s.add_argument(
        "--every", type=int, default=1, help="몇 시간마다 한 차례(기본 1 = worker처럼 매시간)"
    )
    sub.add_parser("clock", help="가상 시각 보기")
    sub.add_parser("cost", help="LLM 비용 장부 합")
    return ap


def main(argv: list[str] | None = None) -> int:
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = build().parse_args(argv)
    try:
        if a.cmd == "init":
            a.secrets = a.secrets_dir
        ctx = Ctx(a)
        api = Api(ctx)
        table = {
            "init": lambda: cmd_init(ctx, a), "new": lambda: cmd_new(ctx, api, a),
            "say": lambda: cmd_say(ctx, api, a), "press": lambda: cmd_press(ctx, api, a),
            "approve": lambda: cmd_decide(ctx, api, a, "approve"),
            "reject": lambda: cmd_decide(ctx, api, a, "reject"), "nudge": lambda: cmd_nudge(ctx, api, a),
            "feed": lambda: cmd_feed(ctx, api, a), "bell": lambda: cmd_bell(ctx, api, a),
            "board": lambda: cmd_board(ctx, api, a), "memory": lambda: cmd_memory(ctx, api, a),
            "actions": lambda: cmd_actions(ctx, api, a), "vendor": lambda: cmd_vendor(ctx, api, a),
            "vsay": lambda: cmd_vsay(ctx, api, a), "vpress": lambda: cmd_vpress(ctx, api, a),
            "vapprove": lambda: cmd_vdecide(ctx, api, a, "approve"),
            "vreject": lambda: cmd_vdecide(ctx, api, a, "reject"),
            "tick": lambda: cmd_tick(ctx, api, a), "clock": lambda: cmd_clock(ctx, api, a),
            "cost": lambda: cmd_cost(ctx, api, a),
        }  # fmt: skip
        table[a.cmd]()
        return 0
    except QaError as e:
        print(f"오류: {e}")
        return 1
    except httpx.HTTPError as e:
        print(f"오류: API에 닿지 못했어요({type(e).__name__}). 서버가 떠 있는지 봐요: {a.api}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
