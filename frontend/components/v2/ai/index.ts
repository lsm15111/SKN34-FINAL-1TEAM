// ai 단계 함수를 F 표에 넣는다: AI 상담 · 에이전트 답 · 지식 검색 · 입구 관문 · 느낌 방 그림(첫 화면 room.ts)
import { register } from "../engine";
import { lookCredit, roomSvg } from "../home/room";
import { agentAnswer, askAboutMat, askAboutStyle, askClaude, askCompare, askPhotos, askReview, routeGate } from "./ask";
import { ragSearch } from "./rag";

register({ askClaude, askAboutStyle, askAboutMat, askCompare, askPhotos, askReview, agentAnswer, ragSearch, routeGate, roomSvg, lookCredit });
