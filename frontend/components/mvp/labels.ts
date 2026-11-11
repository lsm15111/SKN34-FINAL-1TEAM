// MVP 화면 말. 팀 lib/labels.ts는 그대로 두고, MVP에서만 쓰는 이름을 여기에 둔다.

export type Grade = "economy" | "basic" | "premium";
export const GRADES: { key: Grade; label: string; desc: string }[] = [
  { key: "economy", label: "베이직", desc: "합지 벽지 · 평몰딩" },
  { key: "basic", label: "스탠다드", desc: "실크 벽지 · 계단몰딩" },
  { key: "premium", label: "프리미엄", desc: "실크 벽지 · 무몰딩" },
];
export const gradeName = (k: string | null | undefined) => GRADES.find((g) => g.key === k)?.label ?? "스탠다드";

export type DoorMode = "none" | "replace" | "overlay" | "leaf";
export const DOOR_MODES: { key: DoorMode; label: string }[] = [
  { key: "none", label: "안 함" },
  { key: "replace", label: "문틀까지 교체" },
  { key: "overlay", label: "문틀 덧방" },
  { key: "leaf", label: "문짝만 교체" },
];

export type MoldingType = "flat" | "step" | "minus" | "none";
export const MOLDING_TYPES: { key: MoldingType; label: string }[] = [
  { key: "flat", label: "평몰딩" },
  { key: "step", label: "계단몰딩" },
  { key: "minus", label: "무몰딩" },
  { key: "none", label: "안 함" },
];

// 줄 단가의 근거
export const BASIS: Record<string, string> = {
  public: "공공 기준",
  market: "실견적",
  pick: "고른 자재",
  assumed: "팀 가정값",
  none: "업체 확인",
};
