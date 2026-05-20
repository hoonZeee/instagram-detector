# 개발 히스토리 — Instagram 악성 댓글 탐지기

> 작업 기간: 2026년 5월  
> 개발자: Jihoon + Claude

---

## 프로젝트 개요

인스타그램에서 "여 b 제 ㅇ 유 추 ㄹ 검 스엑" 같이 공백과 낱자(자모/영문)를 섞어 필터를 우회하는 스팸 댓글을 탐지하고 일괄 삭제하는 로컬 데스크탑 앱.

**핵심 요구사항**
- 아이디/비밀번호를 앱이 절대 저장하거나 열람하지 않는다 (보안 최우선)
- 로컬에서만 실행 (서버 없음)
- GUI 앱 (스크립트 아님)
- Mac 우선 배포

---

## 기술 스택 선택 이유

| 기술 | 선택 이유 |
|---|---|
| **Python 3.11** | Playwright, CustomTkinter, PyInstaller 모두 Python 생태계. 레퍼런스가 가장 풍부. |
| **Playwright** | 실제 Chrome 브라우저를 띄워서 Instagram에 사람처럼 로그인. 앱이 비밀번호를 절대 안 봄. |
| **CustomTkinter** | Python GUI 중 다크모드 지원이 가장 깔끔. tkinter 기반이라 macOS 패키징 호환. |
| **PyInstaller** | Python 앱을 `.app`으로 패키징. Mac 배포 표준. |
| **규칙 기반 탐지 (기본)** | 서버 불필요, 오프라인 동작. 원하면 Claude API 키 입력해서 AI 탐지 추가 가능. |

---

## 단계별 작업 기록

---

### Phase 1: 프로젝트 셋업

**한 것:**
- `pyenv`로 Python 3.11.9 설정
- `requirements.txt` 작성: playwright, customtkinter, anthropic, pyinstaller
- 기본 파일 구조 생성: `main.py`, `gui.py`, `browser.py`, `instagram.py`, `detector.py`

**문제: tkinter가 없음**

pyenv로 설치한 Python에는 tkinter가 기본 포함 안 됨. CustomTkinter가 tkinter 기반이라 실행 자체가 불가.

```
ModuleNotFoundError: No module named '_tkinter'
```

**해결:**
```bash
brew install tcl-tk@8
# pyenv install 시 configure 옵션에 tcl-tk 경로 명시
PYTHON_CONFIGURE_OPTS="..." pyenv install 3.11.9 --force
```

---

### Phase 2: 로그인 구현

**목표:** 앱이 비밀번호를 안 보면서 Instagram 로그인 세션 유지

**방식:** `launch_persistent_context`로 실제 Chrome 프로필을 `~/.instagram_detector/browser_profile/`에 저장. 한 번 로그인하면 다음 실행부터 자동 세션 복원.

**문제 1: 로그인 감지가 틀렸음**

처음엔 URL이 `/accounts/login`이 아니면 로그인된 걸로 판단했는데, Instagram이 2023년부터 로그인/비로그인 상태 모두 같은 URL(`/`)로 서비스함. 즉 URL만 보면 로그인 여부를 알 수 없음.

**해결:** `sessionid` 쿠키 존재 여부로 판단하는 `_has_valid_session()` 함수 추가.

```python
def _has_valid_session(context) -> bool:
    cookies = context.cookies(["https://www.instagram.com"])
    return any(c["name"] == "sessionid" and c["value"] for c in cookies)
```

**문제 2: `auth_platform` URL에서 로그인 완료로 잘못 판단**

2단계 인증 중간 단계 URL인 `auth_platform`이 `PENDING_PATTERNS`에 없어서 아직 인증 중인데 로그인 완료로 처리됨.

**해결:** `PENDING_PATTERNS` 튜플에 `"auth_platform"` 추가.

---

### Phase 3: 댓글 수집 구현

**목표:** 게시물의 댓글 전체를 가져오기

**처음 시도: Instagram Graph API**

Facebook Developer 계정 + 앱 심사 + `instagram_manage_comments` 권한 필요. 개인 사용 목적으로 이 과정을 거치는 건 현실적으로 불가능. **포기.**

**채택한 방식: Instagram 비공개 웹 API (`/api/v1/media/{media_id}/comments/`)**

Instagram 웹 앱이 내부적으로 사용하는 API. `page.evaluate(fetch())`로 브라우저 컨텍스트에서 호출하면 쿠키가 자동 포함되어 인증 통과.

```javascript
fetch('/api/v1/media/{media_id}/comments/?can_support_threading=true', {
    headers: {
        'x-ig-app-id': '936619743392459',
        'x-csrftoken': csrf,
        'x-requested-with': 'XMLHttpRequest',
    },
    credentials: 'include',
})
```

**문제 1: media_id를 잘못 추출함**

댓글 API는 `media_id` (게시물 고유 번호, 19자리)가 필요한데, 페이지 JSON에서 `"pk"` 값을 추출할 때 사용자 ID (10자리)를 잘못 가져옴.

