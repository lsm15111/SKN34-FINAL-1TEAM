// 알림(시안 WNotify). 고객 · 업체가 같은 화면을 쓰고 머리만 역할별로 다르다.
// ?project= 를 주면 그 공사 소식만 본다(내 공사 화면의 '소식'). 지난 알림 더 보기는 API가 최근 50개만 줘서 아직 없다.
import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { NotifyList } from "@/components/notify/NotifyList";
import { ReadAllButton } from "@/components/notify/ReadAllButton";
import { isProjectId, listNotifications } from "@/lib/api/notify";
import { listMyProjects } from "@/lib/api/project";
import { sizeLabel } from "@/lib/labels";
import { requireRole } from "@/lib/session";
import s from "@/components/notify/notify.module.css";

export const metadata = { title: "알림" };

export default async function NotificationsPage({ searchParams }: { searchParams: Promise<{ project?: string | string[] }> }) {
  const raw = (await searchParams).project;
  const pick = Array.isArray(raw) ? raw[0] : raw;
  const project = pick && isProjectId(pick) ? pick : undefined;
  const session = await requireRole(["customer", "vendor"], project ? `/notifications?project=${project}` : "/notifications");
  const customer = session.role === "customer";
  const [page, projects] = await Promise.all([listNotifications(project), customer ? listMyProjects() : Promise.resolve([])]);

  // 거르기 칩: 전체 + 내 공사(고객, 공사 번호로 나눔). 업체이거나 목록에 없는 공사를 고른 때는 '이 공사 소식' 칩 하나
  const chips = projects.map((p) => ({ id: p.id, label: `${p.code} · ${p.region} · ${sizeLabel(p.size)}` }));
  if (project && !chips.some((c) => c.id === project)) chips.push({ id: project, label: "이 공사 소식" });

  return (
    <>
      <SiteHeader />
      <main id="main">
        <div className={`mj-wrap ${s.head}`}>
          <div className={s.title}>
            <h1 className="mj-h1">알림</h1>
            <p className="mj-sub mj-num">{page.unread ? `안 읽은 알림 ${page.unread}개` : "안 읽은 알림이 없어요"}</p>
          </div>
          <ReadAllButton unread={page.unread} />
        </div>

        <div className={`mj-wrap ${s.body}`}>
          {chips.length ? (
            <nav className={s.chips} aria-label="알림 거르기">
              <Link className={s.chip} href="/notifications" aria-current={project ? undefined : "true"}>전체</Link>
              {chips.map((c) => (
                <Link key={c.id} className={s.chip} href={`/notifications?project=${c.id}`} aria-current={project === c.id ? "true" : undefined}>{c.label}</Link>
              ))}
            </nav>
          ) : null}

          {page.items.length ? (
            <NotifyList items={page.items} />
          ) : project ? (
            <div className={s.empty}>
              <h2 className="mj-h3">이 공사 소식이 아직 없어요</h2>
              <p className="mj-sub">{customer ? "업체가 견적서를 보내거나 공사 날짜를 올리면 여기에 알려 드려요." : "고객이 실측을 요청하거나 공사 날짜를 정하면 여기에 알려 드려요."}</p>
              <Link className="mj-btn mj-btn-sec mj-btn-sm" href="/notifications">전체 알림 보기</Link>
            </div>
          ) : (
            <div className={s.empty}>
              <h2 className="mj-h3">아직 알림이 없어요</h2>
              <p className="mj-sub">
                {customer
                  ? "업체가 견적서를 보내거나 공사 날짜를 올리면 여기에 알려 드려요."
                  : "고객이 실측을 요청하거나 업체를 확정하면 여기에 알려 드려요. 가입 심사 결과도 여기로 와요."}
              </p>
              <Link className="mj-btn mj-btn-sec mj-btn-sm" href={customer ? "/my" : "/vendor"}>{customer ? "내 공사 보기" : "작업함 보기"}</Link>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
