import { notFound } from "next/navigation";
import { DatesForm } from "@/components/pro/jobs/DatesForm";
import { DoneForm } from "@/components/pro/jobs/DoneForm";
import { ExtraForm } from "@/components/pro/jobs/ExtraForm";
import { JobView } from "@/components/pro/jobs/JobView";
import { ProHeader } from "@/components/pro/Shell";
import { approvedVendorGate, getMyProfile, getVendorJob, getVendorJobLog, vendorNow } from "@/lib/api/vendor";

export const metadata = { title: "공사 한 건" };

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
const NEED_DATES = ["waiting", "requested", "change_requested"];

// 공사 한 건(알림 link: /vendor/jobs/{did}). 공사 날짜를 아직 안 냈거나 고객이 다른 날짜를 요청했으면 공사 날짜 올리기(V11),
// 그 밖에는 공사 한 건(V23). ?step=extra 추가 금액(V12) · ?step=done 공사 끝(V13). 남의 공사면 404.
export default async function VendorJobPage({ params, searchParams }: { params: Promise<{ dealId: string }>; searchParams: Promise<{ step?: string | string[] }> }) {
  const { dealId } = await params;
  const step = one((await searchParams).step);
  const me = await approvedVendorGate(`/vendor/jobs/${encodeURIComponent(dealId)}`);
  const job = await getVendorJob(dealId);
  if (!job) notFound();
  const href = `/vendor/jobs/${encodeURIComponent(job.deal_id)}`;
  const working = job.dates_state === "scheduled" && !job.done_posted_at && !job.work_done_on && job.status !== "done";

  if (step === "extra" && working) {
    const profile = await getMyProfile().catch(() => null);
    return (
      <>
        <ProHeader me={me} phone={{ title: "추가 금액 올리기", back: href }} />
        <ExtraForm job={job} taxKind={profile?.tax_kind ?? "general"} />
      </>
    );
  }
  if (step === "done" && working && job.can_finish) {
    return (
      <>
        <ProHeader me={me} phone={{ title: "공사 끝냈어요", back: href }} />
        <DoneForm job={job} />
      </>
    );
  }
  if (NEED_DATES.includes(job.dates_state)) {
    return (
      <>
        <ProHeader me={me} phone={{ title: "공사 날짜 올리기", back: "/vendor?tab=jobs" }} />
        <DatesForm job={job} now={vendorNow("dates")} />
      </>
    );
  }
  const log = await getVendorJobLog(job.deal_id);
  return (
    <>
      <ProHeader me={me} phone={{ title: "공사 한 건", back: "/vendor?tab=jobs" }} />
      <JobView job={job} log={log} now={vendorNow("job")} />
    </>
  );
}
