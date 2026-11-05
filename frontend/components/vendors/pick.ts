// 실측 요청에 담은 업체 · 남길 말 (이 기기 sessionStorage, 프로젝트 · 공정마다).
// 휴대폰 번호를 넣고 돌아와도 담은 그대로다. 보내고 나면 보낸 업체를 뺀다.
// 업체 고르기 목록과 업체 자세히(오른쪽 창 · 전체 화면)가 같이 쓴다. 바꾸면 PICK_EVENT로 서로 알린다.
import { useEffect, useState } from "react";
import type { VTrade } from "./text";

export type Pick = { ids: string[]; msg: string };
const key = (projectId: string, trade: VTrade) => `mj_visit_pick_${projectId}_${trade}`;
export const PICK_EVENT = "mj-visit-pick";
/** 업체 자세히 창의 '실측 요청 보내기': 목록(VendorBoard)이 받아 확인 창을 연다 */
export const SEND_EVENT = "mj-visit-send";

export function readPick(projectId: string, trade: VTrade): Pick {
  try {
    const raw = sessionStorage.getItem(key(projectId, trade));
    const v = raw ? JSON.parse(raw) : null;
    const ids = Array.isArray(v?.ids) ? v.ids.filter((x: unknown): x is string => typeof x === "string") : [];
    return { ids, msg: typeof v?.msg === "string" ? v.msg : "" };
  } catch {
    return { ids: [], msg: "" };
  }
}

export function writePick(projectId: string, trade: VTrade, p: Pick) {
  try {
    if (!p.ids.length && !p.msg) sessionStorage.removeItem(key(projectId, trade));
    else sessionStorage.setItem(key(projectId, trade), JSON.stringify(p));
  } catch { /* 저장 못 해도 화면은 그대로 */ }
  window.dispatchEvent(new Event(PICK_EVENT));
}

/** 담은 업체를 읽고, 다른 곳(목록 · 창)에서 바꾸면 다시 읽는다 */
export function usePick(projectId: string, trade: VTrade): Pick {
  const [p, setP] = useState<Pick>({ ids: [], msg: "" });
  useEffect(() => {
    const read = () => setP(readPick(projectId, trade));
    read();
    window.addEventListener(PICK_EVENT, read);
    return () => window.removeEventListener(PICK_EVENT, read);
  }, [projectId, trade]);
  return p;
}

// 업체 자세히 창을 목록에서 열었는지 (닫을 때 뒤로 가기로 목록에 돌아간다)
const FROM = "mj_vendor_panel_from";
export function markFromList(listHref: string) {
  try { sessionStorage.setItem(FROM, listHref); } catch { /* 없으면 닫을 때 목록 주소로 간다 */ }
}
export function takeFromList(listHref: string): boolean {
  try {
    const ok = sessionStorage.getItem(FROM) === listHref;
    sessionStorage.removeItem(FROM);
    return ok;
  } catch {
    return false;
  }
}
