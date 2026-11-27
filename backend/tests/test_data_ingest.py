"""실제 PostgreSQL에서 스냅샷 변경·재개를 검증한다. 유료 API는 사용하지 않는다."""

import asyncio
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import query
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import data_ingest as ingest
from app.db import SessionLocal, engine
from app.knowledge import ingest as rag
from app.refprice.models import RefDatasetVersion

DATA = Path("/processed")
if not DATA.is_dir():
    DATA = Path(__file__).resolve().parents[2] / "data" / "processed"
MODEL, DIMS, PROFILE = "text-embedding-3-small", 3, ingest.BUILD_PROFILE


def write(path, rows, header=None):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sample(tmp_path, kind):
    source = (
        DATA
        / {
            "unit_price": "02_unit_price.csv",
            "knowledge": "04_lhcs_gypsum_rag.csv",
            "productivity": "03_standard_productivity.csv",
        }[kind]
    )
    with source.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    first, second = dict(row, id="one"), dict(row, id="two")
    if kind == "unit_price":
        first.update(parent_id="", normalized_value="-0.12345678901234567890")
        second.update(parent_id="", normalized_value="")
    elif kind == "knowledge":
        first.update(content="첫 번째 본문", page="1;2")
        second.update(content="두 번째 본문", page="3")
    path = tmp_path / f"{kind}.csv"
    write(path, [first, second])
    return path, [first, second]


class MockEmbedding:
    def __init__(self, fail_at=None, dimensions=3):
        self.calls = []
        self.fail_at = fail_at
        self.dimensions = dimensions

    async def __call__(self, texts):
        self.calls.append(list(texts))
        if len(self.calls) == self.fail_at:
            raise ValueError("합성 API 실패")
        return [
            [1.0, float(sum(text.encode()) % 101 + 1)] + [0.5] * (self.dimensions - 2)
            for text in texts
        ]


async def db_query(sql):
    async with SessionLocal() as session:
        return list((await session.execute(text(sql))).mappings())


async def load(path, model=MODEL, dims=DIMS):
    return await ingest.load_dataset(SessionLocal, ingest.inspect_csv(path), model, dims, PROFILE)


async def embed(version, mock, model=MODEL):
    return await rag.embed_versions(
        SessionLocal, [version], model, DIMS, mock, batch_size=1, count_tokens=lambda _: 10
    )


async def contents(version, kind):
    async with SessionLocal() as session:
        model = ingest.MODELS[kind]
        return {
            row.record_key: row
            for row in (
                await session.scalars(select(model).where(model.dataset_id == version.id))
            ).all()
        }


@pytest.mark.parametrize("kind", ["unit_price", "knowledge"])
@pytest.mark.parametrize("change", ["add", "update", "delete", "metadata"])
def test_independent_snapshot_changes(tmp_path, kind, change):
    path, rows = sample(tmp_path, kind)

    async def run():
        old = await load(path)
        mock = MockEmbedding()
        if kind == "knowledge":
            await embed(old, mock)
        before = await contents(old, kind)
        original = {k: dict(v.provenance) for k, v in before.items()}
        if change == "add":
            rows.append(dict(rows[0], id="three"))
            if kind == "knowledge":
                rows[-1]["content"] = "새로운 본문"
        elif change == "update":
            rows[0]["normalized_value" if kind == "unit_price" else "content"] = (
                "-12.000000000000000001" if kind == "unit_price" else "수정한 본문"
            )
        elif change == "delete":
            rows.pop(0)
        else:
            rows[0].update(source="수정한 출처.pdf", review_reason="별도 검토")
            if kind == "knowledge":
                rows[0].update(category="changed-category", trade="변경 공정", page="8;9")
        write(path, rows)
        new = await load(path)
        assert new.id != old.id and (old.version, new.version) == (1, 2)
        assert new.status is False
        if kind == "knowledge":
            await embed(new, mock)
            assert len(mock.calls) == (3 if change in {"add", "update"} else 2)
        after = await contents(new, kind)
        assert set(after) == {row["id"] for row in rows}
        assert len(after) == {"add": 3, "delete": 1}.get(change, 2)
        for row in rows:
            stored = after[row["id"]]
            assert stored.provenance == row
            if kind == "unit_price":
                expected = Decimal(row["normalized_value"]) if row["normalized_value"] else None
                assert stored.normalized_value == expected
            else:
                assert stored.content == row["content"]
                assert stored.content_hash == rag.content_hash(row["content"])
                assert len(stored.embedding) == DIMS
                if change == "metadata":
                    assert list(stored.embedding) == list(before[row["id"]].embedding)
                    if row["id"] == "one":
                        assert stored.page_numbers == [8, 9]
        preserved = await contents(old, kind)
        assert {k: v.provenance for k, v in preserved.items()} == original
        async with SessionLocal() as session:
            assert await session.scalar(select(func.count()).select_from(RefDatasetVersion)) == 2
            assert (
                len(
                    await ingest.verify(
                        session,
                        [ingest.inspect_csv(path)],
                        MODEL,
                        DIMS,
                        PROFILE,
                        kind == "knowledge",
                    )
                )
                == 1
            )
            if kind == "knowledge":
                old_results = await rag.search_version(
                    session, old.id, False, [1, 1, 1], MODEL, DIMS
                )
                new_results = await rag.search_version(
                    session, new.id, False, [1, 1, 1], MODEL, DIMS
                )
                assert {r.record_key for r in old_results} == {"one", "two"}
                assert {r.record_key for r in new_results} == set(after)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["unit_price", "knowledge"])
