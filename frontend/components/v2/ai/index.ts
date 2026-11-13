// ai 단계 함수를 F 표에 넣는다: AI 상담 · 에이전트 답 · 느낌 방 그림(첫 화면 room.ts). 지식 검색은 서버가 한다
import { register } from "../engine";
import { roomSvg } from "../home/room";
import { agentAnswer, askAboutMat, askAboutStyle, askClaude, askCompare, askPhotos, askReview } from "./ask";

register({ askClaude, askAboutStyle, askAboutMat, askCompare, askPhotos, askReview, agentAnswer, roomSvg });
