// 업체 자세히 조각 (시안 WVendorDetail · WVendorsPanel). 전체 화면(/vendors/[vid])과 업체 고르기 오른쪽 창이 같이 쓴다.
// 가견적 줄은 API(계산 엔진) 값을 그대로 보이고 화면에서 곱하거나 더하지 않는다.
// 고객이 보는 금액은 모두 부가세 포함이라 금액 옆에 따로 적지 않는다.
import { RangeCard } from "@/components/project/RangeCard";
import type { ProjectVendorDetail } from "@/lib/api/visit";
import { CONTACT_LABEL, bizNoText } from "@/lib/labels";
import { dotDate, won } from "@/lib/format";
import { Check, Chev, Dash, Pen } from "./icons";
import { FAQ_LABEL, asMethod, callHours, feeText, vsText } from "./text";
import s from "./Detail.module.css";

type D = ProjectVendorDetail;

/** 사업자 확인함 · 보증하지 않는다는 한 줄 (확인 범위는 아래 '사업자 · 자격 정보'에 있다) */
export function Verified({ d, big = false }: { d: D; big?: boolean }) {
  return (
    <p className={s.verified}>
      <span className={`mj-st mj-st-ok ${big ? s.big : ""}`}><Check size={big ? 16 : 14} />사업자 확인함{d.verified_on ? <span className="mj-num"> · {dotDate(d.verified_on)}</span> : null}</span>
      <span className="mj-small">공사 결과를 보증하지 않아요.</span>
    </p>
  );
}

/** 실측 비용 · 연락 방법 · 연락 받는 시간 (목록에는 출장 지역 안인 업체만 나와서 지역은 적지 않는다) */
export function ContactFacts({ d }: { d: D }) {
  const pr = d.profile;
  const m = asMethod(pr.contact_method);
  const hours = callHours(pr.call_start, pr.call_end);
  return (
    <dl className={s.kv}>
      <dt>실측 비용</dt><dd className={s.strong}>{feeText(pr.visit_fee)}</dd>
      {m ? <><dt>연락 방법</dt><dd>{CONTACT_LABEL[m]}</dd></> : null}
      {hours ? <><dt>연락 받는 시간</dt><dd className="mj-num">{hours}</dd></> : null}
    </dl>
  );
}

/** 가견적 금액 · 표준견적서 대비 · 실측 뒤 예상 범위 (전체 화면은 폭의 이유까지, 오른쪽 창은 범위만) */
export function Estimate({ d, big = false }: { d: D; big?: boolean }) {
  const e = d.estimate;
  if (!e) return <p className={s.none}>가견적 없음</p>;
  const vs = vsText(e.vs_standard, e.vs_direction);
  return (
    <div className={s.est}>
      <p className={`mj-num ${big ? s.totalBig : s.total}`}>{won(e.total)}</p>
      {vs ? <p className="mj-small mj-num">{vs}</p> : null}
      <RangeCard id={big ? "rg-vd" : "rg-vp"} r={e.range} title="실측 뒤 예상" point={{ label: "가견적", amount: e.total }} compact={!big} />
    </div>
  );
}

/** 시공 사진. max가 있으면 앞에서 그만큼만 */
export function Photos({ d, projectId, max }: { d: D; projectId: string; max?: number }) {
  const all = d.profile.portfolio;
  if (!all.length) return <p className="mj-small">아직 올린 시공 사진이 없어요.</p>;
  const items = max ? all.slice(0, max) : all;
  // 업체 사진은 API가 권한을 확인하고 내준다(이 집에서 고를 수 있는 업체만)
  const src = (fileId: string) => `/api/projects/${projectId}/vendors/${d.profile.vendor_id}/photos/${fileId}`;
  return (
    <ul role="list" className={s.ph}>
      {items.map((ph) => {
        const cap = [ph.space, ph.title].filter(Boolean).join(" · ");
        const sub = [ph.pyeong ? `아파트 ${ph.pyeong}평` : "", ph.taken_on ? dotDate(ph.taken_on).slice(0, 7) : ""].filter(Boolean).join(" · ");
        return (
          <li key={ph.id}>
            <figure>
              <div className={s.pic}><img src={src(ph.file_id)} alt={`${cap} 시공 사진`} loading="lazy" /></div>
              <figcaption>{cap}{sub ? <><br /><span className="mj-small mj-num">{sub}</span></> : null}</figcaption>
            </figure>
          </li>
        );
      })}
    </ul>
  );
}

