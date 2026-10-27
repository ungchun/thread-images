#!/usr/bin/env python3
"""지정한 계정의 최근 글 조회수만 본다. 대시보드 전체 갱신(수십 분) 대신 방금 올린 글 확인용.

    python3 peek.py daily.life_gram,haru._81a [--hours 72]

파일을 쓰지도 커밋하지도 않는다 — 결과는 실행 로그에만 나온다. 토큰은 creds()가 찾고 값은 출력하지 않는다.
"""
import sys
from datetime import datetime, timezone

from replies import api
from report import insights, meta
from run import creds


def peek(account, hours):
    token, uid = creds(account)
    _, tz = meta(account)
    now = datetime.now(timezone.utc)
    data = api(f"{uid}/threads", token, fields="id,text,timestamp", limit=25)
    for p in data.get("data", []):
        utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        age = (now - utc).total_seconds() / 3600
        if age > hours:
            break
        m = insights(p["id"], token)
        head = " ".join((p.get("text") or "").split())[:30]
        print(f"{account}\t{utc.astimezone(tz):%m/%d %H:%M}\t{age:5.1f}h\t"
              f"조회 {m.get('views', '?')}\t좋아요 {m.get('likes', '?')}\t답글 {m.get('replies', '?')}\t{head}")


def main():
    accs = [a.strip() for a in sys.argv[1].split(",") if a.strip()]
    hours = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 72
    for a in accs:
        try:
            peek(a, hours)
        except Exception as e:
            print(f"{a}\t실패: {type(e).__name__} {str(e)[:80]}")


if __name__ == "__main__":
    main()
