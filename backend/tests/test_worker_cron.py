"""worker 주기 작업 일정 (작업을 돌리지 않고 다음 실행 때만 계산해 본다)."""

from datetime import datetime

from app import worker
from app.config import settings
from app.directory import tasks as directory_tasks
from app.quote import tasks as quote_tasks
from app.shared.clock import SEOUL


def test_schedule_runs_on_seoul_time():
    jobs = {j.coroutine: j for j in worker.cron_schedule()}
    assert set(jobs) == {
        quote_tasks.dispatch_contact_requests,
        quote_tasks.fail_stuck_contacts,
        directory_tasks.sync_kiscon,
        directory_tasks.check_homepages,
    }
    assert worker.WorkerSettings.timezone == SEOUL
    start = datetime(2026, 11, 3, 3, 1, tzinfo=SEOUL)  # 화요일 03:01 (서울)
    nxt = {}
    for fn, job in jobs.items():
        job.calculate_next(start)
        nxt[fn] = job.next_run
    when = {fn: (t.strftime("%a"), t.hour, t.minute) for fn, t in nxt.items()}
    assert when[quote_tasks.dispatch_contact_requests] == ("Tue", 3, 5)  # 5분마다
    assert when[quote_tasks.fail_stuck_contacts] == ("Tue", 3, 2)  # 10분마다
    assert when[directory_tasks.sync_kiscon] == ("Tue", 4, 10)  # 하루 한 번
    assert when[directory_tasks.check_homepages] == ("Mon", 4, 40)  # 주 한 번
    assert nxt[directory_tasks.check_homepages].date().isoformat() == "2026-11-09"
    # 보내기는 겹치지 않게 같은 job_id로, 오래 걸리는 수집은 시간 제한을 늘린다
    assert jobs[quote_tasks.dispatch_contact_requests].job_id == "dispatch_contact_requests"
    assert jobs[directory_tasks.check_homepages].timeout_s == 3600


def test_schedule_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "cron_enabled", False)
    assert worker.cron_schedule() == []
