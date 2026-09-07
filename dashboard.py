#!/usr/bin/env python3
"""대시보드가 읽을 dashboard.json 하나를 만든다.

세 가지만 담는다.
  scheduled  아직 안 나간 예약 (schedule.txt 그대로)
  posts      계정별 게시물 + 지표
  pending    미답변 답글

수집은 계정별로 독립이라 하나가 죽어도 나머지는 담는다.
번역은 하지 않는다 - Actions 안에서 LLM을 못 부른다. 원문만 넘기고
번역이 필요하면 사람이 threads-reply 스킬로 처리한다.

  python3 dashboard.py [--days 30] [--replies-days 14]
"""
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from replies import unanswered
from report import flag, insights, meta
from run import creds, parse
from replies import api, paged, FIELDS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dashboard.json"
METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]


def rounds():
    """라운드 정의 + 그 라운드에 나간 문구 본문. done/<코드><id>.txt 로 찾는다."""
    f = ROOT / "rounds.json"
    if not f.exists():
        return []
    out = []
    for r in json.loads(f.read_text(encoding="utf-8"))["rounds"]:
        bodies = []
        for d in (ROOT / "done", ROOT / "texts"):
            bodies += [t.read_text(encoding="utf-8").strip()
                       for t in d.glob(f"*{r['id']}.txt")] if d.is_dir() else []
        out.append({**r, "bodies": bodies})
    return out


def tag_rounds(posts, rs):
    """게시물에 라운드를 붙인다. 본문 첫 줄 + 발행일로 고른다.

    같은 문구를 재사용한 라운드(03과 05)가 있어 본문만으로는 못 가른다.
    후보가 여럿이면 rounds.json의 날짜에 가장 가까운 것을 쓴다.
    """
    from datetime import date
    cand = {}
    for r in rs:
        for b in r["bodies"]:
            first = b.splitlines()[0].strip() if b else ""
            if first:
                cand.setdefault(first, []).append(r)
    for p in posts:
        first = (p["text"].splitlines()[0].strip() if p["text"] else "")
        rs_hit = cand.get(first, [])
        if not rs_hit:
            p["round"] = None
        elif len(rs_hit) == 1:
            p["round"] = rs_hit[0]["id"]
        else:
            d = date.fromisoformat(p["date"])
            p["round"] = min(rs_hit,
                             key=lambda r: abs((date.fromisoformat(r["date"]) - d).days))["id"]
    return posts


def compare(posts, rs):
    """라운드별 성과. 계정 체력이 100배씩 차이나므로 단순 평균은 못 쓴다.

    같은 계정 안에서 그 계정의 라운드 평균 대비 몇 배였는지(배수)를 내고,
    그 배수들의 중앙값을 라운드 점수로 삼는다. 계정 규모가 상쇄된다.
    """
    import statistics
    tagged = [p for p in posts if p.get("round")]
    by_acc = {}
    for p in tagged:
        by_acc.setdefault(p["account"], []).append(p)

    ratios = {}
    for acc, ps in by_acc.items():
        seen = {p["round"] for p in ps}
        if len(seen) < 2:          # 한 라운드만 있는 계정은 비교 불가
            continue
        base = statistics.mean(p.get("views", 0) for p in ps) or 1
        for p in ps:
            ratios.setdefault(p["round"], []).append(p.get("views", 0) / base)

    out = []
    for r in rs:
        got = [p for p in tagged if p["round"] == r["id"]]
        rr = ratios.get(r["id"], [])
        out.append({
            "id": r["id"], "date": r["date"], "type": r["type"],
            "kr": r["kr"], "note": r.get("note", ""),
            "posts": len(got),
            "views": sum(p.get("views", 0) for p in got),
            "likes": sum(p.get("likes", 0) for p in got),
            "median": int(statistics.median([p.get("views", 0) for p in got])) if got else 0,
            "score": round(statistics.median(rr), 2) if rr else None,
            "sample": len(rr),
        })
    return out


