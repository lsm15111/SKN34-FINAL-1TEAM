// AI 답 글의 아주 작은 마크다운(굵게 **…** · 줄바꿈 · '- ' 목록 · '#' 제목 줄)을 화면 조각으로 나눠요.
// HTML을 만들지 않고 글 조각만 돌려줘요(그리는 쪽이 React 요소로 그려요 → 주입 없음). 그 밖의 표시는 글 그대로 둬요.
// 답이 흘러 들어오는 중에 닫는 **가 아직 안 왔으면 그 줄 끝까지 굵게 보여요(별표가 잠깐 보였다 사라지지 않게).

export type Span = { text: string; bold: boolean };
export type Line = Span[];
export type Block = { t: "p"; lines: Line[] } | { t: "list"; items: Line[] };

const ITEM = /^\s*[-*•]\s+(.*)$/;
const HEAD = /^\s*#{1,6}\s+(.*)$/;

/** 한 줄 → 굵게 · 보통 조각. '**'가 짝이 없으면 그 뒤를 줄 끝까지 굵게 */
export function spans(line: string): Line {
  const parts = line.split("**");
  const out: Line = [];
  parts.forEach((text, i) => {
    if (!text) return;
    const bold = i % 2 === 1;
    const last = out[out.length - 1];
    if (last && last.bold === bold) last.text += text;
    else out.push({ text, bold });
  });
  return out;
}

/** 글 → 문단(줄 묶음) · 목록. 빈 줄은 문단을 나눠요 */
export function blocks(text: string): Block[] {
  const out: Block[] = [];
  let para: Line[] | null = null;
  let list: Line[] | null = null;
  const close = () => {
    if (para?.length) out.push({ t: "p", lines: para });
    if (list?.length) out.push({ t: "list", items: list });
    para = null;
    list = null;
  };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { close(); continue; }
    const item = ITEM.exec(line);
    if (item) {
      if (para) { out.push({ t: "p", lines: para }); para = null; }
      (list ??= []).push(spans(item[1]));
      continue;
    }
    if (list) { out.push({ t: "list", items: list }); list = null; }
    const head = HEAD.exec(line);
    (para ??= []).push(head ? [{ text: head[1].replaceAll("**", ""), bold: true }] : spans(line));
  }
  close();
  return out;
}

const BLANK = /\n[ \t]*\n/;
const LISTY = /^\s*(?:[-*•]|\d{1,2}\.)\s+/m;

/**
 * 비서 답 글 → 말풍선 글들(피클처럼 생각 덩어리마다 말풍선을 나눠요). 빈 줄마다 나누고, 빈 줄이 없는 옛 답은 줄마다
 * 나눠요. 목록 줄이 든 글은 줄로 나누지 않아요(목록이 말풍선 여럿으로 흩어지지 않게).
 */
export function bubbles(text: string): string[] {
  const t = text.replace(/\r\n?/g, "\n").trim();
  if (!t) return [];
  const parts = BLANK.test(t) ? t.split(/\n[ \t]*\n+/) : LISTY.test(t) ? [t] : t.split("\n");
  return parts.map((x) => x.trim()).filter(Boolean);
}
