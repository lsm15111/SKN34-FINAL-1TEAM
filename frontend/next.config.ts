import type { NextConfig } from "next";

// 브라우저는 항상 같은 주소의 /api/* 로 부른다.
// 개발 중에는 Next가 api 컨테이너로 넘기고, 운영에서는 Caddy가 먼저 받아 넘긴다.
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Next가 /api로 넘기는 요청 본문은 기본 10MB까지만 옮긴다. 도면은 20MB까지 받으므로 넉넉히 늘린다.
  // (운영에서 /api를 앞단 프록시가 바로 API로 보내면 이 값과 상관없다.)
  experimental: { proxyClientMaxBodySize: "25mb" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
