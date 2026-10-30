// 서버 쪽 읽기: 관리자. 업체 가입 신청은 실제 API, 회원 목록은 예시 데이터.
import { serverGet, type Schemas } from "@/lib/backend/server";
import { MEMBERS } from "@/lib/mock/data";

export async function listMembers() { return MEMBERS; }

export type VendorApplication = Schemas["VendorAdminOut"];
export type VendorStatus = "pending" | "approved" | "rejected";
export async function listVendorApplications(status?: VendorStatus) {
  return (await serverGet<VendorApplication[]>(`/admin/vendors${status ? `?status=${status}` : ""}`)) ?? [];
}
export async function getVendorApplication(id: string) {
  return /^[0-9a-f-]{36}$/i.test(id) ? serverGet<VendorApplication>(`/admin/vendors/${id}`) : null;
}
