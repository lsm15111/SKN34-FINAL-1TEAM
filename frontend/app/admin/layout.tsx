import { SiteHeader } from "@/components/site/SiteHeader";
import { requireRole } from "@/lib/session";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  await requireRole("admin", "/admin/members");
  return (
    <>
      <SiteHeader variant="admin" />
      {children}
    </>
  );
}