/** 자주 묻는 5가지 중 업체가 답한 것만(업체 정보 화면 약속: 비워 둔 질문은 안 보여요). fold면 질문만 보이고 누르면 답(오른쪽 창) */
export function Faqs({ d, fold = false }: { d: D; fold?: boolean }) {
  const faqs = new Map(d.profile.faqs.map((f) => [f.key, f.answer]));
  const shown = FAQ_LABEL.filter((f) => faqs.get(f.key));
  if (!shown.length) return <p className="mj-small">아직 적은 답이 없어요.</p>;
  if (fold) {
    return (
      <div className={s.fold}>
        {shown.map((f) => (
          <details key={f.key} className={s.dtl}>
            <summary><Chev className={s.chev} />{f.label}</summary>
            <p className={s.ans}>{faqs.get(f.key)}</p>
          </details>
        ))}
      </div>
    );
  }
  return (
    <dl className={s.qa}>
      {shown.map((f) => <div key={f.key}><dt>{f.label}</dt><dd>{faqs.get(f.key)}</dd></div>)}
    </dl>
  );
}

function Mark({ kind }: { kind: "ok" | "self" | "none" }) {
  if (kind === "ok") return <span className="mj-st mj-st-ok"><Check />믿집 확인</span>;
  if (kind === "self") return <span className="mj-st mj-st-off"><Pen />업체가 적음</span>;
  return <span className="mj-st mj-st-wait"><Dash />확인 안 됨</span>;
}

/** 사업자 · 자격 정보 (접힘) */
export function BizInfo({ d, label }: { d: D; label: React.ReactNode }) {
  const pr = d.profile;
  const name = pr.biz_name ?? "업체";
  const opened = pr.opened_on ? `${pr.opened_on.slice(0, 7).replace("-", ".")}${d.years_open != null ? ` · 업력 ${d.years_open}년` : ""}` : null;
  const biz: { k: string; v: string; mark: "ok" | "self" | "none" }[] = [
    { k: "상호 · 대표자", v: [name, pr.owner_name].filter(Boolean).join(" · "), mark: "ok" },
    ...(pr.biz_no ? [{ k: "사업자등록번호", v: bizNoText(pr.biz_no), mark: "ok" as const }] : []),
    ...(opened ? [{ k: "개업일", v: opened, mark: "ok" as const }] : []),
    ...(pr.address_area ? [{ k: "사업장", v: pr.address_area, mark: "ok" as const }] : []),
    { k: "실내건축공사업 등록", v: pr.interior_license ?? "적지 않았어요", mark: pr.interior_license ? "self" : "none" },
    { k: "보험", v: pr.insurance ?? "적지 않았어요", mark: pr.insurance ? "self" : "none" },
  ];
  return (
    <details className={s.dtl}>
      <summary><Chev className={s.chev} />{label}<span className="mj-small mj-num"> {biz.length}개</span></summary>
      <ul className={`mj-num ${s.bz}`}>
        {biz.map((b) => <li key={b.k}><span className={s.bk}>{b.k}</span><span className={s.bv}>{b.v}</span><Mark kind={b.mark} /></li>)}
      </ul>
      <p className={`mj-small ${s.bzNote}`}>&lsquo;업체가 적음&rsquo;은 믿집이 확인하지 않은 값이에요.</p>
    </details>
  );
}
