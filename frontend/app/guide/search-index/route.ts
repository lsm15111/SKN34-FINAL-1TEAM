// 백과 찾기 창이 처음 열릴 때 한 번 받는 가벼운 목록(용어 · 글 · 자주 묻는 질문). 글이 바뀌면 다시 배포해요.
import { searchIndex } from "@/lib/guide";

export const dynamic = "force-static";

export function GET() {
  return Response.json(searchIndex(), { headers: { "cache-control": "public, max-age=3600" } });
}
