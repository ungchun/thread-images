#!/usr/bin/env python3
"""dashboard.json의 문라이트·코르텍스 게시물을 노션 DB "스레드 게시물 성과"에 넣는다.

게시물 1건 = 1행. 게시물 링크가 고유값이라 그걸로 기존 행을 찾아
있으면 숫자를 갱신하고 없으면 새 행을 만든다. 조회수는 며칠간 계속 오르므로
매일 갱신해야 값이 맞다. 트레이스는 넣지 않는다 — 이 DB는 문라이트·코르텍스 전용이다.

    python3 notion_sync.py --dry-run     # 쓰지 않고 뭘 할지만 출력
    python3 notion_sync.py               # 실제 반영

토큰은 NOTION_TOKEN 환경변수. 값은 절대 출력하지 않는다.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB_ID = "52bd8a99-4774-4680-8976-8a21132dc3b0"   # 문라이트&코르텍스 스레드 성과 정리 > 스레드 게시물 성과
API = "https://api.notion.com/v1/"
PROJECTS = {"moonlight": "문라이트", "cortex": "코르텍스"}

COUNTRY = {"KR": "한국", "JP": "일본", "TW": "대만", "VN": "베트남", "TH": "태국", "ID": "인도네시아",
           "PH": "필리핀", "IN": "인도", "MY": "말레이시아", "TR": "터키", "ES": "스페인", "DE": "독일",
           "IT": "이탈리아", "FR": "프랑스", "PT": "포르투갈", "BR": "브라질", "US": "미국", "AU": "호주"}
# 계정 국가 → 게시물 언어. 브라질은 포르투갈어지만 문체가 달라 따로 표기한다.
LANG = {"KR": "한국어", "JP": "일본어", "TW": "중국어(번체)", "VN": "베트남어", "TH": "태국어",
        "ID": "인도네시아어", "PH": "필리핀어", "IN": "힌디어", "MY": "말레이어", "TR": "터키어",
        "ES": "스페인어", "DE": "독일어", "IT": "이탈리아어", "FR": "프랑스어", "PT": "포르투갈어",
        "BR": "포르투갈어(브라질)", "US": "영어", "AU": "영어"}


def api(method, path, body=None, tries=3):
    """노션 API. 429·5xx는 잠깐 쉬고 다시 민다."""
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("NOTION_TOKEN 없음")
    req = urllib.request.Request(
        API + path, method=method,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            err = json.load(e)
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(2 * (i + 1))
                continue
            raise RuntimeError(f"{e.code} {err.get('message', '')[:200]}")


def find_by_link(link):
    """게시물 링크로 기존 행을 찾는다. 없으면 None."""
    r = api("POST", f"databases/{DB_ID}/query",
            {"filter": {"property": "게시물 링크", "url": {"equals": link}}, "page_size": 1})
    res = r.get("results", [])
    return res[0]["id"] if res else None


_TZ = {}


def local_time(p):
    """발행 시각을 그 계정의 현지 시각으로. 시간대 표시는 뺀다 — 넣으면 노션이 보는 사람
    시간대로 바꿔 보여줘서 LA 09/13 11:01이 한국에서 09/14 03:01로 보인다."""
    if not _TZ:
        for d in (ROOT / "accounts").iterdir():
            m = d / "meta.txt"
            if m.exists():
                _TZ[d.name] = m.read_text().split()[1]
    tz = ZoneInfo(_TZ.get(p["account"], "UTC"))
    return datetime.fromisoformat(p["utc"]).astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")


def props(p):
    """dashboard.json 게시물 한 건 → 노션 속성."""
    text = (p.get("text") or "").strip()
    first = text.splitlines()[0].strip() if text else "(본문 없음)"
    return {
        "게시물": {"title": [{"text": {"content": first[:200]}}]},
        "게시물 링크": {"url": p["link"]},
        "본문": {"rich_text": [{"text": {"content": text[:2000]}}]},
        "날짜": {"date": {"start": local_time(p)}},   # 현지 시각, 시간대 없음
        "계정": {"select": {"name": p["account"]}},
        "국가": {"select": {"name": COUNTRY.get(p["country"], p["country"])}},
        "게시물 언어": {"select": {"name": LANG.get(p["country"], "미확인")}},
        "제품": {"select": {"name": PROJECTS[p["project"]]}},
        "조회": {"number": p.get("views") or 0},
        "하트": {"number": p.get("likes") or 0},
        "댓글": {"number": p.get("replies") or 0},
        "리포스트": {"number": p.get("reposts") or 0},
        "공유": {"number": p.get("shares") or 0},
    }


def metrics_only(p):
    """갱신 시엔 숫자와 날짜만 덮어쓴다. 제목·본문·선택지는 처음 넣은 그대로 둔다 —
    담당자가 노션에서 손으로 고쳤을 수 있다. 날짜는 UTC로 넣었던 옛 행을 바로잡기 위해 포함한다."""
    full = props(p)
    return {k: full[k] for k in ("조회", "하트", "댓글", "리포스트", "공유", "날짜")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    ap.add_argument("--days", type=int, default=0, help="최근 N일만 (0이면 dashboard.json 전체)")
    ap.add_argument("--limit", type=int, default=0, help="최신 N건만 (테스트용)")
    a = ap.parse_args()

    d = json.load(open(ROOT / "dashboard.json", encoding="utf-8"))
    posts = [p for p in d["posts"] if p.get("project") in PROJECTS and p.get("link")]
    if a.days:
        from datetime import datetime, timedelta, timezone
        cut = (datetime.now(timezone.utc) - timedelta(days=a.days)).isoformat()
        posts = [p for p in posts if p["utc"] >= cut]
    posts.sort(key=lambda p: p["utc"])
    if a.limit:
        posts = posts[-a.limit:]
    print(f"대상 {len(posts)}건 (dashboard.json 생성 {d['generated'][:16]})", flush=True)

    created = updated = failed = 0
    for p in posts:
        tag = f"{PROJECTS[p['project']]:<4} {p['account']:<13} {p['utc'][:10]} 조회 {p.get('views', 0):>6}"
        try:
            pid = find_by_link(p["link"])
            if pid:
                if not a.dry_run:
                    api("PATCH", f"pages/{pid}", {"properties": metrics_only(p)})
                updated += 1
                print(f"갱신 {tag}", flush=True)
            else:
                if not a.dry_run:
                    api("POST", "pages", {"parent": {"database_id": DB_ID}, "properties": props(p)})
                created += 1
                print(f"추가 {tag}", flush=True)
        except Exception as e:
            failed += 1
            print(f"실패 {tag}: {e}", flush=True)
        time.sleep(0.35)   # 노션 3 req/s 제한

    mode = "DRY-RUN " if a.dry_run else ""
    print(f"\n{mode}추가 {created} / 갱신 {updated} / 실패 {failed}", flush=True)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
