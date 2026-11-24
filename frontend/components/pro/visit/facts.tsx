// 실측 요청 내용(업체가 보는 것만: 동네 · 면적 · 집 상태 · 희망 기간 · 공사 시작 희망 · 가견적 · 예산 · 사진). 이름 · 연락처 · 동 · 호수는 없어요.
// 폰(V04 · V06)은 한 줄 요약, 웹(D14)은 요약 칸(KeyValue)으로 보여요. 값은 API 값 그대로 모양만 바꿔요.
import type { VendorVisitV3 } from "@/lib/api/vendor";
import { dateShort, rangeText, timeSeoul, won } from "@/lib/format";
import { gradeLabel } from "@/lib/labels";
import { PhotoGrid } from "@/components/ui/PhotoGrid";
import { KeyValue } from "@/components/ui/Summary";
import { MOCK } from "@/lib/mock/v3c/mode";
import { Pics } from "../ui/parts";
import s from "./visit.module.css";

const title = (v: VendorVisitV3) => v.area_label ?? `${v.region} ${v.area_name}`;
export const visitTitle = title;

/** 고객이 직접 할 일(반셀프 칩 화면 말, 요청 때 고객이 업체에 알린 사본). 없으면 그리지 않아요(QA r7 N5: 브리핑 카드에만 보였어요) */
export function DiyFact({ v }: { v: VendorVisitV3 }) {
  if (!v.diy?.length) return null;
  return <p className={s.diy}><b>고객이 직접 할 일</b>{v.diy.join(", ")}</p>;
}
const occ = (v: VendorVisitV3) => (v.occupied ? "사는 중" : "빈 집");

/** 폰 한 줄(9판 V04 k-eb): '노원구 상계동 · 69.4㎡ · 아파트 · 전체 · 빈 집 · 고객 희망 12.7~12.21 · 공사 시작 희망 1.4(월) · 예산 300만 원' */
export function factLine(v: VendorVisitV3): string {
  return [
    title(v),
    // v3 집 글(home: '아파트 · 도배 전체 · 빈 집')을 먼저. home_text는 옛 꼴('노원구 · 21평 · 빈 집')이라 없을 때만
    v.home || v.home_text,
    v.wish_start && v.wish_end ? `고객 희망 ${rangeText(v.wish_start, v.wish_end)}` : null,
    v.work_wish_on ? `공사 시작 희망 ${dateShort(v.work_wish_on)}` : null,
    v.budget_won != null ? `예산 ${won(v.budget_won)}` : null,
  ].filter(Boolean).join(" · ");
}

/** 웹 요약 칸(D14 k-kv) */
export function FactsKV({ v }: { v: VendorVisitV3 }) {
  const items: [string, string][] = [["집", v.home || v.home_text || "—"]];
  if (v.wish_start && v.wish_end) items.push(["고객 희망", rangeText(v.wish_start, v.wish_end, { weekday: true })]);
  if (v.work_wish_on) items.push(["공사 시작 희망", dateShort(v.work_wish_on)]);
  if (v.estimate_total != null) items.push(["가견적", won(v.estimate_total)]);
  if (v.grade) items.push(["벽지", gradeLabel(v.grade)]);
  if (v.budget_won != null) items.push(["예산", won(v.budget_won)]);
  items.push(["받은 때", `${dateShort(v.received_at)} ${timeSeoul(v.received_at)}`]);
  return <KeyValue cols={3} items={items.map(([label, value]) => ({ key: label, label, value, num: true }))} />;
}

/** 고객이 올린 사진(위치 정보는 서버가 지운 뒤예요). 주소는 그 요청을 받은 업체만 여는 GET /vendor/visits/{vid}/photos/{fid}.
 *  예시 모드에는 사진 파일이 없어서 이름표 자리만 보여요 */
export function VisitPhotos({ v }: { v: VendorVisitV3 }) {
  if (!v.photos.length) return null;
  const label = (i: number) => v.photo_labels[i] ?? undefined;
  const alt = (i: number) => `요청 사진 ${i + 1}${label(i) ? ` · ${label(i)}` : ""}`;
  if (MOCK) return <Pics label="고객이 올린 사진" items={v.photos.map((f, i) => ({ key: f, label: label(i), alt: alt(i) }))} />;
  return (
    <PhotoGrid
      label="고객이 올린 사진"
      photos={v.photos.map((f, i) => ({ key: f, src: `/api/vendor/visits/${encodeURIComponent(v.id)}/photos/${encodeURIComponent(f)}`, alt: alt(i), label: label(i) }))}
    />
  );
}

export { occ };
