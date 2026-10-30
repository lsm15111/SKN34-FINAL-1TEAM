"use client";
// 공정표를 그림 파일(PNG)로 저장한다. 화면의 표와 같은 데이터로 캔버스에 다시 그린다 (월 · 일 머리줄, 하루 한 칸, 휴무일 회색).
import { calendarSpan } from "@/lib/format";
import { monthGroups, period, type GanttRow } from "./Gantt";

export function GanttDownload({ title, days, rows, filename }: { title: string; days: string[]; rows: GanttRow[]; filename: string }) {
  function save() {
    const cal = calendarSpan(days);
    const work = new Set(days);
    const colW = 44, labelW = 300, rowH = 54, top = 118, pad = 32;
    const w = pad * 2 + labelW + cal.length * colW, h = top + rows.length * rowH + 40;
    const c = document.createElement("canvas");
    const scale = 2;
    c.width = w * scale; c.height = h * scale;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);
    const font = getComputedStyle(document.body).fontFamily;
    const x0 = pad + labelW;
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#172233"; ctx.font = `700 20px ${font}`; ctx.fillText(title, pad, 40);

    // 범례
    const legend: [string, string][] = [["#2d6cb5", "목공 · 공통"], ["#b9d3f3", "도배"], ["#eceff3", "휴무 (일요일 · 공휴일)"]];
    let lx = pad;
    ctx.font = `13px ${font}`;
    legend.forEach(([color, text]) => {
      ctx.fillStyle = color; ctx.fillRect(lx, 54, 14, 14);
      ctx.fillStyle = "#46546a"; ctx.fillText(text, lx + 20, 66);
      lx += 26 + ctx.measureText(text).width + 16;
    });

    // 휴무일 칸 · 날짜 구분선
    cal.forEach((d, i) => {
      const x = x0 + i * colW;
      if (!work.has(d)) { ctx.fillStyle = "#eceff3"; ctx.fillRect(x, top - 26, colW, rows.length * rowH + 26); }
      ctx.strokeStyle = "#eef2f6"; ctx.beginPath(); ctx.moveTo(x + 0.5, top - 26); ctx.lineTo(x + 0.5, top + rows.length * rowH); ctx.stroke();
    });
    // 월 · 일 머리줄
    let mi = 0;
    monthGroups(cal).forEach((g) => {
      ctx.fillStyle = "#46546a"; ctx.font = `700 13px ${font}`; ctx.fillText(`${g.m}월`, x0 + mi * colW + 6, top - 34);
      mi += g.n;
    });
    cal.forEach((d, i) => {
      ctx.fillStyle = work.has(d) ? "#46546a" : "#8a96a6"; ctx.font = `13px ${font}`;
      const t = String(Number(d.slice(8, 10)));
      ctx.fillText(t, x0 + i * colW + (colW - ctx.measureText(t).width) / 2, top - 8);
    });

    rows.forEach((r, j) => {
      const y = top + j * rowH;
      ctx.strokeStyle = "#d8e2ee"; ctx.beginPath(); ctx.moveTo(pad, y + 0.5); ctx.lineTo(w - pad, y + 0.5); ctx.stroke();
      ctx.fillStyle = "#56647a"; ctx.font = `13px ${font}`; ctx.fillText(String(j + 1), pad, y + 22);
      ctx.fillStyle = "#172233"; ctx.font = `700 14px ${font}`; ctx.fillText(r.label, pad + 22, y + 22);
      ctx.fillStyle = "#56647a"; ctx.font = `12px ${font}`; ctx.fillText(`${r.sub} · ${period(r)}`, pad + 22, y + 40);
      // 이어지는 일하는 날을 막대 하나로
      let start = -1;
      cal.forEach((d, i) => {
        const on = work.has(d) && d >= r.from.date && d <= r.to.date;
        if (on && start < 0) start = i;
        const nextOn = i + 1 < cal.length && work.has(cal[i + 1]) && cal[i + 1] >= r.from.date && cal[i + 1] <= r.to.date;
        if (on && !nextOn) {
          ctx.fillStyle = r.tone === "b" ? "#b9d3f3" : "#2d6cb5";
          const bx = x0 + start * colW + 3, bw = (i - start + 1) * colW - 6;
          ctx.beginPath(); ctx.roundRect(bx, y + 12, bw, 30, 7); ctx.fill();
          start = -1;
        }
      });
    });
    c.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  }
  return <button type="button" className="mj-btn mj-btn-sec" onClick={save}>그림 파일로 저장</button>;
}
