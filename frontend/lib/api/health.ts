// 서버 쪽 읽기: 연결 상태. 영역마다 lib/api/<영역>.ts 한 파일을 두고 화면은 여기만 부른다.
import { serverGet } from "@/lib/backend/server";

export type Ready = { status: string; checks: Record<string, string> };

/** API · DB · Redis가 모두 붙으면 true. API가 안 떴거나 하나라도 안 되면(503) false. */
export async function isReady(): Promise<boolean> {
  try {
    return (await serverGet<Ready>("/health/ready"))?.status === "ok";
  } catch {
    return false;
  }
}
