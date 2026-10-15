#!/usr/bin/env python3
"""대시보드용 로컬 서버.

두 가지를 한다.
  1. 캐시를 완전히 막는다 — 기본 http.server는 Last-Modified/ETag로 304를 주고,
     그러면 HTML을 고쳐도 브라우저가 옛 화면을 계속 쓴다.
  2. /refresh 로 갱신한다. GitHub 토큰이 필요한 일이라
     브라우저가 직접 못 한다(HTML에 토큰을 넣으면 파일 여는 누구나 레포에 쓸 수 있다).
     여기서 gh·git을 대신 실행한다.
     - Actions 주인(team.json actions): 갱신 워크플로를 부른다. 토큰은 Secrets에 있다.
     - 팀원: 로컬 토큰(accounts/*/env.sh)으로 dashboard.py를 돌려 자기 파일만 푸시한다.

  python3 serve.py        # http://localhost:8899/dashboard.html
"""
import json
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8899
REPO = "ungchun/thread-images"
ROOT = __import__("pathlib").Path(__file__).resolve().parent
DROP = {"last-modified", "etag"}
COOLDOWN = 60          # 연타로 API를 태우지 않게

_state = {"running": False, "started": 0.0, "error": ""}
_lock = threading.Lock()


def _local(me):
    """팀원 갱신. 자기 계정만 수집해 dashboard_<아이디>.json 하나만 커밋·푸시한다."""
    from report import data_file
    subprocess.run(["python3", "dashboard.py", "--owner", me], cwd=ROOT, check=True,
                   capture_output=True, timeout=900)
    f = data_file(me).name
    subprocess.run(["git", "add", "--", f], cwd=ROOT, check=True, timeout=30)
    subprocess.run(["git", "commit", "-m", f"dashboard {me}", "--", f], cwd=ROOT,
                   capture_output=True, timeout=30)   # 바뀐 게 없으면 실패해도 된다
    for _ in range(3):   # 다른 사람 푸시와 겹치면 받아서 다시. 각자 자기 파일만 쓰니 충돌은 없다
        subprocess.run(["git", "pull", "--rebase", "--autostash", "--quiet"], cwd=ROOT,
                       capture_output=True, timeout=60)
        if subprocess.run(["git", "push", "--quiet"], cwd=ROOT,
                          capture_output=True, timeout=60).returncode == 0:
            return
        time.sleep(3)
    raise RuntimeError("푸시 실패 — 터미널에서 git status를 확인")


def _run():
    """갱신하고 끝날 때까지 지켜본다. 상태는 /refresh?status로 읽는다."""
    try:
        from report import team
        me = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True,
                            text=True, timeout=30).stdout.strip()
        if me not in team():
            raise RuntimeError(f"team.json에 {me or 'gh 로그인'}이 없다 — /setup을 먼저")
        if not team()[me].get("actions"):
            return _local(me)
        subprocess.run(["gh", "workflow", "run", "dashboard.yml", "-R", REPO],
                       check=True, capture_output=True, timeout=30)
        time.sleep(8)   # 실행이 목록에 뜨기까지
        rid = subprocess.run(
            ["gh", "run", "list", "-R", REPO, "-w", "dashboard.yml", "-L", "1",
             "--json", "databaseId", "-q", ".[0].databaseId"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        for _ in range(40):                      # 최대 ~7분
            out = subprocess.run(
                ["gh", "run", "view", rid, "-R", REPO, "--json", "status,conclusion",
                 "-q", ".status+\" \"+(.conclusion//\"\")"],
                capture_output=True, text=True, timeout=30).stdout.strip()
            if out.startswith("completed"):
                _state["error"] = "" if "success" in out else out
                if "success" in out:   # 새 dashboard.json을 로컬에도 받아둔다 (raw 캐시 우회)
                    subprocess.run(["git", "pull", "--ff-only", "--quiet"], cwd=ROOT,
                                   capture_output=True, timeout=60)
                break
            time.sleep(10)
        else:
            _state["error"] = "시간 초과"
    except Exception as e:
        _state["error"] = str(e)[:200]
    finally:
        _state["running"] = False


class Handler(SimpleHTTPRequestHandler):
    def send_header(self, key, value):
        if key.lower() in DROP:
            return
        super().send_header(key, value)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/refresh"):
            return self.send_error(404)
        with _lock:
            if _state["running"]:
                return self._json({"ok": False, "reason": "이미 갱신 중"})
            left = COOLDOWN - (time.time() - _state["started"])
            if left > 0:
                return self._json({"ok": False, "reason": f"{int(left)}초 뒤에 다시"})
            _state.update(running=True, started=time.time(), error="")
        threading.Thread(target=_run, daemon=True).start()
        self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/refresh"):
            return self._json({"running": _state["running"], "error": _state["error"]})
        super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"http://localhost:{PORT}/dashboard.html")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
