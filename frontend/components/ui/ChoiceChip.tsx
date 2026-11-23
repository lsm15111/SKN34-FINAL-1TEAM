"use client";
// 고르기 칩(design-system 3.2 ChoiceChip · 9판 k-ch): 하나 고르기(라디오) · 여럿 고르기(체크). 40px · 14/600.
// 고름: 파랑 바탕 + 1.5px 파랑 테두리 + 파랑 글자(테두리 두께 · 글자로도 알려요). 준비 중: 꺼짐 + '준비 중' 배지. 제안: 주황.
// 진짜 input(radio · checkbox)을 숨겨 써서 화살표 키 · 폼 보내기 · 화면 읽기가 그대로 돼요.
// onSoon을 주면 준비 중 칩도 눌려서(aria-disabled) 부르는 쪽이 까닭을 보여요. 고름은 바뀌지 않아요(QA r6: 눌러도 반응이 없던 칩).
import { useId, type ReactNode } from "react";
import { Badge } from "./Badge";
import { Icon } from "./Icon";
import s from "./ChoiceChip.module.css";

export type ChipOption = { value: string; label: ReactNode; disabled?: boolean; /** 준비 중(꺼짐 + 배지) */ soon?: boolean; /** 제안(주황) */ proposed?: boolean };

type Single = { multiple?: false; value: string | null; onChange: (v: string) => void };
type Multi = { multiple: true; value: string[]; onChange: (v: string[]) => void };

export function ChoiceChips(props: (Single | Multi) & {
  /** 묶음 이름(fieldset legend). 화면에 보이는 질문이 있으면 hideLegend */
  legend: string;
  options: ChipOption[];
  name?: string;
  hideLegend?: boolean;
  /** 칸 아래 오류 한 줄 */
  error?: string | null;
  /** 준비 중 칩을 눌렀을 때 */
  onSoon?: (v: string) => void;
}) {
  const auto = useId();
  const name = props.name ?? auto;
  const picked = (v: string) => (props.multiple ? props.value.includes(v) : props.value === v);
  const pick = (v: string) => {
    if (props.multiple) props.onChange(props.value.includes(v) ? props.value.filter((x) => x !== v) : [...props.value, v]);
    else props.onChange(v);
  };
  return (
    <fieldset className={s.set} aria-describedby={props.error ? `${name}-err` : undefined}>
      <legend className={props.hideLegend ? "mj-sr" : s.legend}>{props.legend}</legend>
      <div className={s.chips}>
        {props.options.map((o) => {
          const off = o.disabled || o.soon;
          const tap = !!(o.soon && !o.disabled && props.onSoon);
          const on = picked(o.value);
          return (
            <label key={o.value} className={[s.chip, on ? s.on : null, off ? s.off : null, o.proposed ? s.prop : null].filter(Boolean).join(" ")}>
              <input
                type={props.multiple ? "checkbox" : "radio"}
                name={name}
                value={o.value}
                checked={on}
                disabled={off && !tap}
                aria-disabled={tap || undefined}
                onChange={() => (tap ? props.onSoon?.(o.value) : pick(o.value))}
                className={s.input}
              />
              {on && props.multiple ? <Icon name="check" size={14} strokeWidth={2.6} /> : null}
              <span>{o.label}</span>
              {o.soon ? <Badge tone="mute" className={s.soon}>준비 중</Badge> : null}
            </label>
          );
        })}
      </div>
      {props.error ? <p id={`${name}-err`} className={s.error}><Icon name="error" size={16} />{props.error}</p> : null}
    </fieldset>
  );
}
