// 앱 설치 정보(dev-01 PWA). Next가 /manifest.webmanifest로 내보내고 <link rel="manifest">를 넣어요.
// 화면 방향은 막지 않아요(WCAG 1.3.4). 색은 머리 바탕(흰색)과 같게 두어 앱 모드 상태 막대와 머리가 이어져 보여요.
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "믿집",
    short_name: "믿집",
    description: "아파트 도배 · 목공, 시장 데이터 기준 표준견적서와 업체 가견적을 비교하고 실측까지",
    lang: "ko",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    categories: ["lifestyle", "business"],
    icons: [
      { src: "/icons/192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
