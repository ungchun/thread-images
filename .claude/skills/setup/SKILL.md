---
name: setup
description: 새 팀원이 이 레포를 클론한 뒤 자기 Threads 계정을 등록해 공용 대시보드에 같이 보이게 만든다. 팀원 등록, 계정 추가, 토큰 확인, 첫 수집과 푸시까지 한 단계씩 진행한다. "세팅해줘", "내 계정 추가", "대시보드에 내 계정 넣어줘", "온보딩", "토큰 만료됐어"처럼 팀원이 대시보드에 합류하거나 계정을 늘리거나 토큰을 갈 때 사용한다. 경계: 글 예약·발행은 threads 스킬, 답글은 threads-reply 스킬이다. 2026-10-22부터 팀원 계정도 threads 스킬 예약으로만 발행한다(토큰은 THREADS_<아이디> 시크릿).
---

# 팀원 세팅

팀원은 **대시보드만 같이 본다.** 발행은 Actions 주인(team.json의 `actions: true`)만 한다.
팀원 토큰은 GitHub Secrets에 넣지 않는다. 각자 로컬 `accounts/<계정>/env.sh`(gitignore)에
두고, 대시보드 갱신 버튼이 그 토큰으로 자기 계정만 수집해 `dashboard_<GitHub아이디>.json`을
푸시한다. 대시보드는 사람별 파일을 합쳐서 보여준다.

**한 단계씩 진행한다.** 단계마다 결과를 한두 줄로 보여주고, 사용자 확인이 필요한 곳에서만 멈춘다.
질문은 인라인 텍스트로 한다.

**토큰은 절대 출력하지 않는다.** 화면에도, 커밋에도, 로그에도. `env.sh`는 커밋하지 않는다.

## 0. 레포 루트로

```bash
ROOT=$(git rev-parse --show-toplevel) && cd "$ROOT" && git pull --quiet --rebase --autostash
```

`team.json`이 없으면 이 레포가 아니다. 멈추고 알린다.

## 1. GitHub 확인

```bash
gh auth status && gh api user -q .login
gh api repos/ungchun/thread-images -q .permissions.push
```

- `gh`가 없거나 로그인 전이면: `brew install gh` 후 터미널에서 `! gh auth login`을 하라고 안내하고 기다린다.
- push 권한이 `true`가 아니면: 레포 주인(ungchun)에게 협업자 초대를 요청하라고 안내한다.
  초대 메일을 수락한 뒤 다시 확인한다. 권한 없이는 대시보드 데이터를 올릴 수 없다.

로그인 아이디를 이후 `<나>`로 쓴다.

## 2. team.json에 나 추가

`team.json`에 `<나>`가 이미 있으면 건너뛴다. 없으면 대시보드에 보일 이름(짧게, 예: "지은")을
묻고 추가한다. `actions`는 넣지 않는다.

```json
"<나>": {"name": "지은"}
```

## 3. 계정 추가 — 한 계정씩 반복

여러 계정이면 하나 끝내고 "다음 계정 있어요?"로 이어간다.

### 3-1. 계정 이름

Threads 아이디(@ 없이)를 묻는다. 폴더는 `accounts/<계정>/`.
이미 폴더가 있고 `meta.txt` 3번째 토큰(소유자)이 `<나>`가 아니면 멈춘다 — 다른 사람 계정이다.
`<나>` 계정이면 맨 아래 '토큰 교체'로 넘어간다.

### 3-2. 토큰 저장 (출력 금지)

팀원은 계정마다 Threads 액세스 토큰을 이미 갖고 있다. 발급 안내는 하지 않는다.
토큰이 없다는 계정만 건너뛰고 "토큰 받으면 /setup 다시"라고 남긴다.
지표·답글을 읽으려면 `threads_basic`, `threads_manage_insights`, `threads_read_replies` 권한이 필요하다.

토큰을 **클립보드에 복사**하고 "복사했어"라고 말해 달라고 한다. 채팅에 붙여넣지 않게 한다.
신호를 받으면 아래를 돌린다. 클립보드에서 읽어 `/me`로 아이디를 확인하고 `env.sh`를 쓴다.

