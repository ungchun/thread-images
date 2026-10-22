#!/usr/bin/env python3
"""예약 검사. 푸시 전에 schedule.txt를 계정 운영 상태(accounts/status.json)와 발행 규칙과 대조한다.

10/12에 계정 단위로 노출이 막힌 뒤 정한 규칙(2026-10-22 재정비)이다.
  - 휴식(rest)·중단(paused)·영구정지(banned) 계정, status.json에 없는 계정에는 예약하지 않는다
    휴식 계정은 until 이후 복귀 테스트 2건까지 허용한다
  - 계정당 하루 1개 — 현지 날짜 기준, 이미 올라간 글(posted.log + 대시보드 수집분)까지 센다
  - 막힘·저조 계정에 최근 나간 본문을 또 올리지 않는다. 살아 있는 계정의 반복은 허용한다 —
    pim.pm_02는 같은 문구로 세 번 다 터졌다
  - 같은 30분 회차에 우리 계정 3개 이상을 몰지 않는다. 같은 계정을 3일 연속 같은 현지 시각에 올리지 않는다

  python3 gate.py            schedule.txt 검사. 걸리면 종료 코드 1
  python3 gate.py accounts   발행 가능한 계정 목록

이 검사는 푸시 전 안내다. 실제로 막는 건 run.py가 발행 직전에 한다(hold_reason) —
여기서 놓쳐도 run.py가 줄을 done:hold-<사유>로 세운다. 세워진 줄도 여기서 보여준다.
계정끼리 리포스트는 API로 막을 수 없어 최근 리포스트를 경고로만 보여준다.
"""
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from report import actions_owner, meta, owner
from run import DAILY_CAP, OPEN_STATES, POSTED_LOG, REST_TESTS, parse

ROOT = Path(__file__).resolve().parent
BLOCKED = {"rest": "휴식", "paused": "중단", "banned": "영구정지", "dead": "도달 없음"}
HOLDS = {"rest": "휴식 중", "paused": "중단", "banned": "영구정지", "dead": "도달 없음", "unknown": "status.json에 없음",
         "cap": "하루 1개 초과", "resttest": "복귀 테스트 끝 — 판정 뒤 상태 변경"}
WEAK = {"막힘", "저조"}
STALE_H = 6
SLOT_MAX = 2          # 같은 30분 회차에 우리 계정 최대 2개


def status():
    f = ROOT / "accounts" / "status.json"
    return json.loads(f.read_text(encoding="utf-8")).get("accounts", {}) if f.exists() else {}


def body(text):
    """본문만. 파일은 --- 아래가 답글이다."""
    return " ".join(text.partition("\n---\n")[0].split())


