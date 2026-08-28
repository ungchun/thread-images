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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://graph.threads.net/v1.0"
ROOT = Path(__file__).parent
SCHEDULE = ROOT / "schedule.txt"
IMAGES = ROOT / "images"
RAW = "https://raw.githubusercontent.com/ungchun/thread-images/main/"


def api(path, token, **params):
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"{BASE}/{path}", data) as r:
        return json.load(r)


def creds(account):
    env = {}
    for line in (ROOT / "accounts" / account / "env.sh").read_text().splitlines():
        if line.startswith("export "):
            k, _, v = line[7:].partition("=")
            env[k.strip()] = v.strip().strip("'\"")
    return env["THREADS_TOKEN"], env["THREADS_USER_ID"]


def publish(account, text, image, reply=None):
    token, user = creds(account)
    kind = {"media_type": "IMAGE", "image_url": RAW + image} if image else {"media_type": "TEXT"}
    container = api(f"{user}/threads", token, text=text, **kind)["id"]
    time.sleep(30)  # 문서 권장: 발행 전 대기
    post_id = api(f"{user}/threads_publish", token, creation_id=container)["id"]
    if reply:
        c = api(f"{user}/threads", token, media_type="TEXT", text=reply, reply_to_id=post_id)["id"]
        time.sleep(30)
        api(f"{user}/threads_publish", token, creation_id=c)
    return post_id


def main():
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
        image = None if image == "-" else image
        try:
            body, _, reply = (ROOT / textfile).read_text(encoding="utf-8").partition("\n---\n")
            post_id = publish(account, body.strip(), image, reply.strip() or None)
        except Exception as e:  # 실패하면 줄을 남겨 다음 회차에 재시도
            print(f"FAIL {account} {textfile}: {e}", flush=True)
            kept.append(line)
            continue
        print(f"posted {post_id} {account} {textfile}", flush=True)
        shutil.move(ROOT / textfile, ROOT / "done" / Path(textfile).name)
        if image:
            shutil.move(IMAGES / image, ROOT / "done" / Path(image).name)
        changed = True
    if changed:
        SCHEDULE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        sync()


def sync():
    """게시 결과를 리포에 반영해 다른 기기와 맞춘다."""
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "-A"], check=False)
    subprocess.run(git + ["commit", "--quiet", "-m", "posted"], check=False)
    subprocess.run(git + ["push", "--quiet"], check=False)


if __name__ == "__main__":
    main()
