// v5 화면이 쓰는 API 타입: dev 타입(lib/backend/schema.d.ts, 손대지 않아요) + v4 백엔드에만 있는 칸.
// - 더한 칸은 모두 선택(?)이에요. dev 백엔드는 이 칸을 주지 않으니 화면은 값이 있을 때만 그려요.
// - 보내는 칸(방 개수 · 철거 범위 · 직접 할 일)은 기능 확인(lib/v5/caps.ts)이 켜졌을 때만 보내요(dev HomeInfoIn은 모르는 칸을 422로 막아요).
// - v4 백엔드가 dev에 붙으면 pnpm gen:api로 schema.d.ts에 같은 칸이 생기고, 여기 더한 칸은 그대로 맞아요.
import type { components } from "@/lib/backend/schema";

type Dev = components["schemas"];

/** 공간 칩: dev 8칸 + v4 방 개수 칩(작은방 3 · 4) */
type SpaceKey = Dev["HomeInfoIn"]["spaces"][number] | "room3" | "room4";
/** 직접 할 일(반셀프 칩) 키: v4 backend project/diy.py */
type DiyKey = "paint" | "outlet" | "light" | "silicone" | "handle" | "clean" | "paper_buy";
type Demolition = "full" | "partial" | "none";
type Profile = "paper_only" | "remodel";

/** v4 백엔드에만 있는 타입 */
type V4Only = {
  /** 벽지 롤 수(calc.rolls) */
  RollOut: { key: "silk" | "hapji_wide" | "hapji_narrow"; name: string; size: string; count: number; spare_min: number; spare_max: number; text: string };
  /** 방 개수 기본값 한 칸 */
  RoomBandOut: { area_basis: "supply" | "exclusive"; min_m2: string; rooms: number };
  /** 방 개수 칸(GET /guest/room-rule) */
  RoomRuleOut: { price_ver: string; share_ver: string; min: number; max: number; fallback: number; bands: V4Only["RoomBandOut"][]; room_kinds: string[] };
  /** 공사 희망 시기 칩(GET /guest/start-options) */
  StartWishOut: { key: "this_month" | "next_month" | "in_2_3_months"; start_date: string };
  /** 모은 조건 한 칸(GET /projects/{id}/conditions) */
  ConditionOut: { trade: string; key: string; label: string; value: string };
  /** 직접 할 일 고치기(PUT /projects/{id}/diy) */
  DiyIn: { diy: DiyKey[] };
  DiyOut: { diy: DiyKey[] | null; told: string[]; notice?: string | null };
};

/** dev 타입에 더하거나 넓히는 칸 */
type Extra = {
  HomeInfoIn: { spaces: SpaceKey[]; rooms?: number | null; demolition?: Demolition | null; diy?: DiyKey[] | null };
  HomeInfoOut: { spaces: SpaceKey[]; rooms?: number | null; demolition?: Demolition | null };
  GuestStandardOut: { rooms?: number | null; profile?: Profile | null; profile_name?: string | null; own_paper?: boolean; rolls_text?: string | null };
  StandardTradeOut: { days?: string | null; profile?: Profile | null; profile_name?: string | null; own_paper?: boolean; rolls?: V4Only["RollOut"] | null; paper_note?: string | null };
  EstimateV3LineOut: { optional?: boolean; label?: string; note?: string };
  PeriodOut: { work_end?: string | null };
  PublicProfileOut: { intro?: string | null };
  QuoteBoardOut: { quote_due_at?: string | null };
  VendorListOut: { paper_note?: string | null };
  VendorVisitDetailOut: { diy?: string[] };
  JobOut: { busy_days?: string[] };
};

type Merge<A, B> = Omit<A, keyof B> & B;
type Flat = { [K in keyof Dev | keyof Extra]: K extends keyof Extra ? (K extends keyof Dev ? Merge<Dev[K], Extra[K]> : never) : K extends keyof Dev ? Dev[K] : never };

/** 넓힌 타입을 담은 바깥 타입도 넓혀요(StandardOut.trades · VendorDetailOut.profile 등) */
type Nested = {
  StandardOut: Merge<Dev["StandardOut"], { trades: Flat["StandardTradeOut"][] }>;
  EstimateV3Out: Merge<Dev["EstimateV3Out"], { lines: Flat["EstimateV3LineOut"][] }>;
  VendorDetailOut: Merge<Dev["VendorDetailOut"], {
    profile: Flat["PublicProfileOut"];
    estimate_v3?: Merge<Dev["EstimateV3Out"], { lines: Flat["EstimateV3LineOut"][] }> | null;
  }>;
  OverviewOut: Merge<Dev["OverviewOut"], { period: Flat["PeriodOut"] }>;
  ProjectOut: Merge<Dev["ProjectOut"], { home?: Flat["HomeInfoOut"] | null }>;
  JobOut: Merge<Flat["JobOut"], { visit: Flat["VendorVisitDetailOut"] }>;
};

export type Schemas = Merge<Flat, Nested> & V4Only;