def dashboards():
    """수집 파일 전부. 팀원 파일까지 합친다 — 팀원 계정도 같은 규칙을 지킨다."""
    out = []
    for f in sorted(ROOT.glob("dashboard*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return out


def logged():
    """run.py 발행 기록. 대시보드 수집 전이라도 오늘 나간 글을 센다. [(utc, 계정, post_id)]"""
    if not POSTED_LOG.exists():
        return []
    rows = []
    for line in POSTED_LOG.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if line.startswith("#") or len(f) < 4 or f[2] != "threads":
            continue
        rows.append((f[0], f[1], f[3]))
    return rows


def labels(ds):
    """계정별 48시간 판정 라벨(정상·저조·막힘·휴식·회복). 대시보드가 계산해 둔다."""
    out = {}
    for d in ds:
        for a, h in (d.get("accounts_health") or {}).items():
            if isinstance(h, dict) and h.get("label"):
                out[a] = h["label"]
    return out


def local(utc, account):
    return datetime.fromisoformat(utc).astimezone(meta(account)[1])


def rest_open(info, day):
    """휴식 계정이 그날 복귀 테스트를 올릴 수 있는가."""
    return info.get("state") == "rest" and info.get("until") and day >= date.fromisoformat(info["until"])


def check():
    st, ds = status(), dashboards()
    label = labels(ds)
    day_count = defaultdict(set)          # (계정, 현지날짜) → 게시물 id. posted.log와 수집분이 겹쳐도 한 번만 센다
    times = defaultdict(dict)             # 계정 → {현지날짜: "HH:MM"}
    recent = defaultdict(set)             # 계정 → 최근 본문
    tests = defaultdict(set)              # 휴식 계정이 until 이후 올린 글
    posts = [p for d in ds for p in d.get("posts", []) if p.get("kind") != "REPOST_FACADE"]
    seen = [(p["utc"], p["account"], p["id"]) for p in posts] + logged()
    for utc, a, pid in seen:
        if not (ROOT / "accounts" / a).is_dir():
            continue
        t = local(utc, a)
        day_count[(a, t.date())].add(pid)
        times[a][t.date()] = t.strftime("%H:%M")
        if rest_open(st.get(a, {}), t.date()):
            tests[a].add(pid)
    for p in posts:
        recent[p["account"]].add(body(p.get("text") or ""))

    errs, warns, holds, rows = [], [], [], 0
    slots = defaultdict(list)
    f = ROOT / "schedule.txt"
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        when, a, textfile, _, _, done = parse(line)
        held = [d[len("hold-"):] for d in done if d.startswith("hold-")]
        if held:
            holds.append(f"{a} {local(when, a):%m/%d %H:%M} {textfile} — {HOLDS.get(held[0], held[0])}")
            continue
        if "threads" in done:             # 본문은 이미 나갔다. 수집분·posted.log에서 센다
            continue
        rows += 1
        info = st.get(a)
        t = local(when, a)
        d = t.date()
        tag = f"{a} {d:%m/%d}"
        slot = datetime.fromisoformat(when).astimezone(timezone.utc)
        slots[slot.replace(minute=slot.minute // 30 * 30, second=0, microsecond=0)].append(a)
        if info is None:
            errs.append(f"{tag} — status.json에 없는 계정. 상태를 먼저 정한다")
        elif rest_open(info, d):
            tests[a].add(f"sched:{when}")
            if len(tests[a]) > REST_TESTS:
                errs.append(f"{tag} — 휴식 계정 복귀 테스트는 {REST_TESTS}건까지. 48시간 판정 뒤 상태를 바꾼다")
        elif info.get("state") not in OPEN_STATES:
            until = f" ({info['until']}까지)" if info.get("until") else ""
            errs.append(f"{tag} — {BLOCKED.get(info.get('state'), info.get('state'))} 계정{until}")
        day_count[(a, d)].add(f"sched:{when}")
        if len(day_count[(a, d)]) > DAILY_CAP:
            errs.append(f"{tag} — 하루 {DAILY_CAP}개 상한 초과 ({len(day_count[(a, d)])}건, 현지 날짜 기준)")
        tf = ROOT / textfile
        if tf.exists() and body(tf.read_text(encoding="utf-8")) in recent[a]:
            weak = label.get(a) in WEAK or (info or {}).get("state") == "rest"
            msg = f"{tag} — 최근 나간 본문과 같다 ({textfile})"
            (errs if weak else warns).append(msg + (f" · {label.get(a, '휴식')} 계정이라 막는다" if weak else " · 살아 있는 계정이라 허용"))
        hm = t.strftime("%H:%M")
        times[a][d] = hm
        if all(times[a].get(d - timedelta(days=k)) == hm for k in (1, 2)):
            errs.append(f"{tag} — 3일 연속 같은 현지 시각 {hm}. ±30~60분 흔든다")

    for s, accs in sorted(slots.items()):
        if len(accs) > SLOT_MAX:
            errs.append(f"{s:%m/%d %H:%M} UTC 회차에 {len(accs)}개 몰림 ({', '.join(accs)}) — {SLOT_MAX}개까지")

    gen = [d.get("generated") for d in ds if d.get("generated")]
    if gen:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(min(gen))).total_seconds() / 3600
        if age > STALE_H:
            warns.append(f"가장 오래된 수집이 {age:.0f}시간 전 — 하루 건수가 빠질 수 있다. 대시보드를 먼저 갱신한다")
    cut = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    reposts = {p["account"] for d in ds for p in d.get("posts", [])
               if p.get("kind") == "REPOST_FACADE" and p["utc"] >= cut}
    if reposts:
        warns.append(f"최근 7일 리포스트 — 계정끼리 리포스트하지 않는다: {', '.join(sorted(reposts))}")

    print(f"예약 {rows}건 검사 · 수집 {len(posts)}건 + 발행기록 {len(logged())}건 기준")
    for e in errs:
        print("  ✗", e)
    for w in warns:
        print("  !", w)
    if holds:
        print(f"  보류 {len(holds)}건 (run.py가 세움 — 다시 잡거나 지운다)")
        for h in holds:
            print("    ", h)
    if not errs:
        print("  통과")
    return not errs


def list_accounts():
    st = status()
    label = labels(dashboards())
    today = datetime.now(timezone.utc).date()
    groups = defaultdict(list)
    for d in sorted((ROOT / "accounts").iterdir()):
        if not d.is_dir():
            continue
        a, info = d.name, st.get(d.name)
        tag = f"{meta(a)[0]} {a}" + (f" [{owner(a)}]" if owner(a) != actions_owner() else "") \
            + (f" · {label[a]}" if a in label else "")
        if info is None:
            groups["미등록"].append(tag)
        elif info.get("state") == "rest":
            note = f"복귀 테스트 {REST_TESTS}건 가능" if rest_open(info, today) else f"{info.get('until')}까지"
            groups["휴식"].append(f"{tag} — {note}")
        elif info.get("state") in OPEN_STATES:
            groups["유지"].append(tag)
        else:
            groups[BLOCKED.get(info.get("state"), info.get("state"))].append(tag)
    for g in ["유지", "휴식", "중단", "영구정지", "도달 없음", "미등록"]:
        if groups[g]:
            print(f"{g} {len(groups[g])}개")
            for x in groups[g]:
                print("  ", x)
    print(f"\n[아이디] = 팀원 소유. 2026-10-22부터 팀원 계정도 이 레포 예약으로만 발행한다. 유지 계정은 하루 {DAILY_CAP}개.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["accounts"]:
        list_accounts()
    else:
        sys.exit(0 if check() else 1)