```bash
ACC=<계정> python3 - <<'EOF'
import json, os, subprocess, urllib.request, urllib.parse
from pathlib import Path
acc = os.environ["ACC"]
tok = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
assert tok and " " not in tok and "\n" not in tok, "클립보드가 토큰이 아니다"
q = urllib.parse.urlencode({"fields": "id,username", "access_token": tok})
me = json.load(urllib.request.urlopen(f"https://graph.threads.net/v1.0/me?{q}", timeout=20))
assert me["username"] == acc, f"이 토큰은 {me['username']} 계정 것이다"
d = Path("accounts") / acc
d.mkdir(parents=True, exist_ok=True)
(d / "env.sh").write_text(f"export THREADS_TOKEN='{tok}'\nexport THREADS_USER_ID='{me['id']}'\n")
os.chmod(d / "env.sh", 0o600)
print("ok", me["username"], me["id"])
EOF
git check-ignore -q accounts/<계정>/env.sh && echo "env.sh 커밋 안 됨 확인"
```

`pbpaste`가 없는 환경(맥이 아님)이면 사용자에게 `accounts/<계정>/env.sh`를 직접 만들게 한다:
`export THREADS_TOKEN='...'` 한 줄. 그다음 위 스크립트에서 `tok`을 그 파일에서 읽도록 바꿔 돌린다.

`HTTP Error 400`/`401`이면 토큰이 틀렸거나 만료다. 팀원에게 새 토큰을 받아 다시 복사해 달라고 한다.

### 3-3. meta.txt

국가와 홍보 프로젝트를 묻는다. 시간대는 국가로 추정해 보여주고 확인받는다
(나라에 시간대가 여럿이면 묻는다).

- 국가: ISO 두 글자 (KR, VN, US …)
- 프로젝트: `trace`(트레이스) · `moonlight`(문라이트) · `cortex`(코르텍스) 중 하나.
  대시보드 프로젝트 탭이 이걸로 나뉜다.

```
<국가> <IANA 시간대> <나> <프로젝트>
```

예: `VN Asia/Ho_Chi_Minh jieun trace` → `accounts/<계정>/meta.txt`

## 4. 커밋·푸시

```bash
git add team.json accounts/*/meta.txt
git status --short   # env.sh가 보이면 멈춘다
git commit -m "setup: <나> 계정 추가 (<계정들>)"
git pull --rebase --autostash --quiet && git push
```

다른 팀원이 같은 때 `team.json`에 자기를 넣었으면 리베이스가 충돌한다. 두 항목을 다 남기고
`git add team.json && git rebase --continue` 후 다시 푸시한다.

## 5. 첫 수집

```bash
python3 dashboard.py --owner <나>
```

계정당 1분 안팎 걸린다. 끝에 나오는 `오류` 줄을 보여준다. 0건이면:

```bash
git add dashboard_<나>.json && git commit -m "dashboard <나>" && git pull --rebase --autostash --quiet && git push
```

## 6. 대시보드 보는 법 안내

```bash
python3 serve.py   # http://localhost:8899/dashboard.html
```

- 위쪽 사람 탭(전체 / 이름별)과 프로젝트 탭으로 거른다.
- **갱신** 버튼은 내 계정만 다시 수집해 푸시한다. 팀원 숫자는 그 사람이 마지막으로 갱신한 시점 기준이다
  (상단에 사람별 갱신 시각이 나온다).
- serve.py 없이 `dashboard.html`을 그냥 열어도 GitHub에 올라간 데이터로 보인다. 갱신만 안 된다.

## 토큰 교체 (만료됐을 때)

Threads 토큰은 60일이면 만료된다. 대시보드 상단 "수집 실패"에 그 계정이 뜨면 교체한다.
새 토큰을 받아 3-2(저장)만 다시 하면 된다. meta.txt는 그대로 둔다.
만료 전이라면 새로 받지 않고 연장할 수도 있다:

```bash
ACC=<계정> python3 - <<'EOF'
import json, os, re, urllib.request
from pathlib import Path
f = Path("accounts") / os.environ["ACC"] / "env.sh"
s = f.read_text()
tok = re.search(r"THREADS_TOKEN='([^']+)'", s).group(1)
r = json.load(urllib.request.urlopen(
    f"https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token={tok}", timeout=20))
f.write_text(s.replace(tok, r["access_token"]))
print("연장됨, 남은 일수", r["expires_in"] // 86400)
EOF
```