```
# 틀린 예
media_id = 7068899162  # 사용자 ID
# 올바른 예
media_id = 3901223700674880712  # 게시물 ID (19자리)
```

**해결:** 정규식에 `\d{15,}` 조건 추가해서 15자리 미만은 무시.

```python
m1 = text.match(/"media_id":"(\d{15,})"/)
```

**문제 2: `Expecting value: line 1 column 1 (char 0)` 오류**

API 응답이 JSON이 아니라 빈 문자열 또는 HTML. media_id가 틀렸을 때 Instagram이 JSON 대신 HTML 에러 페이지를 반환한 것. media_id 수정 후 해결됨.

---

### Phase 4: Playwright 스레드 안전성 문제

**문제:** GUI(tkinter)는 메인 스레드, Playwright는 별도 스레드에서 호출하면 크래시.

```
Error: cannot switch to a different thread (which happens to have exited)
```

Playwright의 sync API는 생성한 스레드에서만 사용 가능. 여러 뷰(로그인, 게시물, 결과)에서 각자 스레딩을 하면 Playwright가 서로 다른 스레드에서 호출되어 충돌.

**해결: 전용 Playwright 워커 스레드 (`playwright_worker.py`)**

단 하나의 전용 데몬 스레드를 만들어 모든 Playwright 작업을 그 스레드에서만 실행. 다른 스레드는 큐를 통해 작업을 제출하고 결과를 기다림.

```python
class _Worker:
    def _run(self):  # 단 하나의 Playwright 전용 스레드
        while True:
            fn, event, box = self._q.get()
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc
            finally:
                event.set()

def pw_run(fn):
    return _worker.submit(fn)
```

모든 Playwright 호출을 `pw_run(lambda: ...)` 으로 감싸서 해결.

---

### Phase 5: 스팸 탐지 구현

**목표:** "여 b 제 ㅇ 유 추 ㄹ 검 스엑" 같은 우회 스팸 탐지

**핵심 아이디어: 텍스트 정규화 후 블랙리스트 매칭**

스팸 발신자들이 필터를 피하려고 공백, 낱영문자, 낱자모를 섞어놓기 때문에 이것들을 모두 제거하면 원래 단어가 드러남.

```python
def _normalize(text: str) -> str:
    t = _STRIP.sub("", text.lower())          # 공백, 특수문자 제거
    t = re.sub(r"(?<![a-z])[a-z](?![a-z])", "", t)  # 낱 영문자 제거 ("b", "a" 등)
    t = re.sub(r"[ㄱ-ㅎㅏ-ㅣ]", "", t)          # 낱 자모 제거 ("ㅇ", "ㄹ" 등)
    return t

# 예시
"여 b 제 ㅇ 유 추 ㄹ 검 스엑" → 정규화 → "여제유추검스엑" → 블랙리스트 "여제유추" 매칭 → 스팸
```

**문제: `str.maketrans(str, "")` ValueError**

초기 구현에서 `_JAMO_MAP`이라는 불필요한 변수를 만들고 `str.maketrans`를 잘못 호출함. 제거하고 `re.sub`으로 통일.

**탐지 신호 두 가지:**
1. 정규화된 텍스트에 블랙리스트 키워드 포함
2. 동일한 정규화 텍스트가 3개 이상 반복 (봇 도배 탐지)

---

### Phase 6: 댓글 삭제 — 가장 긴 삽질

#### 시도 1: 비공개 API 직접 호출 (`/api/v1/media/{id}/comment/{cid}/delete/`)

댓글 수집과 동일한 방식으로 POST 요청. HTML이 반환됨.

```
status=200 html=True body='<!DOCTYPE html>...'
```

**실패 원인:** 엔드포인트 URL이 틀렸음. 하지만 당시엔 이 사실을 몰랐고, 헤더 문제라고 생각했음.

#### 시도 2: instagrapi 라이브러리

Python Instagram 비공개 API 클라이언트. `login_by_sessionid()`로 기존 세션을 재활용하려 함.

```
467 Client Error - for url: http://instagram/api/v1/users/.../info/
```

**실패 원인:** instagrapi는 Android 모바일 앱 헤더를 사용하는데, 우리 세션은 Chrome 웹 브라우저 세션. Instagram이 헤더 불일치(브라우저 쿠키 + 모바일 API 헤더)를 감지하고 467(인증 실패) 반환.

#### 시도 3: UI 자동화 (Playwright DOM 클릭)

API가 막혔으니 실제 웹 UI를 자동으로 클릭해서 삭제. 댓글 타임스탬프 링크(`a[href*="/c/{comment_id}/"]`)를 찾고, 호버해서 ⋯ 버튼 클릭, 삭제 메뉴 클릭.

```
[DELETE DEBUG] comment links found: []
```

**실패 원인 1: Page Visibility API**

