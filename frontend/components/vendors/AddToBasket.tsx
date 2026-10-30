"use client";
import { useEffect, useState } from "react";
import type { Trade } from "@/lib/types";
import { TRADE_LABEL } from "@/lib/types";
import { readBasket, writeBasket } from "./basket";
import { eulReul } from "@/lib/format";

export function AddToBasket({ projectId, trade, vendorId, vendorName }: { projectId: string; trade: Trade; vendorId: string; vendorName: string }) {
  const [on, setOn] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { setOn(readBasket(projectId)[trade].includes(vendorId)); }, [projectId, trade, vendorId]);
  function toggle() {
    const b = readBasket(projectId);
    const has = b[trade].includes(vendorId);
    b[trade] = has ? b[trade].filter((x) => x !== vendorId) : [...b[trade], vendorId];
    writeBasket(projectId, b);
    setOn(!has);
    setMsg(`${eulReul(vendorName)} ${TRADE_LABEL[trade]} ${has ? "요청함에서 뺐어요" : "요청함에 담았어요"}`);
  }
  return (
    <>
      <button type="button" className={`mj-btn ${on ? "mj-btn-pri" : "mj-btn-sec"}`} aria-pressed={on} onClick={toggle}>{on ? `${TRADE_LABEL[trade]} 요청함에 담았어요` : `${TRADE_LABEL[trade]} 요청함에 담기`}</button>
      <p className="mj-sr" aria-live="polite">{msg}</p>
    </>
  );
}
