"""시간 순으로 정렬되는 UUID(v7). 기본 키 인덱스가 뒤에만 쌓여 삽입이 빠르다."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (
        (ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76  # 버전 7
        | ((rand >> 62) & 0xFFF) << 64
        | 0b10 << 62  # RFC 9562 변형
        | (rand & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)