`context.new_page()`로 새 탭을 열면 백그라운드 탭으로 열림. Instagram이 `document.hidden === true`를 감지하고 댓글 렌더링을 하지 않음. `bring_to_front()`로 탭을 포그라운드로 올렸지만 여전히 링크가 없었음.

**실패 원인 2 (진짜 원인): 댓글 링크가 아예 안 만들어짐**

`bring_to_front()`와 무관하게, React SPA로 동작하는 Instagram 웹은 탭이 프로그래밍으로 열렸을 때 댓글 퍼머링크(`/c/{id}/`)를 DOM에 렌더링하지 않는 경우가 있음. UI 자동화 방식 자체가 불안정.

#### 시도 4: JavaScript fetch 인터셉션

`page.add_init_script()`로 `window.fetch`를 래핑해서 Instagram의 API 호출 헤더를 캡처하려 했음.

```
captured header keys: []
```

**실패 원인:** Instagram 웹앱이 내부적으로 fetch를 나중에 교체하거나, `Headers` 인스턴스를 사용해서 `Object.assign`이 키를 못 복사함.

#### 시도 5: Playwright 네트워크 이벤트 인터셉션 ✅

JavaScript 레벨이 아닌 **Playwright 네트워크 레벨**에서 요청 인터셉트. 브라우저가 실제로 전송하는 HTTP 헤더를 그대로 캡처.

```python
def _on_request(request):
    if "/api/v1/" in request.url:
        captured.update(request.headers)

page.on("request", _on_request)
```

이제 `x-ig-www-claim`, `x-instagram-ajax` 등 쓰기 작업에 필요한 모든 헤더가 캡처됨.

**그런데 여전히 HTML 반환.** 헤더는 맞는데 왜?

#### 최종 원인 발견: 엔드포인트 URL이 처음부터 틀렸음

`debug_capture_delete.py` 스크립트로 사용자가 직접 댓글을 삭제할 때의 실제 네트워크 요청을 캡처:

```
# 우리가 쓰던 (틀린) URL
POST /api/v1/media/{media_id}/comment/{comment_id}/delete/

# 실제 Instagram 웹이 쓰는 URL
POST /api/v1/web/comments/{media_id}/delete/{comment_id}/
```

경로 구조가 완전히 달랐음. `/web/comments/` 경로가 웹 전용 삭제 엔드포인트.

URL 한 줄 수정으로 최종 해결:

```
{"status":"ok"}
```

---

## 최종 아키텍처

```
main.py                 # 진입점, CustomTkinter 테마 설정
gui.py                  # 메인 윈도우, 뷰 전환 관리
browser.py              # Playwright 세션 관리 (persistent context)
instagram.py            # 댓글 수집/삭제 API 호출
detector.py             # 텍스트 정규화 + 블랙리스트 스팸 탐지
playwright_worker.py    # 단일 Playwright 전용 스레드
views/
  login_view.py         # 로그인 화면
  post_view.py          # 게시물 URL 입력
  result_view.py        # 탐지 결과 + 삭제 확인
```

### 댓글 삭제 최종 플로우

1. `page.on("request", ...)` 리스너 등록
2. 게시물 URL로 이동 (Instagram SPA 로드)
3. 3초 대기 — Instagram JS가 초기 API 호출을 하면서 헤더 캡처됨
4. 캡처된 헤더(`x-ig-www-claim`, `x-instagram-ajax` 등)로 삭제 요청:
   ```
   POST /api/v1/web/comments/{media_id}/delete/{comment_id}/
   ```
5. `{"status":"ok"}` 확인

---

## 교훈

1. **Instagram 비공개 API 엔드포인트는 직접 캡처해야 한다.** 인터넷에 알려진 URL과 실제 현재 URL이 다른 경우가 많음. `debug_capture_delete.py` 같은 스크립트로 실제 트래픽을 보는 게 가장 빠름.

2. **GET(읽기)과 POST(쓰기)의 인증 요구사항이 다르다.** GET은 csrf + app-id만 있어도 되지만, POST는 `x-ig-www-claim`, `x-instagram-ajax`가 추가로 필요함. 이걸 모르면 쓰기 API가 계속 HTML을 반환해서 원인을 못 찾음.

3. **Playwright 네트워크 이벤트(`page.on("request")`)는 JS 인터셉션보다 훨씬 강력하다.** JS 레벨에서 `window.fetch`를 래핑하면 라이브러리 내부 구현에 따라 작동 안 할 수 있음. 네트워크 레벨은 무조건 잡힘.

4. **외부 라이브러리(instagrapi)는 세션 방식이 맞아야 한다.** 웹 브라우저 세션으로 모바일 API를 호출하면 Instagram이 핑거프린트 불일치를 감지하고 차단함.

5. **Playwright sync API는 하나의 스레드에서만 써야 한다.** GUI 스레드와 분리된 전용 워커 스레드를 만들고 큐로 통신하는 패턴이 필수.
