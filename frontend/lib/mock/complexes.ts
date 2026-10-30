// 예시 단지 (가상). 견적 받기 질문 흐름이 브라우저에서 바로 쓰도록 따로 둔다.
import type { Complex } from "../types";

export const COMPLEXES: Complex[] = [
  { id: "c1", name: "늘봄마을 2단지", sido: "서울", sgg: "마포구", dong: "성산동", road: "성산로 120 (가상)", households: 1204, builtYear: 2009,
    types: [
      { id: "c1-24", py: 24, supply: 79.9, jeon: 59.96, households: 384, rooms: 2 },
      { id: "c1-34", py: 34, supply: 113.3, jeon: 84.97, households: 612, rooms: 3 },
      { id: "c1-41", py: 41, supply: 135.9, jeon: 101.9, households: 208, rooms: 4 },
    ] },
  { id: "c2", name: "늘봄마을 5단지", sido: "서울", sgg: "마포구", dong: "성산동", road: "성산로 150 (가상)", households: 868, builtYear: 2011,
    types: [
      { id: "c2-25", py: 25, supply: 82.6, jeon: 59.98, households: 412, rooms: 2 },
      { id: "c2-33", py: 33, supply: 109.1, jeon: 84.93, households: 456, rooms: 3 },
    ] },
  { id: "c3", name: "한빛숲 1단지", sido: "서울", sgg: "마포구", dong: "상암동", road: "월드컵북로 300 (가상)", households: 640, builtYear: 2016,
    types: [
      { id: "c3-32", py: 32, supply: 105.8, jeon: 84.96, households: 380, rooms: 3 },
      { id: "c3-40", py: 40, supply: 132.2, jeon: 101.95, households: 260, rooms: 4 },
    ] },
];
