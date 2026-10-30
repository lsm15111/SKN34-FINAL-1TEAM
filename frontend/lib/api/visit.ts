// 서버 쪽 읽기: 실측. 지금은 예시 데이터.
import { VISITS } from "@/lib/mock/data";

export async function getVisits(projectId: string) { return VISITS[projectId] ?? []; }