@pytest.mark.parametrize("profile", [PROFILE, "next-build-profile"])
def test_unchanged_and_missing_file_preserve_db(tmp_path, kind, profile):
    path, _ = sample(tmp_path, kind)

    async def run():
        first = await load(path)
        mock = MockEmbedding()
        if kind == "knowledge":
            await embed(first, mock)
        second = await load(path)
        assert second.id == first.id and second.version == 1
        if kind == "knowledge":
            await embed(second, mock)
            assert len(mock.calls) == 2
        path.unlink()
        async with SessionLocal() as session:
            report = await ingest.plan(
                session,
                ingest.discover(tmp_path),
                MODEL,
                DIMS,
                profile,
                lambda _: 10,
                Decimal("0.02"),
            )
            assert report["missing_files"] == [path.stem]
            assert report["warnings"] and report["embedding_unique_inputs"] == 0
            preserved = await session.get(RefDatasetVersion, first.id)
            assert preserved.status is False
            assert await session.scalar(select(func.count()).select_from(RefDatasetVersion)) == 1
        assert len(await contents(first, kind)) == 2

    asyncio.run(run())


def test_same_content_different_id_reuses_embedding(tmp_path):
    path, rows = sample(tmp_path, "knowledge")

    async def run():
        mock = MockEmbedding()
        first = await load(path)
        await embed(first, mock)
        rows.append(dict(rows[0], id="three"))
        write(path, rows)
        second = await load(path)
        usage = await embed(second, mock)
        stored = await contents(second, "knowledge")
        assert len(mock.calls) == 2 and usage.generated == 0 and usage.reused == 3
        assert set(stored) == {"one", "two", "three"}
        assert list(stored["one"].embedding) == list(stored["three"].embedding)

    asyncio.run(run())


