"""v10 CSS → CSS 모듈: 모든 규칙을 .root 아래 :global(...)로 감싼다."""
import io, re, sys
src = io.open(sys.argv[1], encoding="utf-8").read()
src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

def split_top(s, ch=","):
    out, depth, cur = [], 0, ""
    for c in s:
        if c in "([": depth += 1
        elif c in ")]": depth -= 1
        if c == ch and depth == 0: out.append(cur); cur = ""
        else: cur += c
    out.append(cur); return [x.strip() for x in out if x.strip()]

def sel(x):
    x = x.strip()
    if x in (":root", "html", "body"): return ".root"
    if x == "body::before": return ".root::before"
    if x.startswith("body.mat-open"): return None
    if x.startswith("body "): x = x[5:]
    if x.startswith(":root "): x = x[6:]
    return f".root :global({x})"

def convert(block):
    out, i, n = [], 0, len(block)
    while i < n:
        j = block.find("{", i)
        if j < 0: break
        head = block[i:j].strip()
        depth, k = 1, j + 1
        while depth:
            if block[k] == "{": depth += 1
            elif block[k] == "}": depth -= 1
            k += 1
        body = block[j + 1:k - 1]
        if head.startswith("@keyframes"):
            out.append(f"{head} {{{body}}}")
        elif head.startswith("@media") or head.startswith("@supports"):
            out.append(f"{head} {{\n{convert(body)}\n}}")
        else:
            sels = [s for s in (sel(x) for x in split_top(head)) if s]
            if sels: out.append(f"{', '.join(sels)} {{{body.rstrip()} }}")
        i = k
    return "\n".join(out)

res = convert(src)
io.open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(
    "/* v10 디자인을 /v2 화면에만 적용한다. 원본 v10 CSS를 .root 아래로 감쌌다 (scratchpad css_port.py로 만듦) */\n" + res + "\n")
print(len(res.splitlines()))
