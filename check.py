#!/usr/bin/env python3
"""전 계정 토큰 점검. accounts/ 폴더마다 /me를 찔러 username이 폴더명과 맞는지 본다.

토큰이 빠졌는지, 만료됐는지, 다른 계정 토큰이 잘못 들어갔는지가 한 번에 나온다.
토큰 값 자체는 절대 출력하지 않는다.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from run import creds

ROOT = Path(__file__).resolve().parent


def check(account):
    try:
        token, uid = creds(account)
    except Exception as e:
        return "설정없음", str(e)[:60]
    url = ("https://graph.threads.net/v1.0/me?" +
           urllib.parse.urlencode({"fields": "id,username", "access_token": token}))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        msg = json.load(e).get("error", {}).get("message", "")
        return "실패", msg[:70]
    except Exception as e:
        return "실패", str(e)[:70]
    if d.get("username") != account:
        return "불일치", f"토큰 주인은 {d.get('username')}"
    if str(d.get("id")) != str(uid):
        return "id다름", f"실제 {d.get('id')} / 설정 {uid}"
    return "정상", d["id"]


def main():
    bad = 0
    for d in sorted((ROOT / "accounts").iterdir()):
        if not d.is_dir():
            continue
        state, detail = check(d.name)
        if state != "정상":
            bad += 1
        print(f"{state:6} {d.name:16} {detail}")
    print(f"\n문제 {bad}건")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
