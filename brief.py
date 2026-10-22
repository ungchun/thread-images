#!/usr/bin/env python3
"""매일 슬랙 브리핑 — 계정 상태·승인할 제안·규칙 위반·OKR 진척. cron-job.org가 매일 10:00 KST에 부른다.

2026-10-22 재정비 뒤의 루프에서 사람이 할 일은 "승인"뿐이게 만드는 게 목적이다.
API를 부르지 않는다 — dashboard.yml(4시간마다, GitHub schedule)이 모아 둔 dashboard*.json과 okr.json만 읽는다.
그래서 수집이 멈추면 맨 위에 그 사실부터 낸다.

  python3 brief.py          # 발송 (SLACK_WEBHOOK_URL 필요, 없으면 출력만)
  python3 brief.py --dry    # 출력만

예전 report.py(게시물별 조회수 나열)는 그대로 두지만 매일 브리핑은 이것으로 바꿨다.
"""
import json
import os
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
TARGET = {"TH", "JP", "TW", "ID", "VN", "MY"}
STALE_H = 9           # 4시간 수집이 한 회차 빠져도 + 스케줄 지연


def load():
    ds = []
    for f in sorted(ROOT.glob("dashboard*.json")):
        try:
            ds.append({**json.loads(f.read_text(encoding="utf-8")), "_file": f.name})
        except (ValueError, OSError):
            continue
    st = json.loads((ROOT / "accounts" / "status.json").read_text(encoding="utf-8"))["accounts"]
    okr = json.loads((ROOT / "okr.json").read_text(encoding="utf-8"))
    h48f = ROOT / "stats" / "h48.json"
    h48 = json.loads(h48f.read_text(encoding="utf-8")) if h48f.exists() else {}
    return ds, st, okr, h48


def merged(ds, key):
    out = []
    for d in ds:
        out += d.get(key) or []
    return out


def period_of(okr, today):
    ps = okr["periods"]
    return next((p for p in ps if p["start"] <= today.isoformat() <= p["end"]), ps[-1])


def okr_lines(ds, st, okr, h48, today):
    p = period_of(okr, today)
    t, man = p["targets"], p.get("manual", {})
    posts = {x["id"]: x for x in merged(ds, "posts") if x.get("kind") != "REPOST_FACADE"}.values()
    cut48 = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    in_p = [x for x in posts if p["start"] <= x["date"] <= p["end"]]

    # 유지 계정 조회수 중앙값 — 48시간 지난 글만, 48시간 스냅샷이 있으면 그 값
    per = defaultdict(list)
    for x in in_p:
        if st.get(x["account"], {}).get("state") == "active" and x["utc"] <= cut48:
            v = (h48.get(x["id"]) or {}).get("views", x.get("views"))
            if v is not None:
                per[x["account"]].append(v)
    meds = {a: statistics.median(v) for a, v in per.items()}
    med = int(statistics.median(meds.values())) if meds else None
    reached = sum(m >= t["active_median_views"] for m in meds.values())

    # 좋아요 100 이상 — 이번 주(월~일, KST)
    monday = today - timedelta(days=today.weekday())
    week_hits = [x for x in in_p if (x.get("likes") or 0) >= 100 and x.get("country") in TARGET
                 and x["date"] >= monday.isoformat()]

    # 휴식 복귀 — 기간 시작 때 휴식이던 계정 중 active로 돌아왔거나 복귀 판정 pass
    health = {}
    for d in ds:
        health.update(d.get("accounts_health") or {})
    back = [a for a in p.get("rest_accounts", [])
            if st.get(a, {}).get("state") == "active" or (health.get(a) or {}).get("rest_verdict") == "pass"]

    clicks = sum(x.get("clicks") or 0 for x in in_p if x.get("country") in TARGET)
    ok = lambda got, want: "✅" if got is not None and got >= want else "▫️"
    lines = [f"*OKR {p['id']}* ({p['start'][5:]}~{p['end'][5:]}) — {p['objective']}",
             f"{ok(med, t['active_median_views'])} 유지 계정 조회수 중앙값 {med if med is not None else '–'} / {t['active_median_views']:,}"
             f" (시작 {p['baseline']['active_median_views']}, 달성 계정 {reached}/{len(meds)})",
             f"{ok(len(week_hits), t['hits_per_week'])} 이번 주 좋아요 100+ {len(week_hits)} / {t['hits_per_week']}",
             f"{ok(len(back), t['rest_returned'])} 휴식 복귀 {len(back)} / {t['rest_returned']}"
             + (f" ({', '.join(back)})" if back else ""),
             f"▫️ 링크 클릭(대상 국가, 기간 누계 추정) {clicks:,} · 설치 {man.get('installs_target_countries') if man.get('installs_target_countries') is not None else '미입력'}",
             f"{ok(man.get('creators_contacted', 0), t['creators_contacted'])} 크리에이터 연락 {man.get('creators_contacted', 0)}/{t['creators_contacted']}"
             f" · 계약 {man.get('creators_signed', 0)}/{t['creators_signed']} · 게시 {man.get('creator_posts', 0)}/{t['creator_posts']}",
             f"{ok(man.get('official_wallpaper_posts', 0), t['official_wallpaper_posts'])} 공식 계정 {man.get('official_accounts', 0)}/{t['official_accounts']}"
             f" · 배경화면 게시 {man.get('official_wallpaper_posts', 0)}/{t['official_wallpaper_posts']}"]
    if today.isoformat() >= p["end"]:
        lines.append(f"⏰ 오늘이 판정일이다. 결과를 okr.json `result`에 적고 다음 기간을 연다")
    return lines


