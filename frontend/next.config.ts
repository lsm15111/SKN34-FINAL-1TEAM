import type { NextConfig } from "next";

// 브라우저는 항상 같은 주소의 /api/* 로 부른다.
// 개발 중에는 Next가 api 컨테이너로 넘기고, 운영에서는 Caddy가 먼저 받아 넘긴다.
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // 파일을 받는 기능이 생기면 Next가 /api로 넘기는 본문 한도(기본 10MB)를 experimental.proxyClientMaxBodySize로 늘린다.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
