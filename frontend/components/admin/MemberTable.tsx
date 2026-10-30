"use client";
// 회원관리: 찾기 · 상태 거르기 · 계정 상태 바꾸기
import { useMemo, useState } from "react";
import type { Member } from "@/lib/types";
import { md } from "@/lib/format";

export function MemberTable({ initial }: { initial: Member[] }) {
  const [rows, setRows] = useState(initial);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "suspended">("all");
  const [asking, setAsking] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const list = useMemo(() => rows.filter((m) => (status === "all" || m.status === status) && (!q.trim() || m.name.includes(q.trim()) || m.email.includes(q.trim()))), [rows, q, status]);

  function flip(id: string) {
    setRows((r) => r.map((m) => (m.id === id ? { ...m, status: m.status === "active" ? "suspended" : "active" } : m)));
    const m = rows.find((x) => x.id === id);
    setMsg(`${m?.name} 계정을 ${m?.status === "active" ? "정지했어요" : "다시 쓸 수 있게 했어요"}.`);
    setAsking(null);
  }

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
        <div className="mj-field" style={{ flex: "1 1 260px" }}><label className="mj-label" htmlFor="mq">이름 · 이메일로 찾기</label><input id="mq" className="mj-input" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="mj-field" style={{ flex: "0 1 200px" }}>
          <label className="mj-label" htmlFor="ms">계정 상태</label>
          <select id="ms" className="mj-select" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="all">전체</option><option value="active">사용 중</option><option value="suspended">정지</option></select>
        </div>
      </div>
      <p className="mj-small" aria-live="polite">{list.length}명 · {msg}</p>
      <div className="mj-table-box">
        <table className="mj-table" style={{ minWidth: 720 }}>
          <caption className="mj-sr">회원 목록</caption>
          <thead><tr><th scope="col">이름</th><th scope="col">이메일</th><th scope="col">가입일</th><th scope="col" className="r">프로젝트</th><th scope="col">상태</th><th scope="col">관리</th></tr></thead>
          <tbody>
            {list.map((m) => (
              <tr key={m.id}>
                <th scope="row">{m.name}</th>
                <td>{m.email}</td>
                <td className="mj-num">{md(m.joinedAt)}</td>
                <td className="r mj-num">{m.projects}</td>
                <td><span className={`mj-badge ${m.status === "active" ? "mj-b-ok" : "mj-b-no"}`} style={{ textDecoration: "none" }}>{m.status === "active" ? "사용 중" : "정지"}</span></td>
                <td>
                  {asking === m.id ? (
                    <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button type="button" className={`mj-btn mj-btn-sm ${m.status === "active" ? "mj-btn-danger" : "mj-btn-pri"}`} onClick={() => flip(m.id)}>{m.status === "active" ? "정지할게요" : "다시 쓰게 할게요"}</button>
                      <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => setAsking(null)}>취소</button>
                    </span>
                  ) : (
                    <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => setAsking(m.id)}>{m.status === "active" ? "계정 정지" : "정지 풀기"}<span className="mj-sr"> · {m.name}</span></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