def holds():
    """run.py가 세운 예약 줄. 자동으로 안 풀리니 사람이 다시 잡거나 지운다."""
    f = ROOT / "schedule.txt"
    out = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
        cols = line.split("\t")
        if len(cols) > 5 and "hold-" in cols[5]:
            why = next(d for d in cols[5].replace("done:", "").split(",") if d.startswith("hold-"))
            out.append(f"{cols[1]} {cols[0][5:16]}Z {why[5:]}")
    return out


def build(today=None):
    ds, st, okr, h48 = load()
    today = today or datetime.now(KST).date()
    lines = [f"*트레이스 스레드 브리핑* {today:%m/%d}"]

    now = datetime.now(timezone.utc)
    stale = [(d["_file"], (now - datetime.fromisoformat(d["generated"])).total_seconds() / 3600)
             for d in ds if d.get("generated")]
    stale = [(n, h) for n, h in stale if h > STALE_H]
    if stale:   # 파일마다 따로 — 팀원 시크릿이 빠지면 그 사람 파일만 낡는다
        lines.append("⚠️ 수집이 낡았다: " + ", ".join(f"{n} {h:.0f}시간 전" for n, h in stale)
                     + " — dashboard 워크플로 기록과 팀원 시크릿을 확인한다. 그 계정들 판정은 낡은 값이다")

    health = {}
    for d in ds:
        health.update(d.get("accounts_health") or {})
    counts = defaultdict(list)
    for a, info in st.items():
        if info.get("state") in ("active", "rest", "official"):
            counts[(health.get(a) or {}).get("label") or "판정 전"].append(a)
    order = ["정상", "회복", "저조", "막힘", "휴식", "판정 전"]
    lines.append("*계정 상태* " + " · ".join(f"{k} {len(counts[k])}" for k in order if counts[k]))
    for k in ("막힘", "저조"):
        if counts[k]:
            lines.append(f"  {k}: {', '.join(sorted(counts[k]))}")

    props = merged(ds, "proposals")
    if props:
        lines.append(f"*승인할 상태 변경 {len(props)}건* — 승인하면 accounts/status.json을 바꾼다")
        for x in props:
            arrow = f"{x['from']} → {x['to']}" + (f" ({x['until']}까지)" if x.get("until") else "")
            lines.append(f"  • {x['account']}: {arrow} — {x['reason']}")

    since = (today - timedelta(days=1)).isoformat()
    vio = [v for v in merged(ds, "violations") if v.get("date", "") >= since]
    if vio:
        by = defaultdict(list)
        for v in vio:
            by[v["kind"]].append(v["account"])
        lines.append(f"*규칙 위반 (어제·오늘) {len(vio)}건*")
        for k, accs in by.items():
            lines.append(f"  • {k}: {', '.join(sorted(set(accs)))}")

    h = holds()
    if h:
        lines.append(f"*보류된 예약 {len(h)}건* — 다시 잡거나 지운다")
        lines += [f"  • {x}" for x in h[:10]]

    hits = [x for x in merged(ds, "hits") if x.get("utc", "") >= (today - timedelta(days=7)).isoformat()]
    if hits:
        lines.append(f"*최근 7일 터진 글 {len(hits)}건* (다음 문구 기준)")
        for x in sorted(hits, key=lambda x: -(x.get("likes") or 0))[:5]:
            first = (x.get("text") or "").splitlines()[0][:40] if x.get("text") else ""
            lines.append(f"  • {x['account']} 좋아요 {x['likes']:,} 조회 {x.get('views') or 0:,} — <{x['link']}|{first}>")

    lines.append("")
    lines += okr_lines(ds, st, okr, h48, today)
    return "\n".join(lines)


def main():
    text = build()
    print(text)
    hook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if "--dry" in sys.argv:
        return
    if not hook:
        print("\n(SLACK_WEBHOOK_URL 미설정 — 출력만 함)", file=sys.stderr)
        return
    req = urllib.request.Request(hook, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"\n슬랙 발송: {r.status}", file=sys.stderr)


if __name__ == "__main__":
    main()
