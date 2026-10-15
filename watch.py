#!/usr/bin/env python3
"""남의 계정 게시물 지표를 모은다. watch.html이 watch.json을 읽어 보여준다.

공식 API는 남의 글 지표를 안 준다(profile_posts는 앱 심사 + 지표 필드 없음).
대신 공개 프로필 페이지를 검색엔진 UA로 받으면 HTML 안 JSON에 글별
좋아요·답글·리포스트·인용이 들어 있다. 조회수는 로그아웃 상태라 없다.
첫 화면에 실린 최근 글(대략 20~30개) 중 SINCE 이후 것만 남긴다.
글이 많은 계정은 그 기간이 첫 화면을 넘어 앞부분만 잡힌다(cut=True로 표시).

  python3 watch.py      # watch.txt의 프로필 링크 전부 → watch.json
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SINCE = datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=9)))   # 이 시각(KST) 이후 글만
UA = "Googlebot/2.1 (+http://www.google.com/bot.html)"   # 일반 UA로 받으면 글 데이터가 안 실린다


def fetch(username):
    req = urllib.request.Request(f"https://www.threads.com/@{username}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse(html, username):
    posts, user = {}, {}

    def walk(o):
        if isinstance(o, dict):
            if "like_count" in o and "taken_at" in o and "code" in o \
                    and (o.get("user") or {}).get("username") == username:   # 남의 글 인용·답글 원본은 뺀다
                posts[o["pk"]] = o
            if o.get("username") == username and "follower_count" in o:
                user.update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for m in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            walk(json.loads(m.group(1)))
        except ValueError:
            pass

    since = SINCE.timestamp()
    rows = []
    for p in posts.values():
        if p["taken_at"] < since:
            continue
        info = p.get("text_post_app_info") or {}
        rows.append({
            "link": f"https://www.threads.com/@{username}/post/{p['code']}",
            "utc": datetime.fromtimestamp(p["taken_at"], timezone.utc).isoformat(),
            "text": ((p.get("caption") or {}).get("text") or "").strip(),
            "likes": p.get("like_count") or 0,
            "replies": info.get("direct_reply_count") or 0,
            "reposts": info.get("repost_count") or 0,
            "quotes": info.get("quote_count") or 0,
            "reply": bool(info.get("is_reply")),     # 자기 글 밑에 단 답글(앱 이름·링크 댓글)
        })
    rows.sort(key=lambda r: r["utc"], reverse=True)
    return {
        "username": username,
        "name": user.get("full_name") or "",
        "followers": user.get("follower_count"),
        "link": f"https://www.threads.com/@{username}",
        "posts": rows,
        # 받은 글이 전부 SINCE 이후면 그 앞 글은 첫 화면 밖이라 못 받은 것이다
        "cut": bool(posts) and min(p["taken_at"] for p in posts.values()) >= since,
    }


def main():
    # 한 줄 = "프로필링크  나라 | 홍보 앱". 나라는 본문 언어를 보고 손으로 적는다(자동 판별은 말레이/인니, 대만/홍콩을 못 가른다)
    rows = re.findall(r"@([\w.]+)[^\S\n]*(.*)", (ROOT / "watch.txt").read_text(encoding="utf-8"))
    out = []
    for n, country in dict(rows).items():
        try:
            acc = parse(fetch(n), n)
            print(f"{n}: 글 {len(acc['posts'])}개")
        except Exception as e:
            acc = {"username": n, "link": f"https://www.threads.com/@{n}", "posts": [], "error": str(e)[:200]}
            print(f"{n}: 실패 {e}")
        acc["country"], _, acc["app"] = (x.strip() for x in country.partition("|"))
        out.append(acc)
        time.sleep(2)   # 연속 요청으로 막히지 않게
    (ROOT / "watch.json").write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(), "since": SINCE.isoformat(), "accounts": out},
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
