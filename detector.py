import re
from collections import Counter

# Korean/English mixed obfuscation normalizer
_STRIP = re.compile(r"[\s​‌‍﻿.,!?~*_\-|/\\(){}\[\]<>@#$%^&+=`'\";:]+")

BLACKLIST = [
    # 우회 표기 정규화 후 매칭되는 패턴 (예: "여 b 제 ㅇ 유 추 ㄹ 검 스엑" → "여제유추검스엑")
    "여제유추",
    "여자제유추출",
    # 성인 콘텐츠
    "성인사이트",
    "성인동영상",
    "성인검색",
    "성인광고",
    "야동",
    "야한영상",
    "섹스",
    "섹영상",
    "av배우",
    "무료야동",
    "야동추천",
    "불법영상",
    "몰카",
    # 만남/유인
    "조건만남",
    "즉석만남",
    "빠른만남",
    "원나잇",
    "만남어플",
    "헌팅어플",
    # 채널 유도
    "텔레그램",
    "단톡방",
    "카카오오픈방",
    "실제후기",
]


def _normalize(text: str) -> str:
    """Remove obfuscation separators and collapse to pure syllable string."""
    t = _STRIP.sub("", text.lower())
    # Remove lone single English letters used as separators (e.g. 여 b 제 ㅇ 유)
    t = re.sub(r"(?<![a-z])[a-z](?![a-z])", "", t)
    # Remove lone jamo (e.g. ㅇ, ㄹ used as separators between syllables)
    t = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]", "", t)
    return t


def detect_spam(comments: list[dict]) -> set[str]:
    """
    Returns a set of comment IDs classified as spam.
    Uses two signals:
      1. Keyword blacklist match on normalized text
      2. Repetition: same normalized text posted 3+ times across the comment list
    """
    spam_ids = set()
    norm_counter = Counter()

    normalized = {}
    for c in comments:
        n = _normalize(c["text"])
        normalized[c["id"]] = n
        norm_counter[n] += 1

    for c in comments:
        n = normalized[c["id"]]
        # Signal 1: blacklist
        for kw in BLACKLIST:
            if kw in n:
                spam_ids.add(c["id"])
                break
        # Signal 2: repetition (3+ identical normalized texts)
        if norm_counter[n] >= 3:
            spam_ids.add(c["id"])

    return spam_ids
