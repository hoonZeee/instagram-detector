 # Instagram 악성 댓글 탐지기 개발 로그

## 프로젝트 개요
인스타그램 인기 게시물에 달리는 스팸/악성 댓글(특히 공백·특수문자로 우회된 형태)을 자동 탐지하고 일괄 삭제하는 데스크탑 앱.

**핵심 설계 결정:**
- 브라우저 자동화 (Playwright): 앱이 비밀번호를 아예 모름, 보안 최우선
- Mac 우선 배포 (.app), Windows 확장성은 열어두되 추상화 최소화
- 탐지: 규칙 기반 기본 + 선택적 Claude API 연동

**기술 스택:**
- Python 3.11.9 (pyenv)
- Playwright 1.44 (Chromium 브라우저 자동화)
- CustomTkinter 5.2.2 (GUI)
- Anthropic SDK 0.28 (선택적 AI 탐지)
- PyInstaller 6.8 (패키징)

---

## Phase 1: 프로젝트 셋업 + 기반 구조

**날짜:** 2026-05-20  
**상태:** 완료 ✅

### 작업 내용
- `requirements.txt` 생성 및 패키지 설치
- 프로젝트 구조 설계 및 파일 생성
  - `main.py` — 진입점
  - `gui.py` — 메인 앱 윈도우, 뷰 전환 관리
  - `views/login_view.py` — 로그인 화면
  - `views/post_view.py` — 게시물 URL 입력 + 댓글 수집
  - `views/result_view.py` — 탐지 결과 + 삭제 확인 팝업
  - `browser.py` — Playwright 세션 관리 (보안: 쿠키만 메모리 보관)
  - `instagram.py` — 댓글 수집 + 삭제 (네트워크 인터셉트 방식)
  - `detector.py` — 스팸 탐지 엔진

### 이슈 및 해결
- **문제:** pyenv Python 3.11.9에 tkinter 미포함  
  **해결:** `brew install tcl-tk@8` 후 `pyenv install 3.11.9 --force` 로 Python 재빌드

- **문제:** `str.maketrans(str, "")` — 두 인자 길이 불일치 오류  
  **해결:** `_JAMO_MAP` 미사용 코드 제거, 대신 `re.sub(r"[ㄱ-ㅎㅏ-ㅣ]", "", t)` 로 직접 처리

- **문제:** "여제유추검스엑" 블랙리스트 미매칭  
  **해결:** 정규화 후 형태(`"여제유추"`)를 블랙리스트에 추가

### 검증 결과
```
탐지 테스트:
  [SPAM] 여 b 제 ㅇ 유 추 ㄹ 검 스엑  →  norm: 여제유추검스엑   ✅
  [OK]   안녕하세요 좋은 게시물이에요!  →  norm: 안녕하세요...    ✅
  [SPAM] 성 인 사 이 트 추 천          →  norm: 성인사이트추천   ✅
  [OK]   좋아요~                       →  norm: 좋아요           ✅
  [SPAM] 텔레그램 오픈방 초대           →  norm: 텔레그램...      ✅
  [SPAM] 조건만남 구함                  →  norm: 조건만남구함     ✅
GUI import OK ✅
```

---

## Phase 2 (예정): Playwright 로그인 플로우 테스트
- Chrome 열기 → 유저 로그인 → 세션 캡처 확인
- verify: 로그인 완료 감지 후 `BrowserContext` 반환
