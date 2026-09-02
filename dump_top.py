#!/usr/bin/env python3
"""조회수 상위 게시물의 본문 전문을 뽑는다. 일회성 조사용."""
import sys
from datetime import datetime, timedelta, timezone
from report import api, creds, meta, insights, ROOT

since = datetime.now(timezone.utc) - timedelta(days=int(sys.argv[1] if len(sys.argv) > 1 else 60))
rows = []
for d in sorted((ROOT / "accounts").iterdir()):
    if not d.is_dir():
        continue
    try:
        token, user = creds(d.name)
        code, tz = meta(d.name)
        for p in api(f"{user}/threads", token,
                     fields="id,text,timestamp,permalink", limit=100).get("data", []):
            utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
            if utc < since:
                continue
            ins = insights(p["id"], token)
            rows.append((ins.get("views", 0), code, d.name, utc, p.get("permalink", ""),
                         (p.get("text") or "").strip(), ins))
    except Exception as e:
        print(f"[{d.name}] 실패: {e}", file=sys.stderr)

for v, code, acct, utc, link, text, ins in sorted(rows, reverse=True, key=lambda r: r[0])[:10]:
    print("=" * 70)
    print(f"{code} / {acct} / {utc:%Y-%m-%d %H:%M} UTC")
    print(f"조회 {v:,} · 하트 {ins.get('likes',0):,} · 댓글 {ins.get('replies',0):,} "
          f"· 리포스트 {ins.get('reposts',0):,} · 인용 {ins.get('quotes',0):,} · 공유 {ins.get('shares',0):,}")
    print(link)
    print("-" * 70)
    print(text)
    print()
