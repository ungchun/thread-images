#!/usr/bin/env python3
"""Threads 검색 결과에서 지금 반응이 큰 글을 모은다. 우리 카테고리 밖까지 본다.

watch.py가 정해 둔 경쟁 계정만 본다면, 이건 검색어로 판 전체를 훑는다 —
어떤 형식(영상·캐러셀·글만)·어떤 말투가 지금 터지는지 매일 보려고.
로그아웃 검색 페이지를 검색엔진 UA로 받으면 HTML 안 JSON에 글이 20개 안팎 실린다.
조회수는 없고 좋아요·답글·리포스트, 미디어 종류, 영상 자막(transcription)이 있다.

  python3 scout.py              # scout.txt 검색어 전부 → scout/YYYY-MM-DD.json
  python3 scout.py --top 5      # 저장 후 검색어별 상위 5개를 요약 출력
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "scout"
UA = "Googlebot/2.1 (+http://www.google.com/bot.html)"   # 일반 UA로 받으면 글 데이터가 안 실린다
MAX_AGE = timedelta(days=45)   # 지금 터지는 것만 — 오래된 명예의 전당은 뺀다
KIND = {1: "image", 2: "video", 8: "carousel", 19: "text"}


def fetch(q):
    url = "https://www.threads.com/search?" + urllib.parse.urlencode({"q": q, "serp_type": "default"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse(html):
    posts = {}

    def walk(o):
        if isinstance(o, dict):
            if "like_count" in o and "taken_at" in o and "code" in o:
                posts[o["pk"]] = o
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

    since = (datetime.now(timezone.utc) - MAX_AGE).timestamp()
    rows = []
    for p in posts.values():
        if p["taken_at"] < since:
            continue
        info = p.get("text_post_app_info") or {}
        user = (p.get("user") or {}).get("username") or ""
        carousel = p.get("carousel_media") or []
        rows.append({
            "link": f"https://www.threads.com/@{user}/post/{p['code']}",
            "user": user,
            "utc": datetime.fromtimestamp(p["taken_at"], timezone.utc).isoformat(),
            "kind": KIND.get(p.get("media_type"), str(p.get("media_type"))),
            # 캐러셀 안에 영상이 섞였는지 — "녹화 영상 + 결과 사진" 같은 조합을 보려고
            "videos": sum(1 for c in carousel if c.get("video_versions")) + (1 if p.get("video_versions") else 0),
            "slides": len(carousel),
            "text": ((p.get("caption") or {}).get("text") or "").strip(),
            "likes": p.get("like_count") or 0,
            "replies": info.get("direct_reply_count") or 0,
            "reposts": info.get("repost_count") or 0,
            "quotes": info.get("quote_count") or 0,
            "paid": bool(p.get("is_paid_partnership")),
            "ocr": (p.get("seo_ocr_for_related_post") or "")[:300],
            "transcript": (p.get("seo_transcript_for_related_post") or "")[:300],
        })
    rows.sort(key=lambda r: r["likes"], reverse=True)
    return rows


def main():
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 0
    # 한 줄 = "검색어  나라 | 왜 보나". #으로 시작하면 건너뛴다
    queries = []
    for line in (ROOT / "scout.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            q, _, rest = line.partition("\t")
            country, _, why = rest.partition("|")
            queries.append((q.strip(), country.strip(), why.strip()))
    out = []
    for q, country, why in queries:
        try:
            rows = parse(fetch(q))
            print(f"{q}: 글 {len(rows)}개")
        except Exception as e:
            rows = []
            print(f"{q}: 실패 {e}")
        out.append({"q": q, "country": country, "why": why, "posts": rows})
        time.sleep(3)   # 연속 요청으로 막히지 않게
    OUT.mkdir(exist_ok=True)
    day = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    (OUT / f"{day}.json").write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(), "queries": out},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if top:
        for x in out:
            print(f"\n## {x['q']} ({x['country']})")
            for r in x["posts"][:top]:
                vid = f" 영상{r['videos']}" if r["videos"] else ""
                print(f"  ♥{r['likes']} 답{r['replies']} {r['kind']}{vid} {r['utc'][:10]} @{r['user']} "
                      + r["text"][:70].replace("\n", " "))


if __name__ == "__main__":
    main()
