"""
댓글 스팸 탐지 모듈

탐지 철학:
  - 정상 댓글을 잘못 잡지 않는 것이 최우선. 애매하면 LOW(검토 필요)로 격리한다.
  - 단일 규칙이 아니라 여러 신호를 '점수'로 합산해 확신도(HIGH/MEDIUM/LOW)를 매긴다.
    HIGH/MEDIUM → 기본 선택(삭제 후보), LOW → 기본 선택 해제(유저 검토용).

신호(점수 가중치):
  - 반복            : 동일/유사 댓글이 3회+(강), 2회(중)
  - 우회표기(깨짐)  : 유니코드 동형문자(gⓞⓞgⓛe, ġ૦૦ġĿ) 비율이 높을수록
  - 캠페인 키워드   : 확정 스팸들에서 학습한 '특이한' 키워드와 겹침
  - 군집 크기       : 같은 캠페인 키워드를 공유하는 댓글이 많을수록(군집 클수록)
  - 호객어 보정     : 구글/검색 등은 단독으론 무력하지만, 캠페인 키워드와 함께면 +

핵심 안전장치:
  - 정규화 후 5자 미만(ㅋㅋㅋ 등)은 제외
  - 구글/검색 같은 호객어는 절대 단독 트리거가 되지 않음(캠페인 키워드 동반 필수)
  - 캠페인 키워드는 서로 다른 2개 이상의 확정 스팸에 공통으로 나온 것만 학습
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


# ──────────────────────────────────────────────
# 상수 / 튜닝 파라미터
# ──────────────────────────────────────────────

#: 동일/유사 반복이 이 횟수 이상이면 '강한 반복'
REPEAT_THRESHOLD = 3

#: Jaccard 유사도가 이 값 이상이면 같은 반복 그룹으로 묶음
SIMILARITY_THRESHOLD = 0.6

#: 문자 단위 n-gram 크기 (클러스터링용)
NGRAM_SIZE = 3

#: 정규화 후 이 글자 수 미만이면 탐지 대상에서 제외 (ㅋㅋㅋ, ㅎㅎ 등)
MIN_NORM_LEN = 5

#: 우회표기(homoglyph) 강한 신호 기준 — 의심문자 2개 이상 또는 비율 0.3 이상
OBF_STRONG_COUNT = 2
OBF_STRONG_RATIO = 0.3
#: 우회표기 약한 신호 기준
OBF_MILD_COUNT = 1
OBF_MILD_RATIO = 0.15

#: 점수 → 확신도 임계값
SCORE_HIGH = 5
SCORE_MEDIUM = 3
SCORE_LOW = 2


#: 명백한 성인/스팸 키워드 — 포함되면 강한 점수(단건이어도 HIGH)
BLACKLIST: list[str] = [
    "여제유추", "여자제유추출",
    "성인사이트", "성인동영상", "성인검색", "성인광고",
    "야동", "야한영상", "섹스", "섹영상", "av배우", "무료야동", "야동추천",
    "불법영상", "몰카",
    "조건만남", "즉석만남", "빠른만남", "원나잇", "만남어플", "헌팅어플",
    "텔레그램", "단톡방", "카카오오픈방", "실제후기",
]

#: 호객어 — 검색 유도 등. 단독으로는 절대 탐지 트리거가 되지 않지만,
#: 캠페인 키워드가 함께 있으면 보정 점수를 준다.
LURE_KEYWORDS: list[str] = [
    "구글", "구굴", "google", "googl", "검색", "search", "서치",
    "유튜브", "youtube", "네이버", "naver", "트위터", "텔레", "telegram",
    "링크", "접속", "클릭", "디엠",
]

#: 캠페인 키워드 학습에서 제외할 호객·일반 단어.
#: (구글/검색/있음 등 흔한 표현이 캠페인 키워드로 둔갑하는 것을 막는다)
CAMPAIGN_STOPWORDS: list[str] = LURE_KEYWORDS + [
    "영상", "동영상", "사진", "나옴",  "올려", "진거", "그거",
    "후기"
]


# ──────────────────────────────────────────────
# 결과 타입
# ──────────────────────────────────────────────

class Confidence(str, Enum):
    """탐지 확신도. UI에서 탭으로 분류된다."""
    HIGH   = "high"     # 매우 위험 — 기본 선택됨
    MEDIUM = "medium"   # 중간 위험 — 기본 선택됨
    LOW    = "low"      # 애매함 — 기본 선택 해제(검토 필요)


class SpamReason(str, Enum):
    BLACKLIST      = "blacklist"   # 블랙리스트 키워드 포함
    EXACT_REPEAT   = "exact"       # 완전히 동일한 텍스트 반복
    SIMILAR_REPEAT = "similar"     # 유사한 텍스트 반복
    CAMPAIGN       = "campaign"    # 캠페인 키워드 일치(단건 추적)
    OBFUSCATED     = "obfuscated"  # 우회표기(한글 깨짐) 단건


@dataclass
class CommentGroup:
    """유사하거나 동일한 댓글 묶음(또는 단건)."""
    reason: SpamReason
    ids: list[str] = field(default_factory=list)
    sample_text: str = ""                 # 대표 원본 텍스트 (UI 표시용)
    confidence: Confidence | None = None  # 확신도 (None이면 미판정)
    obfuscated: bool = False              # 우회표기(한글 깨짐) 강하게 감지됨

    @property
    def is_spam(self) -> bool:
        return self.confidence in (Confidence.HIGH, Confidence.MEDIUM)


@dataclass
class DetectionResult:
    """탐지 결과."""
    spam_ids: set[str]             # 기본 선택(HIGH+MEDIUM) 대상 ID
    groups: list[CommentGroup]     # 플래그된 그룹 전체(LOW 포함), UI 표시용


# ──────────────────────────────────────────────
# Step 0 — 정규화 & 우회표기 점수
# ──────────────────────────────────────────────

_STRIP_PATTERN = re.compile(
    r"[\s​‌‍﻿"   # 공백·제로폭 문자
    r".,!?~*_\-|/\\(){}\[\]<>@#$%^&+=`'\";:]+"
)
#: 단독 한글 자모(호환/조합 모두) — 낱자모 제거용
_LONE_JAMO = re.compile(r"[ᄀ-ᇿ㄰-㆏ꥠ-꥿ힰ-퟿]")


def _fold_homoglyphs(text: str) -> str:
    """
    유니코드 동형 문자를 표준 형태로 접는다. ⓞ→o, ġ→g, 전각→반각 등.
    NFKD로 분해해 결합 문자(악센트)를 떼어낸 뒤, NFC로 한글 음절을 다시 합친다.
    (NFKD만 쓰면 한글이 자모로 쪼개져 'ㅇㅣㅆㅇㅡㅁ' 형태가 되므로 재조합 필수)
    """
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", no_marks)


def _normalize(text: str) -> str:
    """
    우회 표기를 제거하고 순수 음절 문자열로 변환한다.

    예) "여 b 제 ㅇ 유 추 ㄹ 검 스엑" → "여제유추검스엑"
        "gⓞⓞgⓛe 검 색"            → "검색"  (낱 영문/기호 제거)
    """
    t = _fold_homoglyphs(text).lower()
    t = _STRIP_PATTERN.sub("", t)
    # 낱 영문자 제거 (단어 경계 밖에 홀로 있는 영문 한 글자)
    t = re.sub(r"(?<![a-z])[a-z](?![a-z])", "", t)
    # 낱 자모 제거 (단독으로 쓰인 자모: ㅋㅋ, ㄹㅈㄷ)
    t = _LONE_JAMO.sub("", t)
    return t


def _is_suspicious_char(ch: str) -> bool:
    """
    정상 한국어 댓글에 쓰이지 않는 '깨진'(동형/외래 스크립트) 문자인지 판정.
    동그라미 문자(ⓞ), 전각, 악센트 라틴(ġ), 낯선 숫자(૦) 등 → True.
    한글/기본 라틴/한자/숫자 → False.
    """
    o = ord(ch)
    if 0x2460 <= o <= 0x24FF:      # 원 문자(Enclosed Alphanumerics)
        return True
    if 0x1F100 <= o <= 0x1F1FF:    # Enclosed Alphanumeric Supplement
        return True
    if 0xFF00 <= o <= 0xFFEF:      # 전각/반각 폼
        return True
    cat = unicodedata.category(ch)
    if cat[0] not in ("L", "N"):   # 글자/숫자만 평가
        return False
    if 0xAC00 <= o <= 0xD7A3:      # 한글 음절
        return False
    if 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:  # 한글 자모
        return False
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:  # 한자(CJK)
        return False
    if ch.isascii():               # 기본 영문/숫자
        return False
    return True


def _obf_info(text: str) -> tuple[float, int]:
    """우회표기 점수. (의심문자 비율, 의심문자 개수)."""
    letters = suspicious = 0
    for ch in text:
        if unicodedata.category(ch)[0] not in ("L", "N"):
            continue
        letters += 1
        if _is_suspicious_char(ch):
            suspicious += 1
    ratio = suspicious / letters if letters else 0.0
    return ratio, suspicious


def _is_strong_obf(info: tuple[float, int]) -> bool:
    ratio, count = info
    return count >= OBF_STRONG_COUNT or ratio >= OBF_STRONG_RATIO


def _is_mild_obf(info: tuple[float, int]) -> bool:
    ratio, count = info
    return count >= OBF_MILD_COUNT or ratio >= OBF_MILD_RATIO


def _has_lure(norm: str) -> bool:
    return any(kw in norm for kw in LURE_KEYWORDS)


# ──────────────────────────────────────────────
# Step 1 — 그룹화 (클러스터링)
# ──────────────────────────────────────────────

def _ngrams(text: str, n: int = NGRAM_SIZE) -> frozenset[str]:
    if len(text) < n:
        return frozenset([text]) if text else frozenset()
    return frozenset(text[i:i + n] for i in range(len(text) - n + 1))


def _jaccard(a: str, b: str) -> float:
    s1, s2 = _ngrams(a), _ngrams(b)
    if not s1 and not s2:
        return 1.0
    union = len(s1 | s2)
    return len(s1 & s2) / union if union else 0.0


class CommentClusterer:
    """
    댓글을 정확한 중복(exact) + 유사 중복(fuzzy)으로 그룹화한다.
    모든 댓글은 하나의 그룹에 속한다(고유하면 크기 1 그룹).
    """

    def cluster(self, comments: list[dict], normalized: dict[str, str]) -> list[CommentGroup]:
        exact_groups = self._exact_groups(comments, normalized)
        return self._fuzzy_merge(exact_groups)

    def _exact_groups(self, comments, normalized) -> dict[str, CommentGroup]:
        groups: dict[str, CommentGroup] = {}
        for c in comments:
            norm = normalized[c["id"]]
            if norm not in groups:
                groups[norm] = CommentGroup(
                    reason=SpamReason.EXACT_REPEAT, sample_text=c["text"],
                )
            groups[norm].ids.append(c["id"])
        return groups

    def _fuzzy_merge(self, exact_groups: dict[str, CommentGroup]) -> list[CommentGroup]:
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
                if find(i) == find(j):
                    continue
                if _jaccard(keys[i], keys[j]) >= SIMILARITY_THRESHOLD:
                    union(i, j)

        root_to_group: dict[int, CommentGroup] = {}
        for idx, key in enumerate(keys):
            root = find(idx)
            src = exact_groups[key]
            if root not in root_to_group:
                root_to_group[root] = CommentGroup(
                    reason=SpamReason.EXACT_REPEAT, sample_text=src.sample_text,
                )
            grp = root_to_group[root]
            grp.ids.extend(src.ids)
            if root != idx:
                grp.reason = SpamReason.SIMILAR_REPEAT

        return list(root_to_group.values())


# ──────────────────────────────────────────────
# Step 2 — 캠페인 키워드 학습
# ──────────────────────────────────────────────

def _campaign_grams_of(text: str) -> set[str]:
    """캠페인 키워드 후보: 3·4글자 n-gram."""
    out: set[str] = set()
    for n in (3, 4):
        if len(text) >= n:
            for i in range(len(text) - n + 1):
                out.add(text[i:i + n])
    return out


def _has_stopword(gram: str) -> bool:
    return any(stop in gram for stop in CAMPAIGN_STOPWORDS)


def _build_campaign_set(seed_ids: list[str], normalized: dict[str, str]) -> set[str]:
    """
    '확정된 의심 댓글(seed)'에서 캠페인 고유 키워드만 학습한다.

    알바들은 일부러 문장을 조금씩 변형해 클러스터를 쪼갠다. 그래서 그룹 단위가
    아니라 '개별 의심 댓글' 단위로 n-gram을 모으고, 서로 다른 2개 이상의 seed에
    공통으로 나오는 n-gram만 캠페인 키워드로 채택한다(교차 검증).
    호객·일반 단어는 스탑리스트로 제외한다.
    """
    df: dict[str, int] = defaultdict(int)
    for cid in seed_ids:
        for gram in _campaign_grams_of(normalized.get(cid, "")):
            df[gram] += 1
    return {
        gram for gram, count in df.items()
        if count >= 2 and not _has_stopword(gram)
    }


# ──────────────────────────────────────────────
# Step 3 — 점수화 & 확신도 판정
# ──────────────────────────────────────────────

def _seed_score(cid, size, obf, bl) -> int:
    """캠페인 키워드 학습 대상(seed)을 고르기 위한 1차 점수 (반복·우회·블랙리스트)."""
    s = 0
    if bl[cid]:
        s += 6
    n = size[cid]
    if n >= REPEAT_THRESHOLD:
        s += 4
    elif n == 2:
        s += 2
    if _is_strong_obf(obf[cid]):
        s += 3
    elif _is_mild_obf(obf[cid]):
        s += 1
    return s


def _score_to_confidence(score: int) -> Confidence | None:
    if score >= SCORE_HIGH:
        return Confidence.HIGH
    if score >= SCORE_MEDIUM:
        return Confidence.MEDIUM
    if score >= SCORE_LOW:
        return Confidence.LOW
    return None


def _pick_reason(group: CommentGroup, has_bl: bool, n: int, overlap: int) -> SpamReason:
    if has_bl:
        return SpamReason.BLACKLIST
    if n >= 2:
        return group.reason            # 클러스터에서 정한 EXACT/SIMILAR
    if overlap >= 1:
        return SpamReason.CAMPAIGN
    return SpamReason.OBFUSCATED        # 단건인데 우회표기로만 잡힌 경우


# ──────────────────────────────────────────────
# 공개 진입점
# ──────────────────────────────────────────────

_clusterer = CommentClusterer()


def detect(comments: list[dict]) -> DetectionResult:
    """
    댓글 목록을 받아 DetectionResult를 반환한다.

        result = detect(comments)
        result.spam_ids   # HIGH+MEDIUM (기본 선택) ID
        result.groups     # 플래그된 그룹 전체(LOW 포함), 각 그룹에 confidence
    """
    if not comments:
        return DetectionResult(spam_ids=set(), groups=[])

    # Step 0: 정규화 + 우회표기 + 블랙리스트
    normalized = {c["id"]: _normalize(c["text"]) for c in comments}
    obf = {c["id"]: _obf_info(c["text"]) for c in comments}
    bl = {c["id"]: any(kw in normalized[c["id"]] for kw in BLACKLIST) for c in comments}

    # Step 1: 클러스터링 (모든 댓글이 어떤 그룹엔가 속함)
    clusters = _clusterer.cluster(comments, normalized)
    size = {cid: len(g.ids) for g in clusters for cid in g.ids}

    # Step 2: seed 선정 → 캠페인 키워드 학습
    seeds = [
        cid for cid in normalized
        if len(normalized[cid]) >= MIN_NORM_LEN
        and _seed_score(cid, size, obf, bl) >= SCORE_MEDIUM
    ]
    campaign = _build_campaign_set(seeds, normalized) if len(seeds) >= 2 else set()

    overlap = {
        cid: len(_campaign_grams_of(normalized[cid]) & campaign) if campaign else 0
        for cid in normalized
    }
    # 군집 크기 신호: 캠페인 키워드를 2개+ 공유하는 댓글이 REPEAT_THRESHOLD 이상이면
    # "확정된 캠페인" — 구성원에게 가중치를 더 준다.
    cohort_confirmed = sum(1 for v in overlap.values() if v >= 2) >= REPEAT_THRESHOLD

    # Step 3: 그룹별 점수 합산 → 확신도
    flagged: list[CommentGroup] = []
    spam_ids: set[str] = set()

    for g in clusters:
        ids = g.ids
        n = len(ids)
        has_bl = any(bl[i] for i in ids)

        # 너무 짧은 댓글 제외 (블랙리스트는 예외)
        if max(len(normalized[i]) for i in ids) < MIN_NORM_LEN and not has_bl:
            continue

        strong = any(_is_strong_obf(obf[i]) for i in ids)
        mild = any(_is_mild_obf(obf[i]) for i in ids)
        ov = max((overlap[i] for i in ids), default=0)
        lure = any(_has_lure(normalized[i]) for i in ids)

        score = 0
        if has_bl:
            score += 6
        if n >= REPEAT_THRESHOLD:
            score += 4
        elif n == 2:
            score += 2
        if strong:
            score += 3
        elif mild:
            score += 1
        if ov >= 2:
            score += 2
        elif ov == 1:
            score += 1
        if lure and ov >= 1:            # 호객어는 캠페인 키워드 동반 시에만 가점
            score += 1
        if ov >= 2 and cohort_confirmed:  # 큰 캠페인 군집 → 가중
            score += 2

        conf = _score_to_confidence(score)
        if conf is None:
            continue

        g.confidence = conf
        g.obfuscated = strong
        g.reason = _pick_reason(g, has_bl, n, ov)
        flagged.append(g)
        if conf in (Confidence.HIGH, Confidence.MEDIUM):
            spam_ids.update(ids)

    return DetectionResult(spam_ids=spam_ids, groups=flagged)


#: 키워드 검색에서 '유사 추천'으로 묶을 Jaccard 임계값
SEARCH_SIMILAR_THRESHOLD = 0.45


def search_comments(
    comments: list[dict],
    keyword: str,
    similar_threshold: float = SEARCH_SIMILAR_THRESHOLD,
) -> tuple[list[CommentGroup], list[CommentGroup]]:
    """
    이미 수집된 댓글에서 키워드로 직접 검색한다(API 재호출 없음).

    반환: (정확히 포함된 그룹들, 유사 추천 그룹들)
      - 정확: 정규화 텍스트에 키워드가 포함된 댓글 (공백/우회표기 무시하고 매칭)
      - 유사: 정확 매칭 댓글과 Jaccard 유사도가 높은(변형으로 추정되는) 댓글
    각 결과는 동일/유사끼리 묶여 CommentGroup 리스트로 반환된다.
    """
    kw = _normalize(keyword)
    if not kw:
        return [], []

    normalized = {c["id"]: _normalize(c["text"]) for c in comments}

    exact_ids = {cid for cid, norm in normalized.items() if kw in norm}
    exact_norms = [normalized[cid] for cid in exact_ids]

    similar_ids: set[str] = set()
    for cid, norm in normalized.items():
        if cid in exact_ids or not norm:
            continue
        if any(_jaccard(norm, en) >= similar_threshold for en in exact_norms):
            similar_ids.add(cid)

    exact_comments = [c for c in comments if c["id"] in exact_ids]
    similar_comments = [c for c in comments if c["id"] in similar_ids]

    exact_groups = _clusterer.cluster(exact_comments, normalized) if exact_comments else []
    similar_groups = _clusterer.cluster(similar_comments, normalized) if similar_comments else []
    return exact_groups, similar_groups


# 하위 호환
def detect_spam(comments: list[dict]) -> set[str]:
    return detect(comments).spam_ids
