// 화면 쪽 순수 함수 단위 시험(pnpm test:unit). 브라우저 · 서버를 띄우지 않아요. 흐름 e2e는 playwright.config.ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./lib",
  testMatch: /.*\.test\.ts$/,
  outputDir: "./e2e/.out/unit",
  reporter: [["list"]],
});
