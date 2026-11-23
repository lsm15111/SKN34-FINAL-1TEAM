import type { Metadata, Viewport } from "next";
import { connection } from "next/server";
import { LiveProvider } from "@/components/site/LiveProvider";
import { SwRegister } from "@/components/site/SwRegister";
import { ToastProvider } from "@/components/ui/Toast";
// 글꼴: Pretendard Variable 가변 다이나믹 서브셋(OFL, pretendard@1.3.9 · ADR design-01 · 리드 결정 2026-11-18).
// 쪽에 든 글자가 속한 조각(woff2 92개 중 몇 개)만 받아요. 같은 주소(/_next/static/media)에서 제공하고 swap으로 바꿔 넣어요.
// 받기 전에는 tokens.css --mj-font-sans의 대체 글꼴 줄(시스템 글꼴 → Apple SD Gothic Neo · Noto Sans KR · 맑은 고딕)로 보여요.
// 크기 · 고정폭 숫자(tnum) 확인: docs/v3/verification/b4.md
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "믿집", template: "%s · 믿집" },
  description: "아파트 도배 · 목공, 시장 데이터 기준 표준견적서와 업체 가견적을 비교하고 실측까지",
  applicationName: "믿집",
  // iOS 홈 화면 앱: 제목 · 상태 막대(기본값, standalone에서만 먹어요). 아이콘은 app/apple-icon.tsx
  appleWebApp: { capable: true, title: "믿집", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

// 앱 모드(PWA)에서 화면 끝까지 그리고 안전 영역은 CSS가 비워요. 확대는 막지 않아요(maximum-scale 안 씀).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#ffffff",
  colorScheme: "only light",
};

// 머리(SiteHeader · AppHeader)는 화면마다 그려요. 바닥글(SiteFooter)은 지금 숨겨 두었어요.
// 실시간 한 줄기(LiveProvider) · 토스트(ToastProvider)는 여기 한 곳에만 둬요. 서비스 워커는 운영에서만 등록해요(SwRegister).
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // 모든 화면을 요청 때 그려요: proxy.ts(B7)의 nonce CSP는 요청마다 그린 화면의 스크립트에만 붙어요.
  // 빌드 때 정적으로 만든 화면은 nonce가 없어 운영에서 스크립트가 막혀요(Next CSP 안내 · security.md OP-01).
  await connection();
  return (
    <html lang="ko">
      <body>
        <a className="mj-skip" href="#main">본문으로 건너뛰기</a>
        <LiveProvider>
          <ToastProvider>{children}</ToastProvider>
        </LiveProvider>
        <SwRegister />
      </body>
    </html>
  );
}
