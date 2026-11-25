// 한 공사 화면 · 요약(C43): 지금 할 일 · 6단계 + 실측 뒤 작은 단계 · 업체 · 서류 · 기본 정보(잠김).
// 금액 · 단계 · 할 일은 API 값(overview · 비교) 그대로예요. 화면은 줄 세우기 · 이름 붙이기만 해요.
import type { ApiCompare, ApiOverview } from "@/lib/api/schedule";
import type { VisitProject } from "@/lib/api/visit";
import { areaText, won } from "@/lib/v5/format";
import { visitState, type StateTone } from "@/lib/v5/labels";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { AFTER_VISIT_STEPS, PROJECT_STEPS, Steps, SubSteps } from "@/components/ui/Steps";
import { Eyebrow, Group, Row, Rows, Strip, Title } from "@/components/project/Kit";
import s from "@/components/project/home.module.css";
import { v5Href } from "@/lib/v5/paths";

const TONE: Record<StateTone, BadgeTone> = { todo: "now", wait: "wait", ok: "ok", done: "mute", late: "bad" };

/** 이 사이트 안 경로만 단추로 이어요(할 일 link는 API 값) */
const inSite = (v: string) => v.startsWith("/") && !v.startsWith("//") && !v.startsWith("/\\");

/** 단계 목록의 '지금' 칸(0부터). 다 끝났으면 칸 수(모두 ✓), 목록이 없으면 API 번호(공사 띠와 같이 0부터로 읽어요) */
function nowIndex(steps: { state: "done" | "now" | "todo" }[], fallback: number, n: number) {
  const at = steps.findIndex((x) => x.state === "now");
  if (at >= 0) return at;
  if (steps.length && steps.every((x) => x.state === "done")) return n;
  return Math.max(0, Math.min(n - 1, fallback));
}

export function Summary({ p, ov, compare }: { p: VisitProject; ov: ApiOverview; compare: ApiCompare | null }) {
  const base = `/v5/projects/${encodeURIComponent(p.id)}`;
  const trade = ov.trades[0];
  const current = nowIndex(trade?.steps ?? [], trade?.current ?? 0, PROJECT_STEPS.length);
  const afterCurrent = nowIndex(ov.after_steps, 0, AFTER_VISIT_STEPS.length);
  const quoteOf = (visitId: string) => compare?.vendors.find((r) => r.visit_id === visitId)?.latest ?? null;
  const quotedCount = compare?.vendors.filter((r) => r.latest).length ?? 0;
  const todo = ov.todo && ov.todo.text ? ov.todo : null;
  const homeSub = [
    `도배 ${p.scope === "partial" ? "부분" : "전체"}`,
    "아파트",
    [p.emd ?? p.sgg, p.areaM2 ? areaText(p.areaM2, p.areaBasis) : null].filter(Boolean).join(" "),
    p.occupied ? "사는 중" : "빈 집",
    p.locked ? "요청 뒤라 잠겼어요" : null,
  ].filter(Boolean).join(" · ");

  return (
    <>
      {todo ? (
        <Group hi>
          <div className={s.todo}>
            <Eyebrow>지금 할 일</Eyebrow>
            <Title as="h2">{todo.text}</Title>
            {todo.action && inSite(todo.link) ? <div className={s.todoBtn}><Button size="sm" href={v5Href(todo.link)}>{todo.action}</Button></div> : null}
          </div>
        </Group>
      ) : null}

      {/* 웹(≥1024)은 위쪽 공사 띠가 6단계를 그려서 폰 · 태블릿에서만 보여요 */}
      <div className={s.phoneSteps}>
        <Group label="공사 단계">
          <div className={s.steps}>
            <Steps current={Math.min(current, PROJECT_STEPS.length - 1)} />
            {current >= PROJECT_STEPS.length - 1 ? <SubSteps current={afterCurrent} /> : null}
          </div>
        </Group>
      </div>

      {ov.vendors.length ? (
        <Group list>
          <Eyebrow pad as="h2">업체</Eyebrow>
          <Rows>
            {ov.vendors.map((v) => {
              const q = quoteOf(v.visit_id);
              if (v.status === "chosen") {
                const total = compare?.deal?.visit_id === v.visit_id ? compare.deal.quote.total : q?.total ?? null;
                // 실측 확정(booked)과 같은 '확정'으로 보이지 않게 '업체 확정'(lib/labels)
                return <Row key={v.visit_id} label={v.vendor_name} sub={total != null ? `확정 금액 · ${won(total)}` : undefined} value={<Badge tone="ok">{visitState("chosen", "customer").label}</Badge>} />;
              }
              if (v.status === "closed") return <Row key={v.visit_id} label={v.vendor_name} sub={q?.total != null ? `실측 견적서 ${won(q.total)}` : undefined} value={<Badge tone="mute">닫힘</Badge>} />;
              const st = visitState(v.status, "customer");
              return <Row key={v.visit_id} label={v.vendor_name} sub={q?.total != null ? `실측 견적서 ${won(q.total)}` : undefined} value={<Badge tone={TONE[st.tone]}>{st.label}</Badge>} />;
            })}
          </Rows>
        </Group>
      ) : null}

      <Group list>
        <Eyebrow pad as="h2">서류</Eyebrow>
        <Rows>
          <Row label="표준견적서" sub={compare ? "부가세 포함" : undefined} value={compare ? won(compare.standard_total) : undefined} valueSub href={`${base}/standard`} />
          <Row label="예상 공정표" href={`${base}/plan`} />
          {ov.vendors.length ? <Row label="가견적" sub={`${ov.vendors.length}곳 · 요청 때 고정`} href={`${base}/visits`} /> : <Row label="가견적" sub="업체를 담으면 생겨요" out />}
          {quotedCount ? <Row label="실측 견적서" sub={`${quotedCount}곳`} href={`${base}/quotes`} /> : <Row label="실측 견적서" sub="실측을 받으면 생겨요" out />}
          {ov.period.kind === "final" ? <Row label="확정 공정표" href={`${base}/plan`} /> : <Row label="확정 공정표" sub="공사 날짜를 수락하면 생겨요" out />}
        </Rows>
      </Group>

      <Strip label="기본 정보" sub={homeSub} href={`/v5/start?edit=${encodeURIComponent(p.id)}`} />
    </>
  );
}
