// v2 백엔드 호출. 계산(금액 · 수량 · 날짜)과 AI는 모두 백엔드가 한다 (/api/mvp/v2/*).
import { call } from "@/lib/backend/client";

export const v2Post = <T,>(path: string, body: unknown) => call<T>("POST", `/mvp/v2/${path}`, body);
export const v2Get = <T,>(path: string) => call<T>("GET", `/mvp/v2/${path}`);
/** 이미 있는 MVP API (/mvp/plans · /mvp/materials) */
export const mvpGet = <T,>(path: string) => call<T>("GET", `/mvp/${path}`);
