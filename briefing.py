#!/usr/bin/env python3
"""매일 아침 스레드 홍보 브리핑 (트레이스, 조회수만). cron-job.org가 08:00 KST에 briefing.yml을 깨운다.

팀 전체 계정을 이 자리에서 새로 긁는다. 커밋된 dashboard_<아이디>.json은 팀원이 갱신을
눌러야만 바뀌어서 아침에 그대로 쓰면 숫자가 멈춰 있다.
  Actions 주인  THREADS_ACCOUNTS
  팀원          THREADS_<아이디 대문자, -는 _> (예: THREADS_SEONGJI_CODE). 없으면 그 사람은 건너뛴다.

  python3 briefing.py          # 출력만
  python3 briefing.py --send   # 슬랙 발송 (SLACK_BRIEFING_WEBHOOK_URL)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from dashboard import accounts, posts_of
from report import actions_owner, team

KST = timezone(timedelta(hours=9))
DAYS = 14
WEEKDAY = "월화수목금토일"


def collect():
    """사람마다 자기 시크릿을 THREADS_ACCOUNTS 자리에 끼워 creds()가 그대로 읽게 한다."""
    mine = os.environ.get("THREADS_ACCOUNTS", "")
    posts, errors = [], []
    for who in team():
        blob = mine if who == actions_owner() else os.environ.get("THREADS_" + who.upper().replace("-", "_"))
        if not blob:
            errors.append(f"{who}: 시크릿 없음 — 건너뜀")
            continue
        os.environ["THREADS_ACCOUNTS"] = blob
        for a in accounts(who):
            try:
                posts += posts_of(a, DAYS)
            except Exception as e:
                errors.append(f"{a}: {str(e)[:80]}")
    os.environ["THREADS_ACCOUNTS"] = mine
    return [p for p in posts if p["kind"] != "REPOST_FACADE" and p["project"] == "trace"], errors


def utc(p):
    return datetime.fromisoformat(p["utc"])


def link(p):
    head = (p["text"].splitlines() or [""])[0][:24]
    head = head.replace("<", "").replace(">", "").replace("|", "")   # 슬랙 링크 문법 깨짐 방지
    return f"<{p['link']}|{head}…>"


def message(posts, now):
    today = now.astimezone(KST)
    yday = (today - timedelta(days=1)).date()
    y = sorted((p for p in posts if utc(p).astimezone(KST).date() == yday), key=lambda p: -p["views"])
    lines = [f"📊 *스레드 홍보 브리핑 · {today:%m/%d} ({WEEKDAY[today.weekday()]})*",
             f"어제 {yday:%m/%d} 발행 {len(y)}건 · 총 조회 {sum(p['views'] for p in y):,}", "",
             "*━━ 어제 TOP 3 ━━*"]
    lines += [f"{p['flag']} {p['account']}  *{p['views']:,}*  {link(p)}" for p in y[:3]]
    rest = [f"{p['flag']} {p['account']} *{p['views']:,}*" for p in y[3:]]
    if rest:
        lines += ["", "*━━ 나머지 ━━*"] + [" · ".join(rest[i:i + 3]) for i in range(0, len(rest), 3)]
    # 계정당 1개 — 안 그러면 한 계정의 같은 문구가 상위를 다 차지한다
    top, seen = [], set()
    for p in sorted(posts, key=lambda p: -p["views"]):
        if p["account"] not in seen:
            seen.add(p["account"])
            top.append(p)
        if len(top) == 3:
            break
    lines += ["", f"*━━ 최근 {DAYS}일 TOP 3 (계정당 1개) ━━*"]
    lines += [f"{utc(p).astimezone(KST):%m/%d} {p['flag']} {p['account']}  *{p['views']:,}*  {link(p)}"
              for p in top]
    return "\n".join(lines)


def demo():
    now = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    mk = lambda acc, views, when: {"account": acc, "views": views, "flag": "", "text": "a|b\nc",
                                   "link": "L", "utc": when}
    ps = [mk("x", 5, "2026-10-18T01:00:00+00:00"), mk("x", 9, "2026-10-12T01:00:00+00:00"),
          mk("y", 7, "2026-10-17T16:00:00+00:00"),   # KST 10/18 01:00 → 어제
          mk("z", 3, "2026-10-17T14:00:00+00:00")]   # KST 10/17 23:00 → 어제 아님
    m = message(ps, now)
    assert "어제 10/18 발행 2건 · 총 조회 12" in m, m
    assert "10/12  x  *9*" in m and m.count("x  *") == 2, m   # 14일 TOP은 x의 최고 글 하나만
    assert "<L|ab…>" in m, m
    print("ok")


def main():
    if "--demo" in sys.argv:
        return demo()
    posts, errors = collect()
    msg = message(posts, datetime.now(timezone.utc))
    print(msg)
    for e in errors:
        print("  !", e, file=sys.stderr)
    if "--send" in sys.argv:
        req = urllib.request.Request(os.environ["SLACK_BRIEFING_WEBHOOK_URL"],
                                     data=json.dumps({"text": msg}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        print("sent")


if __name__ == "__main__":
    main()
