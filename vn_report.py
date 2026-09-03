#!/usr/bin/env python3
"""베트남 계정 게시물만 정리해 슬랙으로 보낸다.

report.py는 8개 계정을 나라별로 훑지만, 여기서는 한 계정 안에서 글끼리
비교하는 게 목적이라 국기·나라 표기를 빼고 날짜와 지표만 세운다.

  python3 vn_report.py           # 발송
  python3 vn_report.py --dry     # 출력만
  python3 vn_report.py --days 90 # 조회 기간 (기본 60일)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from report import collect, meta

ACCOUNT = "ashgrey._02"
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")


def line(r):
    """한 건 = 날짜·지표 줄 + 링크 줄. 0인 지표는 생략해 소음을 줄인다.
    댓글은 우리가 매번 다는 고정 답글 1건을 빼고 실제 반응만 센다.
    """
    extra = []
    for label, key, base in (("하트", "likes", 0), ("댓글", "replies", 1),
                             ("리포스트", "reposts", 0), ("공유", "shares", 0)):
        v = r.get(key, 0) - base
        if v > 0:
            extra.append(f"{label} {v:,}")
    tail = (" · " + " · ".join(extra)) if extra else ""
    when = r["when"].strftime("%m/%d")   # collect가 현지 시각으로 넣어준다
    return (f"`{when}`  조회 *{r.get('views', 0):,}*{tail}\n"
            f"<{r['link']}|{r['text']}>")


def render(rows, days):
    tz = meta(ACCOUNT)[1]
    ordered = sorted(rows, key=lambda r: -r.get("views", 0))
    total = sum(r.get("views", 0) for r in rows)

    out = [{"type": "header",
            "text": {"type": "plain_text", "text": f"베트남 브리핑 | {datetime.now(tz):%Y-%m-%d}"}},
           {"type": "context",
            "elements": [{"type": "mrkdwn",
                          "text": f"@{ACCOUNT} · 최근 {days}일 {len(rows)}건 · 누적 조회 {total:,} · 날짜는 현지 기준"}]},
           {"type": "divider"}]
    if not ordered:
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": "게시물 없음"}})
        return out
    # 슬랙 블록 하나에 담을 수 있는 텍스트가 3000자라 10건씩 끊어 담는다.
    for i in range(0, len(ordered), 10):
        chunk = ordered[i:i + 10]
        out.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": "\n\n".join(line(r) for r in chunk)}})
    return out


def main():
    days = 60
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = collect(ACCOUNT, since)
    blocks = render(rows, days)
    print(json.dumps(blocks, ensure_ascii=False, indent=1))

    if "--dry" in sys.argv:
        return
    if not SLACK_WEBHOOK:
        print("\n(SLACK_WEBHOOK_URL 미설정 — 출력만 함)", file=sys.stderr)
        return
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=json.dumps({"blocks": blocks}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"\n슬랙 발송: {r.status}", file=sys.stderr)


if __name__ == "__main__":
    main()