def test_model_change_is_separate_snapshot(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        mock = MockEmbedding()
        first = await load(path)
        await embed(first, mock)
        other_model = "text-embedding-3-large"
        second = await load(path, model=other_model)
        await embed(second, mock, other_model)
        assert first.id != second.id and second.version == 2 and len(mock.calls) == 4
        async with SessionLocal() as session:
            with pytest.raises(ValueError, match="검색 버전"):
                await rag.search_version(session, first.id, False, [1, 1, 1], other_model, DIMS)

    asyncio.run(run())


def test_api_failure_resumes_only_unfinished_batch(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        version = await load(path)
        mock = MockEmbedding(fail_at=2)
        with pytest.raises(ValueError, match="합성 API 실패"):
            await embed(version, mock)
        chunks = await contents(version, "knowledge")
        assert sum(c.embedding is not None for c in chunks.values()) == 1
        resumed = await load(path)
        assert resumed.id == version.id
        await embed(resumed, mock)
        assert len(mock.calls) == 3
        assert mock.calls[1] == mock.calls[2]
        assert all(c.embedding is not None for c in (await contents(version, "knowledge")).values())

    asyncio.run(run())


def test_parent_deletion_rejected_and_decimal_null_zero_preserved(tmp_path):
    path, rows = sample(tmp_path, "unit_price")
    rows[1]["parent_id"] = "one"
    rows.append(dict(rows[0], id="zero", normalized_value="0"))
    write(path, rows)

    async def run():
        version = await load(path)
        stored = await contents(version, "unit_price")
        assert stored["one"].normalized_value == Decimal("-0.12345678901234567890")
        assert stored["two"].normalized_value is None
        assert stored["zero"].normalized_value == 0
        write(path, rows[1:])
        with pytest.raises(ValueError, match="부모 참조"):
            await load(path)
        assert len(await contents(version, "unit_price")) == 3
        assert (await db_query("select count(*) n from ref_dataset_versions"))[0]["n"] == 1

    asyncio.run(run())


def test_concurrent_load_and_execution_lock(tmp_path):
    path, _ = sample(tmp_path, "unit_price")

    async def run():
        versions = await asyncio.gather(load(path), load(path))
        assert versions[0].id == versions[1].id
        assert (await db_query("select count(*) n from ref_dataset_versions"))[0]["n"] == 1
        async with ingest.execution_lock(engine):
            with pytest.raises(ValueError, match="다른 수동"):
                async with ingest.execution_lock(engine):
                    pytest.fail("중복 실행 잠금이 필요해요")
        async with ingest.execution_lock(engine):
            pass

    asyncio.run(run())


def test_failed_load_is_atomic_and_recoverable(tmp_path, monkeypatch):
    path, _ = sample(tmp_path, "unit_price")
    dataset = ingest.inspect_csv(path)
    original = ingest.records

    def broken(path, kind):
        for index, row in enumerate(original(path, kind)):
            if index == 1:
                raise ValueError("합성 파일 읽기 실패")
            yield row

    async def run():
        monkeypatch.setattr(ingest, "records", broken)
        with pytest.raises(ValueError, match="합성 파일"):
            await ingest.load_dataset(SessionLocal, dataset, MODEL, DIMS, PROFILE)
        assert (await db_query("select count(*) n from ref_dataset_versions"))[0]["n"] == 0
        monkeypatch.setattr(ingest, "records", original)
        version = await load(path)
        assert version.version == 1 and len(await contents(version, "unit_price")) == 2

    asyncio.run(run())


def test_db_rejects_profile_mutation_and_wrong_vector_dimensions(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        version = await load(path)
        async with SessionLocal.begin() as session:
            with pytest.raises(IntegrityError):
                await session.execute(text("UPDATE rag_chunks SET embedding='[1,2]'::vector"))
        await embed(version, MockEmbedding())
        async with SessionLocal.begin() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text("UPDATE ref_dataset_versions SET embedding_model='changed'")
                )

    asyncio.run(run())


@pytest.mark.parametrize("as_json", [False, True])
def test_plan_and_dry_run_never_write_or_call_api(tmp_path, monkeypatch, capsys, as_json):
    sample(tmp_path, "knowledge")
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)

    def forbidden(*args, **kwargs):
        pytest.fail("명시적 embed 실행 없이 API를 호출할 수 없어요")

    monkeypatch.setattr(rag, "OpenAIEmbedder", forbidden)
    for command in ("plan", "load", "embed"):
        args = ingest.parser().parse_args(
            [command, "--directory", str(tmp_path), "--dimensions", "3"]
            + (["--json"] if as_json else [])
        )
        asyncio.run(ingest.run(args))
        output = capsys.readouterr().out
        assert (
            '"executed": false' if as_json else "읽기 전용 · DB 변경 및 OpenAI API 호출 없음"
        ) in output
        if not as_json:
            assert "2행" in output and "신규 임베딩 본문: 2종" in output
        assert query("select count(*) n from ref_dataset_versions")[0]["n"] == 0


def test_token_limit_and_invalid_vector_reject_before_write(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        version = await load(path)
        mock = MockEmbedding()
        with pytest.raises(ValueError, match="토큰"):
            await rag.embed_versions(
                SessionLocal, [version], MODEL, DIMS, mock, count_tokens=lambda _: 8193
            )
        assert not mock.calls
        assert all(c.embedding is None for c in (await contents(version, "knowledge")).values())
        for vector in ([1, 2], [0, 0, 0], [1, float("nan"), 2], [1e39, 0, 1]):
            with pytest.raises(ValueError):
                rag.valid_vector(vector, 3)

    asyncio.run(run())


def test_empty_snapshot_removes_all_current_rows(tmp_path):
    path, rows = sample(tmp_path, "knowledge")

    async def run():
        old = await load(path)
        write(path, [], list(rows[0]))
        new = await load(path)
        assert new.version == 2 and not await contents(new, "knowledge")
        assert len(await contents(old, "knowledge")) == 2

    asyncio.run(run())


def test_original_csv_counts_types_and_full_snapshot():
    expected = [310, 6756, 46358, 51, 25, 1512, 64, 264, 92, 33, 99, 29, 59, 22, 395]
    datasets = ingest.discover(DATA)
    assert [len(d.hashes) for d in datasets] == expected

    async def run():
        versions = []
        for dataset in datasets:
            versions.append(await ingest.load_dataset(SessionLocal, dataset, MODEL, 1536, PROFILE))
        async with SessionLocal() as session:
            verified = await ingest.verify(session, datasets, MODEL, 1536, PROFILE)
            assert sum(v["rows"] for v in verified) == 56069
            assert sum(v["embedding_missing"] for v in verified) == 1133
        assert (
            await db_query("select count(*) n from ref_unit_price_rows where normalized_value<0")
        )[0]["n"] == 2
        assert (
            await db_query("select count(*) n from ref_productivity_rows where normalized_value<0")
        )[0]["n"] == 11
        assert (
            await db_query(
                "select count(*) n from ref_wage_rows where record_type='occupation_wage' and normalized_value is null"
            )
        )[0]["n"] == 71
        assert (await db_query("select count(distinct publication_date) n from ref_wage_rows"))[0][
            "n"
        ] > 1
        assert (await db_query("select count(distinct basis_hours) n from ref_wage_rows"))[0][
            "n"
        ] > 1
        assert (
            await db_query(
                "select count(*) n from ref_productivity_rows where normalized_value is null and numeric_role='unresolved'"
            )
        )[0]["n"] == 30108
        mock = MockEmbedding(dimensions=1536)
        usage = await rag.embed_versions(
            SessionLocal, versions, MODEL, 1536, mock, batch_size=64, count_tokens=lambda _: 10
        )
        assert usage.generated == 1132 and len(mock.calls) == 18
        async with SessionLocal() as session:
            verified = await ingest.verify(session, datasets, MODEL, 1536, PROFILE, True)
            assert sum(v["embedding_missing"] for v in verified) == 0
        assert (
            await db_query("select count(*) n from rag_chunks where vector_dims(embedding)=1536")
        )[0]["n"] == 1133
        again = await rag.embed_versions(
            SessionLocal, versions, MODEL, 1536, mock, batch_size=64, count_tokens=lambda _: 10
        )
        assert again.generated == 0 and len(mock.calls) == 18
        # 실제 원본 전체도 재실행 시 새 버전·중복 행이 생기지 않는다.
        for dataset in datasets:
            await ingest.load_dataset(SessionLocal, dataset, MODEL, 1536, PROFILE)
        assert (await db_query("select count(*) n from ref_dataset_versions"))[0]["n"] == 15

    asyncio.run(run())


def test_sdk_retries_counts_actual_calls_and_stops_at_cap(monkeypatch):
    from types import SimpleNamespace

    import httpx
    from openai import RateLimitError

    calls = []
    fail = True

    async def create(**kwargs):
        calls.append(kwargs)
        if fail:
            raise RateLimitError(
                "합성 제한",
                body=None,
                response=httpx.Response(
                    429, request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
                ),
            )
        return SimpleNamespace(
            model=MODEL,
            usage=SimpleNamespace(total_tokens=7),
            data=[SimpleNamespace(index=0, embedding=[1, 2, 3])],
        )

    async def close():
        pass

    async def no_sleep(seconds):
        pass

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create), close=close)
    monkeypatch.setattr(rag, "AsyncOpenAI", lambda **kwargs: client)
    monkeypatch.setattr(rag.asyncio, "sleep", no_sleep)

    async def run():
        nonlocal fail
        usage = rag.EmbeddingUsage()
        adapter = rag.OpenAIEmbedder("synthetic-key", MODEL, 3, 2, usage)
        with pytest.raises(ValueError, match="호출 상한"):
            await adapter(["합성 본문"])
        assert len(calls) == usage.api_calls == 2 and usage.input_tokens == 0
        fail = False
        adapter = rag.OpenAIEmbedder("synthetic-key", MODEL, 3, 3, usage)
        assert await adapter(["합성 본문"]) == [[1, 2, 3]]
        assert usage.api_calls == 3 and usage.input_tokens == 7
        assert usage.report(Decimal("0.02"))["estimated_usd"] == "1.4E-7"
        assert calls[-1]["dimensions"] == 3 and calls[-1]["model"] == MODEL
        await adapter.close()

    asyncio.run(run())


