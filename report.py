#!/usr/bin/env python3
"""스레드 게시물 지표를 모아 슬랙으로 보낸다. cron-job.org가 매일 10시에 부른다.

스레드는 올린 다음 날부터 조회수가 붙기 시작해 며칠에 걸쳐 자란다(대만 계정
실측: 당일 0, 1일 2, 4일 20, 6일 21). 그래서 전날 것만 보면 거의 0이라 의미가
없다. 어제 올린 글과 그 전 게시물을 함께 보고, 어제 대비 증가분을 옆에 붙인다.

증가분은 stats/YYYY-MM-DD.json 스냅샷과 비교해서 낸다. 매 실행마다 오늘 치를
남기므로, 하루만 돌아도 다음날부터 증가분이 나온다.

  python3 report.py            # 발송 (SLACK_WEBHOOK_URL 필요)
  python3 report.py --dry      # 발송·저장 없이 출력만
  python3 report.py --window 14  # 성장 관찰 기간 (기본 14일)

환경변수
  THREADS_ACCOUNTS   계정별 토큰 JSON (없으면 accounts/*/env.sh 사용)
  SLACK_WEBHOOK_URL  없으면 stdout만
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from run import creds

ROOT = Path(__file__).resolve().parent
STATS = ROOT / "stats"
KST = timezone(timedelta(hours=9))
GRAPH = "https://graph.threads.net/v1.0"
METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
PER_COUNTRY = 3     # 나라별로 보여줄 상위 게시물 수


def api(path, token, **params):
    params["access_token"] = token
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def flag(code):
    """ISO 국가코드 → 국기 이모지. 코드 두 글자를 regional indicator로 옮긴다."""
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(ord(c) + 0x1F1A5) for c in code.upper())


def meta(account):
    """accounts/<계정>/meta.txt = "<국가코드> <시간대>". 시각은 현지 기준으로 보여준다."""
    f = ROOT / "accounts" / account / "meta.txt"
    parts = f.read_text(encoding="utf-8").split() if f.exists() else []
    code = parts[0] if parts else "??"
    try:
        tz = ZoneInfo(parts[1]) if len(parts) > 1 else KST
    except ZoneInfoNotFoundError:
        tz = KST
    return code, tz


def insights(post_id, token):
    """지표 6종. 실패하면 빈 dict — 한 건 때문에 리포트 전체를 죽이지 않는다."""
    try:
        data = api(f"{post_id}/insights", token, metric=",".join(METRICS))["data"]
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
        return {}
    return {d["name"]: (d.get("values") or [{}])[0].get("value", 0) for d in data}


def collect(account, since):
    """since(UTC) 이후 게시물 전량의 현재 지표."""
    token, user = creds(account)
    code, tz = meta(account)
    posts = api(f"{user}/threads", token,
                fields="id,text,timestamp,permalink", limit=100).get("data", [])
    rows = []
    for p in posts:
        utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        if utc < since:
            continue
        text = (p.get("text") or "").strip().splitlines()
        rows.append({
            "id": p["id"],
            "account": account,
            "country": code,
            "at": utc.isoformat(),
            "when": utc.astimezone(tz),
            "link": p.get("permalink", ""),
            "text": (text[0][:24] if text else "(본문 없음)"),
            **insights(p["id"], token),
        })
    return rows


def load_prev():
    """가장 최근 스냅샷(오늘 것 제외) → {게시물id: 지표}."""
    if not STATS.is_dir():
        return {}
    today = f"{datetime.now(KST):%Y-%m-%d}.json"
    files = sorted(f for f in STATS.glob("*.json") if f.name != today)
    if not files:
        return {}
    return json.loads(files[-1].read_text(encoding="utf-8"))


def save(rows):
    STATS.mkdir(exist_ok=True)
    snap = {r["id"]: {m: r.get(m, 0) for m in METRICS} for r in rows}
    (STATS / f"{datetime.now(KST):%Y-%m-%d}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def delta(row, prev):
    """어제 대비 조회수 증가분. 스냅샷에 없던 글은 None(비교 불가)."""
    old = prev.get(row["id"])
    return None if old is None else row.get("views", 0) - old.get("views", 0)


def line(r, prev, show_delta=True):
    d = delta(r, prev) if show_delta else None
    grew = f" (+{d})" if d else ""
    return (f"{flag(r['country'])} `{r['account']}` {r['when']:%m-%d %H:%M %Z} (현지)\n"
            f"  <{r['link']}|{r['text']}>\n"
            f"  조회 {r.get('views', 0)}{grew} · 하트 {r.get('likes', 0)} · "
            f"댓글 {r.get('replies', 0)} · 리포스트 {r.get('reposts', 0)} · "
            f"인용 {r.get('quotes', 0)} · 공유 {r.get('shares', 0)}")


def render(rows, prev, window):
    today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    out = [f"*홍보 브리핑 | {datetime.now(KST):%Y-%m-%d}*"]

    fresh = [r for r in rows if yesterday <= r["when"].astimezone(KST) < today]
    out.append("\n*어제 올린 글*")
    if fresh:
        out += [line(r, prev, show_delta=False) for r in
                sorted(fresh, key=lambda x: x["at"])]
    else:
        out.append("없음")

    # 20건을 한 줄로 쏟으면 안 읽힌다. 나라별로 묶어 상위 몇 건만 본다.
    # 계정 간 성과 차이가 이 브리핑의 핵심 정보인데, 섞어놓으면 그게 안 보인다.
    rest = [r for r in rows if r not in fresh and r.get("views", 0)]
    out.append(f"\n*그 전 게시물* (최근 {window}일 · 나라별 조회 상위 {PER_COUNTRY}건)")
    if not rest:
        out.append("없음")
        return "\n".join(out)

    by_country = {}
    for r in rest:
        by_country.setdefault(r["country"], []).append(r)
    # 잘 되는 나라부터. 그 나라 최고 조회수가 기준.
    for code, group in sorted(by_country.items(),
                              key=lambda kv: -max(r.get("views", 0) for r in kv[1])):
        group.sort(key=lambda r: -r.get("views", 0))
        total = sum(r.get("views", 0) for r in group)
        out.append(f"\n{flag(code)} *{code}* — {len(group)}건 · 조회 합계 {total:,}")
        out += [f"  <{r['link']}|{r['text']}> {r['when']:%m-%d}\n"
                f"    조회 {r.get('views', 0):,}{f' (+{delta(r, prev)})' if delta(r, prev) else ''} · "
                f"하트 {r.get('likes', 0)} · 댓글 {r.get('replies', 0)} · "
                f"리포스트 {r.get('reposts', 0)} · 인용 {r.get('quotes', 0)} · "
                f"공유 {r.get('shares', 0)}"
                for r in group[:PER_COUNTRY]]

    return "\n".join(out)


def main():
    window = 14
    if "--window" in sys.argv:
        window = int(sys.argv[sys.argv.index("--window") + 1])
    dry = "--dry" in sys.argv

    since = datetime.now(timezone.utc) - timedelta(days=window)
    rows = []
    for d in sorted((ROOT / "accounts").iterdir()):
        if not d.is_dir():
            continue
        try:
            rows += collect(d.name, since)
        except Exception as e:  # 한 계정이 죽어도 나머지는 보낸다
            print(f"[{d.name}] 수집 실패: {e}", file=sys.stderr)

    prev = load_prev()
    msg = render(rows, prev, window)
    print(msg)

    if dry:
        return
    save(rows)

    if SLACK_WEBHOOK:
        req = urllib.request.Request(
            SLACK_WEBHOOK, data=json.dumps({"text": msg}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"\n슬랙 발송: {r.status}", file=sys.stderr)
    else:
        print("\n(SLACK_WEBHOOK_URL 미설정 — 출력만 함)", file=sys.stderr)


if __name__ == "__main__":
    main()
