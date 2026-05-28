"""
댓글 스팸 탐지 모듈

탐지 파이프라인:
  1. TextNormalizer   — 우회 표기(공백/낱자모/낱영문) 제거
  2. CommentClusterer — 정확한 중복(hash) + 유사 중복(Jaccard n-gram) 그룹화
  3. SpamClassifier   — 그룹 크기·블랙리스트 기반 판정
  4. detect()         — 위 세 단계를 묶는 공개 진입점

최종 판단은 UI(result_view)에서 유저에게 위임한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────

#: 반복이 이 횟수 이상이면 스팸으로 분류
REPEAT_THRESHOLD = 3

#: Jaccard 유사도가 이 값 이상이면 같은 그룹으로 묶음
SIMILARITY_THRESHOLD = 0.6

#: n-gram 크기 (문자 단위)
NGRAM_SIZE = 3

BLACKLIST: list[str] = [
    # 여성 유추 관련 우회 표기
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
    # 만남·유인
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


# ──────────────────────────────────────────────
# 결과 타입
# ──────────────────────────────────────────────

class SpamReason(str, Enum):
    BLACKLIST     = "blacklist"    # 블랙리스트 키워드 포함
    EXACT_REPEAT  = "exact"        # 완전히 동일한 텍스트 3회 이상
    SIMILAR_REPEAT = "similar"     # 유사한 텍스트 3회 이상


@dataclass
class CommentGroup:
    """유사하거나 동일한 댓글 묶음."""
    reason: SpamReason
    ids: list[str] = field(default_factory=list)
    sample_text: str = ""          # 대표 원본 텍스트 (UI 표시용)

    @property
    def is_spam(self) -> bool:
        return len(self.ids) >= REPEAT_THRESHOLD


@dataclass
class DetectionResult:
    """탐지 결과. spam_ids 외에 그룹 정보도 포함해 UI에서 상세 표시 가능."""
    spam_ids: set[str]
    groups: list[CommentGroup]     # 그룹별 정보 (UI에서 그룹 단위 표시용)


# ──────────────────────────────────────────────
# Step 1 — 정규화
# ──────────────────────────────────────────────

_STRIP_PATTERN = re.compile(
    r"[\s​‌‍﻿"   # 공백·제로폭 문자
    r".,!?~*_\-|/\\(){}\[\]<>@#$%^&+=`'\";:]+"
)


def _normalize(text: str) -> str:
    """
    우회 표기를 제거하고 순수 음절 문자열로 변환한다.

    예) "여 b 제 ㅇ 유 추 ㄹ 검 스엑" → "여제유추검스엑"
    """
    t = _STRIP_PATTERN.sub("", text.lower())
    # 낱 영문자 제거 (단어 경계 밖에 홀로 있는 영문 한 글자)
    t = re.sub(r"(?<![a-z])[a-z](?![a-z])", "", t)
    # 낱 자모 제거 (초성·중성만 단독으로 쓰인 경우)
    t = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]", "", t)
    return t


# ──────────────────────────────────────────────
# Step 2 — 그룹화
# ──────────────────────────────────────────────

def _ngrams(text: str, n: int = NGRAM_SIZE) -> frozenset[str]:
    """문자 단위 n-gram 집합 반환."""
    if len(text) < n:
        return frozenset([text]) if text else frozenset()
    return frozenset(text[i:i + n] for i in range(len(text) - n + 1))


def _jaccard(a: str, b: str) -> float:
    """두 문자열의 n-gram Jaccard 유사도 (0.0 ~ 1.0)."""
    s1, s2 = _ngrams(a), _ngrams(b)
    if not s1 and not s2:
        return 1.0
    union = len(s1 | s2)
    return len(s1 & s2) / union if union else 0.0


class CommentClusterer:
    """
    댓글을 정확한 중복(exact) + 유사 중복(fuzzy) 두 단계로 그룹화한다.

    알고리즘:
      1. 정규화된 텍스트를 hash map으로 묶어 exact 그룹 구성 — O(n)
      2. 각 exact 그룹의 대표 텍스트끼리 Jaccard 유사도 계산
         유사도 ≥ SIMILARITY_THRESHOLD 이면 병합 — O(g²), g = 고유 그룹 수
         댓글 수천 개라도 고유 텍스트 종류는 훨씬 적으므로 실용적으로 빠름
    """

    def cluster(
        self,
        comments: list[dict],
        normalized: dict[str, str],
    ) -> list[CommentGroup]:
        """
        comments: [{id, text, ...}, ...]
        normalized: {comment_id: normalized_text}
        반환: CommentGroup 리스트
        """
        exact_groups = self._exact_groups(comments, normalized)
        merged = self._fuzzy_merge(exact_groups)
        return merged

    # ── 내부 메서드 ──

    def _exact_groups(
        self,
        comments: list[dict],
        normalized: dict[str, str],
    ) -> dict[str, CommentGroup]:
        """정규화 텍스트가 완전히 같은 댓글끼리 묶는다."""
        groups: dict[str, CommentGroup] = {}
        for c in comments:
            norm = normalized[c["id"]]
            if norm not in groups:
                groups[norm] = CommentGroup(
                    reason=SpamReason.EXACT_REPEAT,
                    sample_text=c["text"],
                )
            groups[norm].ids.append(c["id"])
        return groups

    def _fuzzy_merge(
        self,
        exact_groups: dict[str, CommentGroup],
    ) -> list[CommentGroup]:
        """
        Jaccard 유사도가 높은 exact 그룹들을 하나의 SIMILAR_REPEAT 그룹으로 병합.
        Union-Find로 전이적 클러스터링.
        """
        keys = list(exact_groups.keys())
        parent = list(range(len(keys)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)

        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                # 이미 같은 그룹이면 스킵
                if find(i) == find(j):
                    continue
                if _jaccard(keys[i], keys[j]) >= SIMILARITY_THRESHOLD:
                    union(i, j)

        # 같은 루트끼리 묶어 최종 그룹 구성
        root_to_group: dict[int, CommentGroup] = {}
        for idx, key in enumerate(keys):
            root = find(idx)
            src = exact_groups[key]
            if root not in root_to_group:
                root_to_group[root] = CommentGroup(
                    reason=SpamReason.EXACT_REPEAT if len(exact_groups[keys[root]].ids) >= 1
                           else SpamReason.SIMILAR_REPEAT,
                    sample_text=src.sample_text,
                )
            grp = root_to_group[root]
            grp.ids.extend(src.ids)
            # 여러 exact 그룹이 합쳐지면 SIMILAR_REPEAT로 격상
            if root != idx:
                grp.reason = SpamReason.SIMILAR_REPEAT

        return list(root_to_group.values())


# ──────────────────────────────────────────────
# Step 3 — 판정
# ──────────────────────────────────────────────

class SpamClassifier:
    """
    그룹화된 결과와 블랙리스트를 이용해 스팸 ID 집합을 결정한다.
    판정 기준:
      - 그룹 크기 ≥ REPEAT_THRESHOLD → 스팸
      - 정규화 텍스트에 블랙리스트 키워드 포함 → 스팸
    최종 확인은 UI(result_view)에서 유저에게 위임한다.
    """

    def classify(
        self,
        comments: list[dict],
        normalized: dict[str, str],
        groups: list[CommentGroup],
    ) -> DetectionResult:
        spam_ids: set[str] = set()

        # 반복 기반 판정
        for group in groups:
            if group.is_spam:
                spam_ids.update(group.ids)

        # 블랙리스트 판정 — 이미 repeat 그룹에 없는 것만 개별 그룹으로 추가
        already_grouped = {cid for g in groups for cid in g.ids}
        for c in comments:
            norm = normalized[c["id"]]
            if any(kw in norm for kw in BLACKLIST):
                spam_ids.add(c["id"])
                if c["id"] not in already_grouped:
                    groups.append(CommentGroup(
                        reason=SpamReason.BLACKLIST,
                        ids=[c["id"]],
                        sample_text=c["text"],
                    ))

        return DetectionResult(spam_ids=spam_ids, groups=groups)


# ──────────────────────────────────────────────
# 공개 진입점
# ──────────────────────────────────────────────

_clusterer = CommentClusterer()
_classifier = SpamClassifier()


def detect(comments: list[dict]) -> DetectionResult:
    """
    댓글 목록을 받아 DetectionResult를 반환한다.

    사용 예)
        result = detect(comments)
        spam_ids = result.spam_ids          # 삭제 대상 ID 집합
        groups = result.groups              # UI 그룹 표시용
    """
    if not comments:
        return DetectionResult(spam_ids=set(), groups=[])

    # Step 1: 전체 정규화
    normalized = {c["id"]: _normalize(c["text"]) for c in comments}

    # Step 2: 그룹화
    groups = _clusterer.cluster(comments, normalized)

    # Step 3: 판정
    return _classifier.classify(comments, normalized, groups)


# 하위 호환 — 기존 코드에서 detect_spam() 으로 호출하는 곳이 있으면 그대로 동작
def detect_spam(comments: list[dict]) -> set[str]:
    return detect(comments).spam_ids