def test_api_wait_has_no_open_db_transaction(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        version = await load(path)

        async def mock(texts):
            rows = await db_query(
                "select count(*) n from pg_stat_activity where datname=current_database() and state='idle in transaction'"
            )
            assert rows[0]["n"] == 0
            return [[1, 2, 3] for _ in texts]

        await embed(version, mock)

    asyncio.run(run())


def test_changed_file_during_load_rolls_back(tmp_path, monkeypatch):
    path, rows = sample(tmp_path, "unit_price")
    dataset = ingest.inspect_csv(path)
    rows[0]["normalized_value"] = "999"
    write(path, rows)

    async def run():
        with pytest.raises(ValueError, match="적재 중 파일"):
            await ingest.load_dataset(SessionLocal, dataset, MODEL, DIMS, PROFILE)
        assert (await db_query("select count(*) n from ref_dataset_versions"))[0]["n"] == 0

    asyncio.run(run())


def test_unknown_schema_and_duplicate_keys_fail(tmp_path):
    path, rows = sample(tmp_path, "knowledge")
    write(path, [rows[0], rows[0]])
    with pytest.raises(ValueError, match="ID 중복"):
        ingest.inspect_csv(path)
    path.write_text("id,content\na,본문\n", encoding="utf-8")
    with pytest.raises(ValueError, match="필수 열"):
        ingest.inspect_csv(path)


def test_embedding_progress_counts_committed_rows_and_resumes(tmp_path):
    path, _ = sample(tmp_path, "knowledge")

    async def run():
        version = await load(path)
        mock = MockEmbedding(fail_at=2)
        events = []
        with pytest.raises(ValueError, match="합성 API 실패"):
            await rag.embed_versions(
                SessionLocal,
                [version],
                MODEL,
                DIMS,
                mock,
                batch_size=1,
                count_tokens=lambda _: 10,
                progress=lambda done, total: events.append((done, total)),
            )
        assert events == [(0, 2), (1, 2)]
        assert (
            sum(c.embedding is not None for c in (await contents(version, "knowledge")).values())
            == 1
        )
        events.clear()
        await rag.embed_versions(
            SessionLocal,
            [version],
            MODEL,
            DIMS,
            mock,
            batch_size=1,
            count_tokens=lambda _: 10,
            progress=lambda done, total: events.append((done, total)),
        )
        assert events == [(0, 1), (1, 1)]
        assert len(mock.calls) == 3

    asyncio.run(run())


def test_human_report_shows_verified_status_and_percentage(capsys):
    report = {
        "files": [{"file": "rag.csv", "rows": 1000}],
        "executed": True,
        "warnings": ["CSV 누락: missing (DB 버전과 상태 유지)"],
        "verified": [
            {
                "file": "rag.csv",
                "rows": 1000,
                "version": 2,
                "status": False,
                "embedding_missing": 0,
            }
        ],
    }
    ingest.show_progress("검증", 500, 1000)
    ingest.show_report(report, "verify")
    output = capsys.readouterr().out
    assert "50.0%" in output and "500/1,000행" in output
    assert "1,000행 | 2차 | 비활성 | 0행" in output
    assert "임베딩 누락 없음" in output and "CSV 누락: missing" in output
    assert '"verified"' not in output


def test_human_load_and_verify_show_real_completion(tmp_path, monkeypatch, capsys):
    sample(tmp_path, "unit_price")
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    for command in ("load", "verify"):
        arguments = [command, "--directory", str(tmp_path)]
        if command == "load":
            arguments.append("--execute")
        asyncio.run(ingest.run(ingest.parser().parse_args(arguments)))
        output = capsys.readouterr().out
        assert "100.0%" in output and "2/2행" in output
        assert "검증 통과" in output and "비활성" in output
        assert "CSV 1개 | 전체 2행" in output


async def activate(paths):
    async with ingest.execution_lock(engine):
        return await ingest.activate_versions(
            SessionLocal, [ingest.inspect_csv(p) for p in paths], MODEL, DIMS, PROFILE
        )


def test_removed_calculation_option_is_rejected():
    with pytest.raises(SystemExit):
        ingest.parser().parse_args(["verify", "--allow-calculation"])


@pytest.mark.parametrize("kind", ["unit_price", "knowledge"])
def test_activate_and_repeat_preserve_rows(tmp_path, kind):
    path, _ = sample(tmp_path, kind)

    async def run():
        version = await load(path)
        mock = MockEmbedding()
        if kind == "knowledge":
            await embed(version, mock)
        result = await activate([path])
        assert result[0]["status"] is True
        assert (await db_query("select status from ref_dataset_versions"))[0]["status"] is True
        await activate([path])
        assert len(await contents(version, kind)) == 2
        assert len(mock.calls) == (2 if kind == "knowledge" else 0)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["unit_price", "knowledge"])
