// 화면 응답 보안 머리 (security.md OP-01~03 · T18). Next 16의 proxy(예전 middleware)가 요청마다 붙여요.
// - CSP: 요청마다 새 nonce. 요청 머리 CSP에 넣으면 Next가 자기 스크립트에 nonce를 붙여요 → 화면은 동적 렌더링이어야 해요.
// - 스타일: React가 서버에서 style 속성으로 그려 nonce로는 못 열어서 'unsafe-inline'을 둬요. 스크립트는 nonce만 돼요.
// - 개발(next dev): React 디버깅 eval · HMR 웹소켓을 더 열어요. 운영 https에서만 HSTS · upgrade-insecure-requests.
// - CSP_REPORT_ONLY=true면 막지 않고 콘솔에 알리기만 해요(처음 켤 때 · 문제가 생겼을 때 되돌리기).
// - 지금 주소(경로 + 검색어)를 요청 머리 x-mj-path로 서버 화면에 넘겨요(로그인 뒤 돌아갈 next, lib/session.ts currentPath).
import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/components/auth/next";

const DEV = process.env.NODE_ENV === "development";
// 서버 화면이 읽는 지금 주소 머리. 이 사이트 안 경로만(safeNext: '//' · 역슬래시 · 공백 · 제어 문자 거절) · 1,024자 안
const PATH_HEADER = "x-mj-path";
const PATH_MAX = 1024;
// 개발 HMR 웹소켓 주소에 쓰는 Host 머리는 이 꼴만 받아요(머리에 다른 지시어를 끼워 넣지 못하게)
const HOST = /^(?:[\w.-]+|\[[0-9a-f:.]+\])(?::\d{1,5})?$/i;

const HEADERS: Record<string, string> = {
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "x-frame-options": "DENY",
  "cross-origin-opener-policy": "same-origin",
};

function policy(nonce: string, https: boolean, host: string | null): string {
  const hmr = DEV && host && HOST.test(host) ? ` ws://${host} wss://${host}` : "";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${DEV ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src 'self'${hmr}`,
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(https ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));
  const https = request.headers.get("x-forwarded-proto") === "https" || request.nextUrl.protocol === "https:";
  const csp = policy(nonce, https, request.headers.get("host"));
  const name = process.env.CSP_REPORT_ONLY === "true" ? "content-security-policy-report-only" : "content-security-policy";

  const forwarded = new Headers(request.headers);
  forwarded.set("x-nonce", nonce);
  forwarded.set(name, csp); // Next가 렌더링할 때 여기서 nonce를 읽어요
  const path = safeNext(request.nextUrl.pathname + request.nextUrl.search); // _rsc는 Next가 이미 뺐어요
  if (path && path.length <= PATH_MAX) forwarded.set(PATH_HEADER, path);
  else forwarded.delete(PATH_HEADER); // 브라우저가 같은 이름으로 보낸 값은 믿지 않아요
  const res = NextResponse.next({ request: { headers: forwarded } });
  res.headers.set(name, csp);
  for (const [k, v] of Object.entries(HEADERS)) res.headers.set(k, v);
  if (https) res.headers.set("strict-transport-security", "max-age=31536000; includeSubDomains");
  return res;
}

export const config = {
  matcher: [
    {
      // API(/api) · Next 내부 파일(/_next) · 확장자가 있는 정적 파일(아이콘 · sw.js · manifest)은 빼요
      source: "/((?!api(?:/|$)|_next/|.*\\.\\w+$).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
