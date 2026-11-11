// 서버 쪽 읽기: MVP 예시 평면도 · 목공 자재. 견적 미리 보기는 고른 값마다 브라우저가 부른다(POST, client.ts).
import { serverGet, type Schemas } from "@/lib/backend/server";

export type MvpPlan = Schemas["MvpPlanBriefOut"];
export type MvpMaterials = Schemas["MvpMaterialsOut"];
export type MvpPreview = Schemas["MvpPreviewOut"];
export type MvpPreviewIn = Schemas["MvpPreviewIn"];
export type MvpMokSel = Schemas["MvpMokSelIn"];

/** 예시 평면도 목록 (공급면적 순). 로그인하지 않았으면 null */
export async function getMvpPlans() {
  return serverGet<MvpPlan[]>("/mvp/plans");
}

/** 목공 자재 · 정해진 단가 항목 · 등급별 처음 자재 */
export async function getMvpMaterials() {
  return serverGet<MvpMaterials>("/mvp/materials");
}
