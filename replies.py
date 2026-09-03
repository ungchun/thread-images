#!/usr/bin/env python3
"""게시물의 답글을 다루는 도구. threads-reply 스킬이 쓴다.

핵심은 "우리가 아직 답 안 한 답글"을 정확히 고르는 것이다. has_replies 필드는
쓰면 안 된다 - 그건 하위 답글 존재 여부라서 제3자가 대댓글을 달아도 True가 된다.
대신 conversation 전체를 받아 우리 계정이 replied_to 로 가리킨 ID를 모으고,
그 집합에 없는 답글만 미답변으로 본다.

  python3 replies.py posts <계정> [--days 30]     게시물 목록 (지표 포함)
  python3 replies.py list <계정> <게시물id>        미답변 답글 (시간순)
  python3 replies.py tone <계정> [--limit 20]     우리가 지금까지 쓴 답장 (톤 참고용)
  python3 replies.py send <계정> <답글id> <파일>   답장 발행 (본문은 파일에서 읽는다)
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from report import meta, insights
from run import creds

ROOT = Path(__file__).resolve().parent
GRAPH = "https://graph.threads.net/v1.0"
FIELDS = "id,text,username,timestamp,permalink,replied_to,root_post,is_reply"


def api(path, token, post=False, **params):
    """GET은 토큰을 반드시 쿼리로 보낸다. 본문에 실으면 190이 난다."""
    params["access_token"] = token
    query = urllib.parse.urlencode(params)
    url = f"{GRAPH}/{path}"
    req = (urllib.request.Request(url, data=query.encode()) if post
           else urllib.request.Request(f"{url}?{query}"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode()[:500]}") from None


def paged(path, token, **params):
    """커서를 끝까지 따라간다. 인기 글은 답글이 수백 개라 한 번에 안 온다."""
    params.setdefault("limit", 100)
    out = []
    while True:
        d = api(path, token, **params)
        out += d.get("data", [])
        nxt = (d.get("paging") or {}).get("cursors", {}).get("after")
        if not nxt or not d.get("data"):
            return out
        params["after"] = nxt


def posts(account, days):
    token, uid = creds(account)
    code, tz = meta(account)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for p in api(f"{uid}/threads", token,
                 fields="id,text,timestamp,permalink", limit=100).get("data", []):
        utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        if utc < since:
            continue
        ins = insights(p["id"], token)
        head = (p.get("text") or "").strip().splitlines()
        rows.append({
            "id": p["id"],
            "when": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "views": ins.get("views", 0),
            "likes": ins.get("likes", 0),
            "replies": ins.get("replies", 0),
            "link": p.get("permalink", ""),
            "text": head[0][:30] if head else "(본문 없음)",
        })
    return rows


def unanswered(account, post_id):
    """미답변 답글을 시간순으로. 우리 글 자신과 우리가 쓴 답글은 뺀다."""
    token, _ = creds(account)
    convo = paged(f"{post_id}/conversation", token, fields=FIELDS)
    answered = {r.get("replied_to", {}).get("id")
                for r in convo if r.get("username") == account}
    _, tz = meta(account)
    rows = []
    for r in paged(f"{post_id}/replies", token, fields=FIELDS):
        if r.get("username") == account or r["id"] in answered:
            continue
        utc = datetime.fromisoformat(r["timestamp"].replace("+0000", "+00:00"))
        rows.append({
            "id": r["id"],
            "user": r.get("username", "?"),
            "when": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "text": (r.get("text") or "").strip(),
            "link": r.get("permalink", ""),
        })
    return sorted(rows, key=lambda r: r["when"])


def tone(account, limit):
    """우리가 지금까지 쓴 답장. 고정 답글(앱스토어 링크)은 톤 참고가 안 되니 뺀다."""
    token, uid = creds(account)
    fixed = (ROOT / "accounts" / account / "reply.txt")
    fixed = fixed.read_text(encoding="utf-8").strip() if fixed.exists() else ""
    out = []
    for p in api(f"{uid}/threads", token, fields="id,timestamp", limit=25).get("data", []):
        for r in paged(f"{p['id']}/conversation", token, fields=FIELDS):
            t = (r.get("text") or "").strip()
            if r.get("username") != account or not t or t == fixed:
                continue
            if "apps.apple.com" in t:
                continue
            out.append(t)
            if len(out) >= limit:
                return out
    return out


def send(account, reply_to_id, body):
    """컨테이너 생성 → 발행. 글 올릴 때와 같은 경로에 reply_to_id만 더한다."""
    token, uid = creds(account)
    c = api(f"{uid}/threads", token, post=True,
            media_type="TEXT", text=body, reply_to_id=reply_to_id)
    time.sleep(3)   # 컨테이너가 준비될 시간. 바로 발행하면 간헐적으로 실패한다.
    return api(f"{uid}/threads_publish", token, post=True, creation_id=c["id"])


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, account = sys.argv[1], sys.argv[2]

    def opt(name, default):
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default

    if cmd == "posts":
        for r in posts(account, opt("--days", 30)):
            print(f"{r['id']}  {r['when']}  조회 {r['views']:>8,}  하트 {r['likes']:>5,}  "
                  f"댓글 {r['replies']:>4,}  {r['text']}")
    elif cmd == "list":
        rows = unanswered(account, sys.argv[3])
        print(f"미답변 {len(rows)}건")
        for r in rows:
            print(f"\n[{r['id']}] @{r['user']}  {r['when']}\n{r['text']}")
    elif cmd == "tone":
        for t in tone(account, opt("--limit", 20)):
            print(f"- {t}")
    elif cmd == "send":
        body = Path(sys.argv[4]).read_text(encoding="utf-8").strip()
        print(send(account, sys.argv[3], body))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
