// 서버 쪽 읽기: 예상 공정표 · 확정 공정표. 지금은 예시 데이터.
import { FX } from "@/lib/mock/data";

export async function getExpectedSchedule(_projectId: string) { return FX.expected; }
export async function getConfirmedSchedule(_projectId: string) { return FX.confirmed; }
