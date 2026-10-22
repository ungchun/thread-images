#!/usr/bin/env python3
"""게시물 정리 후보 목록. 지우지 않는다 — 목록과 지우기 전 지표만 남긴다.

2026-10-22 결정: 한꺼번에 지우지 않는다. 10/12 노출 붕괴 당일에 약 723건을 일괄 삭제했고,
회복을 재는 2주(~11/09) 동안 삭제가 끼면 무엇이 효과였는지 가를 수 없다.
11/09 OKR 판정 뒤에 이 목록을 다시 뽑아 승인받고, 계정당 하루 2~3건씩 천천히 지운다.

후보는 유지·휴식 계정 것만 본다. 프로필을 보러 온 사람에게 같은 문구가 줄줄이 보이는 게 문제라서다.
  dup   같은 계정에 같은 본문이 여러 번 — 조회수가 가장 높은 하나만 남기고 나머지
  low   올린 지 7일 넘었고 조회수 100 미만·좋아요 0
지키는 것: 좋아요 100 이상(터진 글), 조회 5,000 이상이나 링크 클릭 10 이상(아직 일하는 글),
계정당 가장 많이 본 글, 최근 14일 글(회복 측정 중), 리포스트.
중단 국가 계정은 이미 멈췄으니 지워서 얻는 게 없다 — 보지 않는다.

  python3 prune.py     → research/prune_candidates.tsv (지표 스냅샷 포함)

dashboard*.json 수집 창(기본 30일) 안의 글만 본다. 그보다 오래된 글은 `replies.py posts <계정> --days N`으로 따로 본다.
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "research" / "prune_candidates.tsv"
KEEP_LIKES = 100
LOW_VIEWS, LOW_AGE_D = 100, 7
FRESH_D = 14
KEEP_VIEWS, KEEP_CLICKS = 5000, 10


def norm(t):
    return " ".join((t or "").split())


def main():
    st = json.loads((ROOT / "accounts" / "status.json").read_text(encoding="utf-8"))["accounts"]
    live = {a for a, v in st.items() if v.get("state") in ("active", "rest", "official")}
    posts, seen = [], set()
    for f in sorted(ROOT.glob("dashboard*.json")):
        for p in json.loads(f.read_text(encoding="utf-8")).get("posts", []):
            if p["account"] in live and p.get("kind") != "REPOST_FACADE" and p["id"] not in seen:
                seen.add(p["id"])
                posts.append(p)

    now = datetime.now(timezone.utc)
    age = lambda p: (now - datetime.fromisoformat(p["utc"])).days
    views = lambda p: p.get("views") or 0
    by_acc, by_body = defaultdict(list), defaultdict(list)
    for p in posts:
        by_acc[p["account"]].append(p)
        by_body[(p["account"], norm(p.get("text")))].append(p)
    top = {a: max(ps, key=views)["id"] for a, ps in by_acc.items()}

    def protected(p):
        return ((p.get("likes") or 0) >= KEEP_LIKES or views(p) >= KEEP_VIEWS or (p.get("clicks") or 0) >= KEEP_CLICKS
                or p["id"] == top[p["account"]] or age(p) < FRESH_D)

    rows = {}
    for (a, _), ps in by_body.items():
        if len(ps) > 1:
            best = max(ps, key=views)
            for p in ps:
                if p is not best and not protected(p):
                    rows[p["id"]] = (p, f"dup ({len(ps)}회 중 최고 {views(best):,} 아님)")
    for p in posts:
        if p["id"] not in rows and not protected(p) and age(p) >= LOW_AGE_D \
                and views(p) < LOW_VIEWS and not p.get("likes"):
            rows[p["id"]] = (p, "low")

    cols = ["account", "country", "utc", "reason", "views", "likes", "replies", "reposts", "shares", "clicks", "id", "link", "text"]
    lines = ["# 정리 후보 — 지우지 않음. 생성 " + now.isoformat(timespec="minutes") +
             ". 11/09 OKR 판정 뒤 승인받고 계정당 하루 2~3건씩. 지표는 삭제 전 스냅샷",
             "\t".join(cols)]
    for p, why in sorted(rows.values(), key=lambda r: (r[0]["account"], r[0]["utc"])):
        rec = {**p, "reason": why, "text": norm(p.get("text"))[:80]}
        lines.append("\t".join("" if rec.get(c) is None else str(rec.get(c)) for c in cols))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    count = defaultdict(lambda: [0, 0])
    for p, why in rows.values():
        count[p["account"]][0 if why.startswith("dup") else 1] += 1
    print(f"{OUT.relative_to(ROOT)} · 후보 {len(rows)}건 / 유지·휴식 계정 게시물 {len(posts)}건")
    for a in sorted(count):
        print(f"  {a:16} 중복 {count[a][0]:3}  저조 {count[a][1]:3}  (전체 {len(by_acc[a])})")


if __name__ == "__main__":
    main()
