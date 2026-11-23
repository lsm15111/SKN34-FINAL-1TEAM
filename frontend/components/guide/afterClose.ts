// 폰 창(찾기 · AI 채팅)은 열 때 기록 한 칸을 넣어 뒤로 가기로 닫혀요(useModal closeOnBack).
// 창을 닫자마자 다른 화면으로 가면, 그 칸을 걷는 '뒤로'가 늦게 와서 시작한 이동을 취소해요.
// 그래서 칸이 있으면 걷힌 뒤(popstate)에 다음 일을 해요. Menu.tsx와 같은 방식이고, 안 오면 0.5초 뒤에 해요.
export function afterClose(close: () => void, then: () => void) {
  const willPop = Boolean(history.state?.mjModal);
  close();
  if (!willPop) {
    then();
    return;
  }
  let done = false;
  const run = () => {
    if (done) return;
    done = true;
    window.removeEventListener("popstate", run);
    then();
  };
  window.addEventListener("popstate", run);
  window.setTimeout(run, 500);
}