def skiplist(account):
    """답하지 않기로 한 답글 id. accounts/<계정>/skip.txt 한 줄에 "id  # 이유"."""
    f = ROOT / "accounts" / account / "skip.txt"
    out = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rid, _, why = line.partition("#")
        out[rid.strip()] = why.strip()
    return out


def accounts():
    return sorted(d.name for d in (ROOT / "accounts").iterdir() if d.is_dir())


def scheduled():
    """아직 안 나간 예약. 시각은 계정 현지로도 같이 준다."""
    f = ROOT / "schedule.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        when, acc, textfile, tw, ig, done = parse(line)
        code, tz = meta(acc)
        utc = datetime.fromisoformat(when)
        body = ""
        p = ROOT / textfile
        if p.exists():
            body = p.read_text(encoding="utf-8").strip()
        out.append({
            "account": acc, "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "local": utc.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "text": body, "media": tw, "done": sorted(done),
        })
    return sorted(out, key=lambda r: r["utc"])


def posts_of(account, days):
    """계정의 최근 게시물 + 지표."""
    token, uid = creds(account)
    code, tz = meta(account)
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    data = api(f"{uid}/threads", token,
               fields="id,text,timestamp,permalink,media_type", limit=100)
    out = []
    for p in data.get("data", []):
        utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        if utc.timestamp() < since:
            continue
        m = insights(p["id"], token)
        out.append({
            "id": p["id"], "account": account, "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "date": utc.astimezone(tz).strftime("%Y-%m-%d"),
            "local": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "text": (p.get("text") or "").strip(),
            "kind": p.get("media_type", ""),
            "link": p.get("permalink", ""),
            **{k: m.get(k, 0) for k in METRICS},
        })
    return out


def pending_of(account, posts, days):
    """최근 게시물들의 미답변 답글. 오래된 글은 안 본다 - 답글이 수백 건이라 느리다."""
    cut = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    for p in posts:
        if datetime.fromisoformat(p["utc"]).timestamp() < cut:
            continue
        for r in unanswered(account, p["id"]):
            out.append({**r, "account": account, "country": p["country"],
                        "flag": p["flag"], "post": p["id"],
                        "post_text": p["text"].splitlines()[0][:40] if p["text"] else "",
                        "post_link": p["link"]})
    return out


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    rdays = (int(sys.argv[sys.argv.index("--replies-days") + 1])
             if "--replies-days" in sys.argv else 14)

    all_posts, all_pending, all_skipped, errors = [], [], [], []
    for a in accounts():
        try:
            ps = posts_of(a, days)
            all_posts += ps
        except Exception as e:
            errors.append(f"{a} 게시물: {e}")
            continue
        try:
            skip = skiplist(a)
            for r in pending_of(a, ps, rdays):
                if r["id"] in skip:
                    all_skipped.append({**r, "why": skip[r["id"]]})
                else:
                    all_pending.append(r)
        except Exception as e:
            errors.append(f"{a} 답글: {e}")

    rs = rounds()
    all_posts = tag_rounds(all_posts, rs)
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "rounds": compare(all_posts, rs),
        "plan": json.loads((ROOT / "rounds.json").read_text(encoding="utf-8")).get("plan", []),
        "window_days": days,
        "scheduled": scheduled(),
        "posts": sorted(all_posts, key=lambda r: r["utc"], reverse=True),
        "pending": sorted(all_pending, key=lambda r: r["when"]),
        "skipped": sorted(all_skipped, key=lambda r: r["when"]),
        "errors": errors,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"예약 {len(data['scheduled'])} · 게시물 {len(data['posts'])} · "
          f"미답변 {len(data['pending'])} · 답안함 {len(data['skipped'])} · 오류 {len(errors)}")
    for e in errors:
        print(" ", e)


if __name__ == "__main__":
    main()
