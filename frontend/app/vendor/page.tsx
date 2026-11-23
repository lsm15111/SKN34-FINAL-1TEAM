import { ApplicationScreen } from "@/components/pro/home/ApplicationHome";
import { FirstDay } from "@/components/pro/home/FirstDay";
import { Inbox } from "@/components/pro/inbox/Inbox";
import { ProHeader, ProTabBar } from "@/components/pro/Shell";
import { Main } from "@/components/site/Frame";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  getMyApplication, getSetupDone, getVendorSchedule, getVendorVisit, getVisitSummary, listVendorVisits, vendorGate, vendorNow,
  type InboxSort, type InboxTab,
} from "@/lib/api/vendor";

export const metadata = { title: "작업함" };

const TABS: InboxTab[] = ["all", "todo", "waiting", "sched", "jobs", "done"];
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
type Search = { tab?: string | string[]; sort?: string | string[]; sel?: string | string[]; mock?: string | string[] };

// 업체 홈(/vendor). 승인 전: 심사 기다림 · 보완 요청(V14) · 거절(V22). 승인 뒤 받은 요청이 아직 없으면 처음 할 일(V02),
// 있으면 작업함(V03 폰 · D04 웹, ?tab= · ?sort= · ?sel=). 예시 데이터 모드에서는 ?mock=pending|needs_info|rejected|first로 모습을 바꿔 봐요.
export default async function VendorHome({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const mock = one(sp.mock);
  const me = await vendorGate("/vendor", mock);
  const app = await getMyApplication(mock);
  if (!app) {
    return (
      <>
        <ProHeader me={me} />
        <Main narrow>
          <EmptyState icon="store" as="h1" title="업체 신청을 찾을 수 없어요" action={<Button href="/login">다시 로그인</Button>}>로그인한 계정을 확인해 주세요.</EmptyState>
        </Main>
      </>
    );
  }
  if (app.status !== "approved") {
    return (
      <>
        <ProHeader me={me} />
        <ApplicationScreen app={app} />
      </>
    );
  }

  const summary = await getVisitSummary(mock);
  const total = summary ? summary.todo + summary.waiting + summary.sched + summary.jobs + summary.done : 0;
  if (summary && total === 0) {
    const done = await getSetupDone(mock);
    return (
      <>
        <ProHeader me={me} />
        <Main narrow><FirstDay done={done} home /></Main>
        <ProTabBar />
      </>
    );
  }

  const tab = TABS.find((t) => t === one(sp.tab)) ?? "todo";
  const sort: InboxSort = one(sp.sort) === "new" ? "new" : "due";
  const [page, schedule] = await Promise.all([
    tab === "sched" ? Promise.resolve({ items: [], next_before: null }) : listVendorVisits(tab, sort),
    tab === "sched" ? getVendorSchedule(vendorNow("sched")) : Promise.resolve(null),
  ]);
  const selKey = one(sp.sel);
  const selRow = page.items.find((r) => (r.deal_id ?? r.id) === selKey) ?? page.items[0] ?? null;
  const sel = selRow && !selRow.deal_id ? await getVendorVisit(selRow.id) : null;

  return (
    <>
      <ProHeader me={me} />
      <Main>
        <Inbox tab={tab} sort={sort} summary={summary} page={page} selRow={selRow} sel={sel} now={vendorNow(tab === "sched" ? "sched" : "inbox")} schedule={schedule} />
      </Main>
      <ProTabBar />
    </>
  );
}