def test_activation_replaces_previous_and_preserves_rows(tmp_path, kind):
    path, rows = sample(tmp_path, kind)

    async def run():
        old = await load(path)
        mock = MockEmbedding()
        if kind == "knowledge":
            await embed(old, mock)
        await activate([path])
        rows[0]["normalized_value" if kind == "unit_price" else "content"] = (
            "99" if kind == "unit_price" else "활성화할 새 본문"
        )
        write(path, rows)
        new = await load(path)
        if kind == "knowledge":
            await embed(new, mock)
        await activate([path])
        states = await db_query("select version,status from ref_dataset_versions order by version")
        assert [(v["version"], v["status"]) for v in states] == [(1, False), (2, True)]
        preserved = await contents(old, kind)
        assert len(preserved) == 2
        assert preserved["one"].provenance["id"] == "one"
        if kind == "knowledge":
            assert preserved["one"].content == "첫 번째 본문"
        else:
            assert preserved["one"].normalized_value == Decimal("-0.12345678901234567890")

    asyncio.run(run())


def test_failed_embedding_verification_keeps_all_active_versions(tmp_path):
    unit, unit_rows = sample(tmp_path, "unit_price")
    knowledge, rag_rows = sample(tmp_path, "knowledge")

    async def run():
        await load(unit)
        old_rag = await load(knowledge)
        await embed(old_rag, MockEmbedding())
        await activate([unit, knowledge])
        unit_rows[0]["normalized_value"] = "123"
        rag_rows[0]["content"] = "아직 임베딩 없는 새 본문"
        write(unit, unit_rows)
        write(knowledge, rag_rows)
        await load(unit)
        await load(knowledge)
        with pytest.raises(ValueError, match="임베딩 미완료"):
            await activate([unit, knowledge])
        states = await db_query("select version,status from ref_dataset_versions order by version")
        assert [v["status"] for v in states if v["version"] == 1] == [True, True]
        assert [v["status"] for v in states if v["version"] == 2] == [False, False]

    asyncio.run(run())


