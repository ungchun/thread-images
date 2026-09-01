#!/usr/bin/env python3
"""schedule.txt 에서 시각이 지난 예약을 올린다. cron이 5분마다 부른다.

schedule.txt 한 줄: <ISO시각(UTC)>\t<계정명>\t<본문파일>\t<이미지파일|->
게시에 성공하면 그 줄을 삭제하고, 본문/이미지를 done/ 으로 옮긴다.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://graph.threads.net/v1.0"
ROOT = Path(__file__).parent
SCHEDULE = ROOT / "schedule.txt"
IMAGES = ROOT / "images"
RAW = "https://raw.githubusercontent.com/ungchun/thread-images/main/images/"


def api(path, token, get=False, **params):
    """Threads API 호출. GET은 본문을 못 읽고 190을 내주므로 쿼리로 보낸다."""
    params["access_token"] = token
    query = urllib.parse.urlencode(params)
    if get:
        req = urllib.request.Request(f"{BASE}/{path}?{query}")
    else:
        req = urllib.request.Request(f"{BASE}/{path}", data=query.encode())
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # Threads는 실패 이유를 본문에 담는다
        raise RuntimeError(f"{e.code} {e.read().decode()[:800]}") from None


def wait_ready(container, token, tries=20):
    """컨테이너가 FINISHED 될 때까지 기다린다. 캐러셀은 묶기 전에 반드시 확인해야 한다."""
    for _ in range(tries):
        st = api(container, token, get=True, fields="status,error_message")
        if st.get("status") == "FINISHED":
            return
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container}: {st}")
        time.sleep(5)
    raise RuntimeError(f"container {container}: 준비 안 됨")


def creds(account):
    """계정별 토큰. THREADS_ACCOUNTS(JSON) 우선, 없으면 로컬 env.sh."""
    blob = os.environ.get("THREADS_ACCOUNTS")
    if blob:
        a = json.loads(blob)[account]
        return a["token"], a["user_id"]
    env = {}
    for line in (ROOT / "accounts" / account / "env.sh").read_text().splitlines():
        if line.startswith("export "):
            k, _, v = line[7:].partition("=")
            env[k.strip()] = v.strip().strip("'\"")
    return env["THREADS_TOKEN"], env["THREADS_USER_ID"]


def fixed_reply(account):
    """계정 고정 답글. 본문에 ---로 직접 쓰면 그쪽이 우선한다."""
    f = ROOT / "accounts" / account / "reply.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def publish(account, text, images, reply=None):
    token, user = creds(account)
    if len(images) > 1:  # 캐러셀: 장마다 컨테이너를 만들고 묶는다
        items = [api(f"{user}/threads", token, media_type="IMAGE",
                     image_url=RAW + i, is_carousel_item="true")["id"] for i in images]
        for i in items:
            wait_ready(i, token)
        kind = {"media_type": "CAROUSEL", "children": ",".join(items)}
    elif images:
        kind = {"media_type": "IMAGE", "image_url": RAW + images[0]}
    else:
        kind = {"media_type": "TEXT"}
    container = api(f"{user}/threads", token, text=text, **kind)["id"]
    wait_ready(container, token)
    post_id = api(f"{user}/threads_publish", token, creation_id=container)["id"]
    if reply:
        c = api(f"{user}/threads", token, media_type="TEXT", text=reply, reply_to_id=post_id)["id"]
        wait_ready(c, token)
        api(f"{user}/threads_publish", token, creation_id=c)
    return post_id


def main():
    if not os.environ.get("GITHUB_ACTIONS"):
        subprocess.run(["git", "-C", str(ROOT), "pull", "--quiet", "--rebase"], check=False)
    if not SCHEDULE.exists():
        return
    now = datetime.now(timezone.utc)
    kept, changed = [], False
    for line in SCHEDULE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            kept.append(line)
            continue
        when, account, textfile, image = line.split("\t")
        if datetime.fromisoformat(when) > now:
            kept.append(line)
            continue
        images = [] if image == "-" else image.split(",")
        try:
            body, _, reply = (ROOT / textfile).read_text(encoding="utf-8").partition("\n---\n")
            post_id = publish(account, body.strip(), images, reply.strip() or fixed_reply(account))
        except Exception as e:  # 실패하면 줄을 남겨 다음 회차에 재시도
            print(f"FAIL {account} {textfile}: {e}", flush=True)
            kept.append(line)
            continue
        print(f"posted {post_id} {account} {textfile}", flush=True)
        shutil.move(ROOT / textfile, ROOT / "done" / Path(textfile).name)
        for i in images:
            shutil.move(IMAGES / i, ROOT / "done" / i)
        changed = True
    if changed:
        SCHEDULE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        sync()


def sync():
    """게시 결과를 리포에 반영해 다른 기기와 맞춘다. Actions에선 워크플로가 한다."""
    if os.environ.get("GITHUB_ACTIONS"):
        return
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "-A"], check=False)
    subprocess.run(git + ["commit", "--quiet", "-m", "posted"], check=False)
    subprocess.run(git + ["push", "--quiet"], check=False)


if __name__ == "__main__":
    main()
