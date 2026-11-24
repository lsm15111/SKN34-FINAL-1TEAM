// 서버 쪽 읽기: 업체 보기 · 업체 자세히 · 리뷰 · 담은 업체(고객, api.md 4장). 쓰기(담기 · 빼기)는 브라우저가 /api로 해요.
// 예시(lib/mock/v3a)는 개발에서 NEXT_PUBLIC_MJ_MOCK=1이고 예시 공사 id일 때만이에요. lib/api/visit.ts(실측 일정)는 B2b 것이라 여기 따로 둬요.
import { serverGet, type Schemas } from "@/lib/backend/server";
import { mockKeyOf } from "@/lib/mock/v3a/mode";
import { mockPhotoSrc, mockReviews, mockShortlist, mockVendorDetail, mockVendorList } from "@/lib/mock/v3a/vendors";
import { isUuid } from "./project";

const seg = (id: string) => encodeURIComponent(id);

export type VendorList = Schemas["VendorListOut"];
export type VendorCardData = Schemas["VendorCardOut"];
export type VendorDetail = Schemas["VendorDetailOut"];
export type ReviewPage = Schemas["ReviewPageOut"];
export type ReviewItem = Schemas["ReviewItemOut"];
export type Shortlist = Schemas["ShortlistOut"];
export type Grade = "economy" | "basic";

/** 이 집 도배 업체(가견적 낮은 순). 이 구에 없으면 가까운 구(C12). 남의 공사면 null */
export async function getVendorList(projectId: string): Promise<VendorList | null> {
  const k = mockKeyOf(projectId);
  if (k) return mockVendorList(k);
  return isUuid(projectId) ? serverGet<VendorList>(`/projects/${seg(projectId)}/vendors?trade=dobae&sort=estimate`) : null;
}

/** 업체 자세히. grade를 주면 그 벽지로 미리 보기(C11 '합지 −31만 1,850원'). 목록 밖 업체면 null */
export async function getVendorDetail(projectId: string, vendorId: string, grade?: Grade | null): Promise<VendorDetail | null> {
  const k = mockKeyOf(projectId);
  if (k) return mockVendorDetail(k, vendorId, grade);
  if (!isUuid(projectId) || !isUuid(vendorId)) return null;
  const q = new URLSearchParams({ trade: "dobae" });
  if (grade) q.set("grade", grade);
  return serverGet<VendorDetail>(`/projects/${seg(projectId)}/vendors/${seg(vendorId)}?${q.toString()}`);
}

/** 리뷰 전체(최신순 · 낮은 별점부터, 숨긴 리뷰 빠짐). before는 다음 쪽 커서, limit은 한 쪽 수(API 기본 50 · 최대 100) */
export async function getVendorReviews(projectId: string, vendorId: string, sort: "latest" | "low", before?: string | null, limit?: number): Promise<ReviewPage | null> {
  if (mockKeyOf(projectId)) return mockReviews(vendorId, sort);
  if (!isUuid(projectId) || !isUuid(vendorId)) return null;
  const q = new URLSearchParams({ sort });
  if (before) q.set("before", before);
  if (limit) q.set("limit", String(limit));
  return serverGet<ReviewPage>(`/projects/${seg(projectId)}/vendors/${seg(vendorId)}/reviews?${q.toString()}`);
}

/** 담은 업체(공사 · 공종마다 3칸). 남의 공사면 null */
export async function getShortlist(projectId: string): Promise<Shortlist | null> {
  const k = mockKeyOf(projectId);
  if (k) return mockShortlist(k);
  return isUuid(projectId) ? serverGet<Shortlist>(`/projects/${seg(projectId)}/shortlist?trade=dobae`) : null;
}

/** 시공 사진 주소(같은 주소 /api, 권한은 API가 봐요). 예시 공사면 그린 자리 그림(index번째) */
export function photoSrc(projectId: string, vendorId: string, fileId: string, index = 0): string {
  if (mockKeyOf(projectId)) return mockPhotoSrc(index);
  return `/api/projects/${seg(projectId)}/vendors/${seg(vendorId)}/photos/${seg(fileId)}`;
}
