// 업체 화면이 이미 읽은 요청 사실 → 비서 브리핑 씨앗(BriefSeed). 목업 브리핑이 요약 줄을 이 값으로 채워요.
// 실제 API(/vendor/assistant/briefs/{vid})는 서버가 같은 사실로 만들어서 이 씨앗을 쓰지 않아요.
import type { BriefSeed } from "@/lib/api/assistant";
import type { InboxRowV3, VendorVisitV3 } from "@/lib/api/vendor";
import { gradeLabel } from "@/lib/labels";
import { visitTitle } from "../visit/facts";
import { rowTitle } from "../inbox/rows";

export function seedFromVisit(v: VendorVisitV3): BriefSeed {
  return {
    region: visitTitle(v),
    area: null,
    grade: v.grade ? gradeLabel(v.grade) : null,
    occupied: v.occupied,
    wish: v.wish_start && v.wish_end ? { start: v.wish_start, end: v.wish_end } : null,
    work_wish_on: v.work_wish_on ?? null,
    estimate_won: v.estimate_total ?? null,
    photos: v.photos.length,
    due_at: v.next?.due_at ?? null,
    memo: v.message,
  };
}

export function seedFromRow(r: InboxRowV3): BriefSeed {
  return {
    region: rowTitle(r),
    area: null,
    grade: r.grade ? gradeLabel(r.grade) : null,
    wish: r.wish_start && r.wish_end ? { start: r.wish_start, end: r.wish_end } : null,
    work_wish_on: r.work_wish_on ?? null,
    estimate_won: r.estimate_total ?? null,
    due_at: r.next?.due_at ?? null,
  };
}