def test_activation_transaction_failure_rolls_back_retirement(tmp_path):

    path, rows = sample(tmp_path, "unit_price")

    async def run():
        await load(path)
        await activate([path])
        rows[0]["normalized_value"] = "123"
        write(path, rows)
        await load(path)
        # 상태 변경 중 DB 오류를 발생시켜 이전 버전 종료까지 함께 롤백되는지 확인한다.
        async with SessionLocal.begin() as session:
            await session.execute(
                text("""CREATE FUNCTION fail_test_activation() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.status THEN RAISE EXCEPTION 'synthetic failure'; END IF;
                RETURN NEW; END $$""")
            )
            await session.execute(
                text("""CREATE TRIGGER fail_test_activation BEFORE UPDATE ON ref_dataset_versions
                FOR EACH ROW EXECUTE FUNCTION fail_test_activation()""")
            )
        try:
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError):
                await activate([path])
        finally:
            async with SessionLocal.begin() as session:
                await session.execute(
                    text("DROP TRIGGER fail_test_activation ON ref_dataset_versions")
                )
                await session.execute(text("DROP FUNCTION fail_test_activation()"))
        states = await db_query("select version,status from ref_dataset_versions order by version")
        assert [(v["version"], v["status"]) for v in states] == [(1, True), (2, False)]
        await activate([path])

    asyncio.run(run())


