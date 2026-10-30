import { SiteHeader } from "@/components/site/SiteHeader";
import { Wizard } from "@/components/start/Wizard";

export const metadata = { title: "견적 받기" };

// 링크로 바로 들어온 경우를 위한 화면. 보통은 헤더의 '견적 받기' 창으로 연다.
export default function StartPage() {
  return (
    <>
      <SiteHeader />
      <Wizard mode="page" />
    </>
  );
}