def test_activation_cli_requires_explicit_flags_and_preserves_readonly_verify(
    tmp_path, monkeypatch, capsys
):
    path, _ = sample(tmp_path, "unit_price")
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    asyncio.run(load(path))
    for args in (["load", "--activate"], ["verify", "--activate"]):
        with pytest.raises(ValueError, match="--activate"):
            asyncio.run(ingest.run(ingest.parser().parse_args(args)))
    common = ["verify", "--directory", str(tmp_path), "--dimensions", "3", "--require-embeddings"]
    asyncio.run(ingest.run(ingest.parser().parse_args(common)))
    assert query("select status from ref_dataset_versions")[0]["status"] is False
    asyncio.run(ingest.run(ingest.parser().parse_args([*common, "--activate"])))
    assert query("select status from ref_dataset_versions")[0]["status"] is True
    assert "활성화 완료" in capsys.readouterr().out


def test_activation_rejects_stale_snapshot_and_serializes_repeat(tmp_path):
    path, rows = sample(tmp_path, "unit_price")

    async def run():
        await load(path)
        old_data = ingest.inspect_csv(path)
        rows[0]["normalized_value"] = "99"
        write(path, rows)
        await load(path)
        # 과거 파일을 다시 놓아도 최신 버전이 아니면 활성화하지 않는다.
        rows[0]["normalized_value"] = "-0.12345678901234567890"
        write(path, rows)
        assert ingest.inspect_csv(path).sha256 == old_data.sha256
        with pytest.raises(ValueError, match="최신"):
            await activate([path])
        assert all(
            v["status"] is False for v in await db_query("select status from ref_dataset_versions")
        )
        rows[0]["normalized_value"] = "99"
        write(path, rows)
        data = ingest.inspect_csv(path)
        await asyncio.gather(
            ingest.activate_versions(SessionLocal, [data], MODEL, DIMS, PROFILE),
            ingest.activate_versions(SessionLocal, [data], MODEL, DIMS, PROFILE),
        )
        assert (await db_query("select count(*) n from ref_dataset_versions where status = true"))[
            0
        ]["n"] == 1

    asyncio.run(run())


@pytest.mark.parametrize("command", ["plan", "load", "embed", "verify"])
@pytest.mark.parametrize("include_existing", [False, True])
def test_cli_rejects_missing_selected_dataset(
    tmp_path, monkeypatch, capsys, command, include_existing
):
    if include_existing:
        sample(tmp_path, "unit_price")
    arguments = [command, "--directory", str(tmp_path), "--dataset", "missing", "--json"]
    if include_existing:
        arguments += ["--dataset", "unit_price"]
    if command in {"load", "embed"}:
        arguments.append("--execute")
    monkeypatch.setattr(sys, "argv", ["data_ingest", *arguments])
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    assert ingest.main() == 1
    captured = capsys.readouterr()
    assert "missing" in captured.err and not captured.out
    assert query("select count(*) n from ref_dataset_versions")[0]["n"] == 0


def test_cli_verify_rejects_no_csv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["data_ingest", "verify", "--directory", str(tmp_path), "--json"]
    )
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    assert ingest.main() == 1
    assert not capsys.readouterr().out


def test_cli_verify_accepts_empty_snapshot(tmp_path, monkeypatch, capsys):
    path, rows = sample(tmp_path, "unit_price")
    write(path, [], list(rows[0]))
    asyncio.run(load(path))
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    args = ingest.parser().parse_args(
        ["verify", "--directory", str(tmp_path), "--dimensions", "3", "--json"]
    )
    asyncio.run(ingest.run(args))
    report = json.loads(capsys.readouterr().out)
    assert len(report["verified"]) == 1 and report["verified"][0]["rows"] == 0


@pytest.mark.parametrize("fail", [False, True])
def test_cli_embedding_json_has_single_result(tmp_path, monkeypatch, capsys, fail):
    path, _ = sample(tmp_path, "knowledge")
    asyncio.run(load(path))
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)

    class StubEmbedder:
        def __init__(self, key, model, dimensions, max_calls, usage):
            self.usage = usage

        async def __call__(self, texts):
            self.usage.api_calls += 1
            if fail:
                raise ValueError("합성 API 실패")
            self.usage.input_tokens += 20
            return [[1, 2, 3] for _ in texts]

        async def close(self):
            pass

    monkeypatch.setattr(rag, "OpenAIEmbedder", StubEmbedder)
    arguments = ["embed", "--directory", str(tmp_path), "--dimensions", "3", "--execute", "--json"]
    monkeypatch.setattr(sys, "argv", ["data_ingest", *arguments])
    assert ingest.main() == (1 if fail else 0)
    captured = capsys.readouterr()
    if fail:
        assert not captured.out
        assert "API 시도 1회" in captured.err and "합성 API 실패" in captured.err
    else:
        report = json.loads(captured.out)
        assert report["executed"] is True
        assert report["embedding_usage"]["api_calls"] == 1
        assert report["embedding_usage"]["input_tokens"] == 20
        assert report["verified"][0]["embedding_missing"] == 0
        assert not captured.err


@pytest.mark.parametrize("kind", ["unit_price", "knowledge", "productivity"])
def test_removed_csv_metadata_is_optional_and_preserved(tmp_path, kind):
    path, rows = sample(tmp_path, kind)
    original = ingest.inspect_csv(path)
    values = next(ingest.records(path, kind))
    assert "review_reason" not in values
    assert "semantic_status" not in values
    assert values["provenance"] == rows[0]
    removed = {
        "historical",
        "current_rule_usable",
        "automatic_calculation_usable",
        "rag_reference_usable",
        "needs_review",
        "review_reason",
        "semantic_status",
    }
    write(path, [{k: v for k, v in row.items() if k not in removed} for row in rows])
    simplified = ingest.inspect_csv(path)
    assert simplified.kind == original.kind and len(simplified.hashes) == len(original.hashes)


@pytest.mark.parametrize(
    "dataset_key",
    [
        "01_floorplan_quantities",
        "02_unit_price",
        "03_standard_productivity",
        "06_construction_wages",
    ],
)
def test_unused_structured_datasets_stay_inactive(tmp_path, dataset_key):
    with (DATA / f"{dataset_key}.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    path = tmp_path / f"{dataset_key}.csv"
    write(path, [row])
    rag_path, _ = sample(tmp_path, "knowledge")

    async def mark_active(ident):
        async with SessionLocal.begin() as session:
            await session.execute(
                text("UPDATE ref_dataset_versions SET status=true WHERE id=:id"), {"id": ident}
            )

    async def run():
        old = await load(path)
        assert old.status is False
        original = await contents(old, old.kind)
        await mark_active(old.id)
        repeated = await load(path)
        assert repeated.id == old.id and repeated.status is False
        assert await contents(old, old.kind)
        await mark_active(old.id)
        row["source"] = "수정한 출처.pdf"
        write(path, [row])
        new = await load(path)
        assert new.id != old.id and new.status is False
        assert not any(
            v["status"] for v in await db_query("SELECT status FROM ref_dataset_versions")
        )
        await mark_active(new.id)
        knowledge = await load(rag_path)
        await embed(knowledge, MockEmbedding())
        result = await activate([path, rag_path])
        assert [item["status"] for item in result] == [False, True]
        result = await activate([path, rag_path])
        assert [item["status"] for item in result] == [False, True]
        assert (await contents(old, old.kind)).keys() == original.keys()
        states = await db_query("SELECT kind,status FROM ref_dataset_versions")
        assert all(v["status"] is False for v in states if v["kind"] != "knowledge")
        assert all(v["status"] is True for v in states if v["kind"] == "knowledge")
        assert len(await contents(new, new.kind)) == 1
        assert len(await contents(knowledge, "knowledge")) == 2

    asyncio.run(run())


def test_unused_dataset_cli_dry_run_and_activation(tmp_path, monkeypatch, capsys):
    path, _ = sample(tmp_path, "unit_price")
    path = path.rename(tmp_path / "02_unit_price.csv")
    asyncio.run(load(path))
    query("UPDATE ref_dataset_versions SET status=true")
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    common = ["--directory", str(tmp_path), "--dimensions", "3", "--json"]
    asyncio.run(ingest.run(ingest.parser().parse_args(["load", *common])))
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert query("SELECT status FROM ref_dataset_versions")[0]["status"] is True
    asyncio.run(
        ingest.run(
            ingest.parser().parse_args(["verify", *common, "--require-embeddings", "--activate"])
        )
    )
    result = json.loads(capsys.readouterr().out)
    assert result["verified"][0]["status"] is False
    assert query("SELECT status FROM ref_dataset_versions")[0]["status"] is False
    assert query("SELECT count(*) n FROM ref_unit_price_rows")[0]["n"] == 2
