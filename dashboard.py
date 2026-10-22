#!/usr/bin/env python3
"""대시보드가 읽을 dashboard.json 하나를 만든다.

세 가지만 담는다.
  scheduled  아직 안 나간 예약 (schedule.txt 그대로)
  posts      계정별 게시물 + 지표 (insights 실패 글은 지표가 None)
  pending    미답변 답글
계정 운영(2026-10-22 재정비)용으로 accounts_health·proposals·violations·hits를 같이 낸다.
48시간 조회수는 stats/h48.json에 글마다 한 번 적는다(Actions에서만 저장).

수집은 계정별로 독립이라 하나가 죽어도 나머지는 담는다.
번역은 하지 않는다 - Actions 안에서 LLM을 못 부른다. 원문만 넘기고
번역이 필요하면 사람이 threads-reply 스킬로 처리한다.

  python3 dashboard.py [--days 30] [--replies-days 14] [--owner <GitHub 아이디>]

--owner 계정만 모아 그 사람 파일(report.data_file)에 쓴다. 기본은 Actions 주인 → dashboard.json.
팀원은 serve.py 갱신 버튼이 로컬 토큰(env.sh)으로 이걸 돌리고 자기 파일만 푸시한다.
Actions(dashboard.yml)는 주인과 팀원(THREADS_<아이디> 시크릿)을 한 잡에서 차례로 돈다.
  python3 dashboard.py --merge-h48 <파일>   stats/h48.json에 다른 기록을 합친다 (커밋 직전)
"""
import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from replies import unanswered
from report import account_project, actions_owner, data_file, flag, insights, meta, owner
from run import creds, parse
from replies import api, paged, FIELDS

ROOT = Path(__file__).resolve().parent
METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]


def known(ps):
    """조회수를 받은 글만. insights가 실패한 글은 views가 None이다 — 0으로 세면 막힌 글처럼 보인다."""
    return [p for p in ps if p.get("views") is not None]


def rounds(proj="trace"):
    """라운드 정의 + 그 라운드에 나간 문구 본문. <코드><id>.txt 또는 <id>_<언어>.txt 로 찾는다.

    변종은 두 방식. (1) 파일명 접미 a/b → A/B: 문구 A/B. (2) 파일 최상위 또는 라운드의
    arms {라벨: [계정]}: 같은 문구를 계정 그룹별로 다른 경로·조건에 올릴 때. tag_rounds가 계정으로 붙인다.
    본문은 --- 앞까지만 잰다 — 문라이트·코르텍스 파일은 뒤에 답글 블록이 붙어 있어 전체를 대조하면 안 맞는다.
    """
    f = rounds_file(proj)
    if not f.exists():
        return []
    rj = json.loads(f.read_text(encoding="utf-8"))
    top_arms = rj.get("arms") or {}
    out = []
    for r in rj["rounds"]:
        bodies = []          # [(본문, 변종)] — 변종은 파일명 접미 a/b → A/B. 짝(a·b 둘 다)이 있을 때만.
        files = [t for d in text_dirs(proj) if d.is_dir()
                 for t in list(d.glob(f"*{r['id']}.txt")) + list(d.glob(f"*{r['id']}[ab].txt"))
                 + list(d.glob(f"{r['id']}_*.txt"))
                 # 라운드 전용 폴더(texts/trace15/t15a_kr.txt)도 찾는다. glob은 하위를 안 본다.
                 + [t for t in d.rglob(f"{r['id']}_*.txt") if t.parent != d]]
        stems = {t.stem for t in files}
        for t in files:
            pair = t.stem[:-1] + ("b" if t.stem[-1] == "a" else "a")
            var = t.stem[-1].upper() if t.stem[-1] in "ab" and pair in stems else None
            body = t.read_text(encoding="utf-8").partition("\n---\n")[0].strip()
            bodies.append((body, var))
        # 최상위 arms 는 '이번 실험' 라운드에만 상속한다. 옛 라운드까지 갈래로 집계되면
        # A/B 변형과 섞여 점수가 오염된다. 라운드가 arms 를 직접 갖거나, arms_from 이후 날짜일 때만.
        inherit = top_arms if (rj.get("arms_from") and r["date"] >= rj["arms_from"]) else {}
        out.append({**r, "bodies": bodies, "arms": r.get("arms") or inherit})
    return out


def _norm(s):
    return " ".join((s or "").replace("||", "").split())   # ||스포일러|| 표시는 발행 시 제거되므로 대조에서도 뺀다


def tag_rounds(posts, rs):
    """게시물에 라운드를 붙인다. 본문 첫 줄 + 발행일로 고른다.

    같은 문구를 재사용한 라운드(03과 05)가 있어 본문만으로는 못 가른다.
    후보가 여럿이면 rounds.json의 날짜에 가장 가까운 것을 쓴다.
    """
    from datetime import date
    full, first = {}, {}     # 본문 전체 매칭 우선. A/B가 첫 줄이 같은 언어(es·fr·hi)가 있어서다.
    for r in rs:
        for b, var in r["bodies"]:
            if not b:
                continue
            full.setdefault(_norm(b), []).append((r, var))
            first.setdefault(b.splitlines()[0].strip(), []).append((r, None))
    for p in posts:
        txt = p["text"] or ""
        d = date.fromisoformat(p["date"])
        hits = full.get(_norm(txt)) or [
            h for h in first.get(txt.splitlines()[0].strip() if txt else "", [])
            if abs((date.fromisoformat(h[0]["date"]) - d).days) <= 3]   # 첫 줄 폴백은 라운드 날짜 ±3일만
        if not hits:
            p["round"] = p["variant"] = None
            continue
        if len(hits) > 1:
            hits = [min(hits, key=lambda h: abs((date.fromisoformat(h[0]["date"]) - d).days))]
        r = hits[0][0]
        # 문구를 과거 라운드에서 재사용하면 옛 게시물이 새 라운드로 잡힌다(본문이 같으므로).
        # arms 를 쓰는 경로 실험 라운드는 그 라운드 날짜 이후 글만 센다.
        if r.get("arms") and d < date.fromisoformat(r["date"]):
            p["round"] = p["variant"] = None
            continue
        p["round"], p["variant"] = r["id"], hits[0][1]
        arms = r.get("arms") or {}
        if arms:   # 갈래 실험: 변종은 문구가 아니라 계정이 속한 그룹
            p["variant"] = next((k for k, accs in arms.items() if p["account"] in accs), p["variant"])
    return posts


def baselines(by_acc):
    """계정별 기준값. 도달(조회수)과 반응(하트율) 둘 다 중앙값으로 잡는다.

    평균을 쓰면 그 계정의 폭발 한 건이 기준을 끌어올려 자기 배수를 깎고
    같은 계정의 다른 라운드 배수까지 전부 눌러버린다. 실측: 일본 aoi.02_의
    32,245건이 평균 기준 6.39배, 중앙값 기준 25.6배로 4배 차이가 났다.
    중앙값은 폭발에 흔들리지 않는다.
    """
    import statistics
    out = {}
    for acc, ps in by_acc.items():
        views = [p["views"] for p in known(ps)] or [0]
        # 하트율은 조회가 0이면 정의되지 않는다
        ers = [(p.get("likes") or 0) / p["views"] for p in known(ps) if p["views"] > 0]
        out[acc] = {
            "views": statistics.median(views) or 1,
            "er": statistics.median(ers) if ers else None,
        }
    return out


def ratios_of(p, base):
    """한 게시물의 (도달배수, 반응배수). 나라·계정마다 기준선이 달라 배수로 환산한다.

    반응배수를 따로 두는 이유: 조회수는 알고리즘이 얼마나 밀어줬는가이고
    하트율은 본 사람이 얼마나 반응했는가다. 8라운드에서 둘이 정반대를
    가리켰다(조회는 A 우세, 하트율은 B가 두 배). 나라별 하트율 기준선은
    인도네시아 1.58%와 이탈리아 0.09%로 열 배 넘게 벌어진다.
    """
    reach = (p.get("views") or 0) / base["views"]
    er_base = base["er"]
    if not er_base or not p.get("views"):
        return reach, None
    return reach, ((p.get("likes") or 0) / p["views"]) / er_base


def compare(posts, rs):
    """라운드별 성과. 계정 체력이 100배씩 차이나므로 단순 평균은 못 쓴다.

    같은 계정 안에서 그 계정 평소(중앙값) 대비 몇 배였는지를 내고,
    그 배수들의 중앙값을 라운드 점수로 삼는다. 계정 규모가 상쇄된다.
    도달(조회수)과 반응(하트율)을 따로 낸다 — rounds.json의 판정 규칙 참조.
    """
    import statistics
    tagged = [p for p in posts if p.get("round")]
    by_acc = {}
    for p in tagged:
        by_acc.setdefault(p["account"], []).append(p)
    # 기준선은 태깅 여부와 무관하게 그 계정의 전체 이력이다. 태깅된 글만 쓰면 라운드
    # 하나짜리 계정은 자기 자신이 기준이 되어 배수가 1.0 근처에 붙고, "평소 대비"가 안 된다.
    hist = {}
    for p in posts:
        hist.setdefault(p["account"], []).append(p)
    base = baselines(hist)

    reach, resp = {}, {}
    for acc, ps in by_acc.items():
        if len(hist.get(acc, [])) < 3:   # 이력 3건 미만이면 중앙값이 불안정
            continue
        for p in known(ps):
            a, b = ratios_of(p, base[acc])
            reach.setdefault(p["round"], []).append(a)
            if b is not None:
                resp.setdefault(p["round"], []).append(b)

    out = []
    for r in rs:
        got = [p for p in tagged if p["round"] == r["id"]]
        rr = reach.get(r["id"], [])
        er = resp.get(r["id"], [])
        out.append({
            "id": r["id"], "date": r["date"], "type": r["type"],
            "kr": r["kr"], "note": r.get("note", ""),
            "posts": len(got),
            "views": sum(p.get("views") or 0 for p in got),
            "likes": sum(p.get("likes") or 0 for p in got),
            "median": int(statistics.median([p["views"] for p in known(got)])) if known(got) else 0,
            "score": round(statistics.median(rr), 2) if rr else None,
            "sample": len(rr),
            "er_score": round(statistics.median(er), 2) if er else None,
            "er_sample": len(er),
            "variants": variant_scores(got, hist, base),
        })
    return out


def variant_scores(got, by_acc, base):
    """라운드 안 A/B 변종별 점수. 기준은 compare()와 같은 그 계정 평소 중앙값.

    판정은 도달·반응 두 지표가 같은 쪽을 가리킬 때만 낸다(rounds.json 규칙).
    """
    import statistics
    vs = {}
    for p in got:
        if p.get("variant"):
            vs.setdefault(p["variant"], []).append(p)
    out = {}
    for k, ps in sorted(vs.items()):
        rr, er = [], []
        for p in known(ps):
            if len(by_acc.get(p["account"], [])) < 3:   # by_acc 는 전체 이력(hist)
                continue
            a, b = ratios_of(p, base[p["account"]])
            rr.append(a)
            if b is not None:
                er.append(b)
        out[k] = {"posts": len(ps),
                  "median": int(statistics.median([p["views"] for p in known(ps)])) if known(ps) else 0,
                  "score": round(statistics.median(rr), 2) if rr else None,
                  "sample": len(rr),
                  "er_score": round(statistics.median(er), 2) if er else None,
                  "er_sample": len(er)}
    return out


def arm_scores(posts, rs):
    """arms 가 있는 라운드들의 갈래별 점수. 관측 카드의 현재값으로 쓴다.

    갈래는 계정 그룹(=발행 경로)이라 라운드를 넘나들어 합친다. 점수는 compare()와 같은
    "그 계정 평소(전체 이력 중앙값) 대비 몇 배"의 중앙값. 1.0 이 평소, 0.05 면 도달이 꺼진 것.
    """
    import statistics
    armed = {r["id"] for r in rs if r.get("arms")}
    if not armed:
        return {}
    hist = {}
    for p in posts:
        hist.setdefault(p["account"], []).append(p)
    base = baselines(hist)
    by_arm, accs = {}, {}
    for p in known(posts):
        if p.get("round") in armed and p.get("variant") and len(hist.get(p["account"], [])) >= 3:
            r = ratios_of(p, base[p["account"]])[0]
            by_arm.setdefault(p["variant"], []).append(r)
            accs.setdefault(p["variant"], {}).setdefault(p["account"], []).append(round(r, 2))
    return {k: {"score": round(statistics.median(v), 2), "n": len(v), "accounts": accs[k]}
            for k, v in by_arm.items()}


def account_status():
    """계정 운영 상태. accounts/status.json이 단일 출처다."""
    f = ROOT / "accounts" / "status.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8")).get("accounts", {})


BLOCK_VIEWS, BLOCK_RUN = 100, 3      # 48시간 조회수 100 미만 3회 연속 → 막힘
RECOVER_VIEWS, RECOVER_RUN = 500, 2  # 500 이상 2회 연속 → 회복 (막힌 적이 있을 때)
LOW_RUN = 3                          # 막힘은 아닌데 최근 3건 중앙값이 RECOVER_VIEWS 미만 → 저조
REST_DAYS = 14                       # 막힘 → 휴식 기간
REST_TEST_POSTS = 2                  # 복귀 테스트: until 이후 첫 2건 중 하나라도 500 이상이면 복귀 (스펙은 1건, 10/22 주인 승인으로 2건)
# 평소(중앙값)는 이 날 이후 글로만 잡는다. 10/12에 노출이 계정 단위로 무너져 그 전 글은
# 중앙값이 수천이다. 섞으면 평소가 부풀어 지금 글의 배수·터짐률이 전부 바닥에 붙는다.
HEALTH_FROM = "2026-10-13"

H48_FILE = ROOT / "stats" / "h48.json"
H48_MIN, H48_MAX = 48, 60   # 수집이 6시간마다라 이 12시간 창에 두 번 걸린다
H48_KEEP_DAYS = 45          # 집계 창(30일)보다 길게만 두면 된다. 파일이 커지지 않게 자른다
H48 = {}                    # main이 채운다. health()의 기본값


def load_h48(path=H48_FILE):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_h48(h48, path=H48_FILE):
    """한 줄에 한 글. 6시간마다 커밋되니 diff가 추가된 줄만 보이게 한다."""
    Path(path).parent.mkdir(exist_ok=True)
    body = ",\n".join(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                      for k, v in sorted(h48.items()))
    Path(path).write_text("{\n" + body + "\n}\n", encoding="utf-8")


def record_h48(h48, posts, now=None):
    """48시간 조회수를 글마다 한 번만 적는다. API는 지금 값만 주므로 48~60시간 사이에 본 값을 48시간 값으로 쓴다.
    60시간 넘도록 못 적은 글(수집이 빠졌거나 이 기록 이전 글)은 지금 값을 approx로 적는다 — 늦게 붙은 조회가 섞인다.
    조회수를 못 받은 글(None)은 다음 수집에 다시 본다."""
    now = now or datetime.now(timezone.utc)
    added = 0
    for p in posts:
        if p["id"] in h48 or p.get("views") is None or p.get("kind") == "REPOST_FACADE":
            continue
        age = (now - datetime.fromisoformat(p["utc"])).total_seconds() / 3600
        if age < H48_MIN:
            continue
        h48[p["id"]] = {"views": p["views"], "likes": p.get("likes") or 0, "reposts": p.get("reposts") or 0,
                        "at": now.isoformat(timespec="seconds"), "age_h": round(age, 1), "approx": age > H48_MAX}
        added += 1
    return added


def prune_h48(h48, now=None):
    cut = ((now or datetime.now(timezone.utc)) - timedelta(days=H48_KEEP_DAYS)).isoformat()
    for k in [k for k, r in h48.items() if r.get("at", "") < cut]:
        del h48[k]


def merge_h48(a, b):
    """같은 글이 양쪽에 있으면 진짜 48시간 값(approx 아님)을, 둘 다 같으면 먼저 적은 쪽을 남긴다.
    한 잡에서 주인별로 여러 번 돌고, 커밋 전에 원격 것과도 합치므로 덮어쓰면 기록이 사라진다."""
    out = dict(a)
    for k, r in b.items():
        o = out.get(k)
        if o is None or (bool(o.get("approx")), o.get("at", "")) > (bool(r.get("approx")), r.get("at", "")):
            out[k] = r
    return out


def health(rows, info, h48=None, now=None):
    """계정 상태 — 정상·저조·막힘·휴식·회복 (2026-10-22 재정비 기준). 한 계정의 전 프로젝트 글을 넣는다.

    48시간 조회수로 판정한다. stats/h48.json 값을 쓰고, 없으면 지금 조회수로 근사한다(approx에 건수).
    48시간이 안 된 글과 조회수를 못 받은 글(None)은 판정에서 뺀다 — 0으로 세면 막힘으로 오판한다.
    평소 = HEALTH_FROM 이후 판정 글의 조회수 중앙값(없으면 전체). 하트율·터짐률(평소 2배 이상)도 같은 글로 잰다.
    저조 = 막힘은 아니지만 최근 3건 중앙값이 회복 기준 미만. 이게 없으면 [4, 0, 0]도 정상으로 떴다.
    휴식 계정은 until 이후 첫 2건이 복귀 테스트다 — 하나라도 500 이상이면 pass, 둘 다 미만이면 fail.
    """
    import statistics
    h48 = H48 if h48 is None else h48
    cut = ((now or datetime.now(timezone.utc)) - timedelta(hours=H48_MIN)).isoformat()
    judged = []
    for p in sorted(rows, key=lambda p: p["utc"]):
        if p["utc"] > cut or p.get("kind") == "REPOST_FACADE":
            continue
        r = h48.get(p["id"])
        m = r or p
        if m.get("views") is None:
            continue
        judged.append({"date": p["date"], "views": m["views"], "likes": m.get("likes") or 0,
                       "approx": bool(not r or r.get("approx"))})
    v = [j["views"] for j in judged]
    out = {"n": len(v)}
    if v:
        pool = [j for j in judged if j["date"] >= HEALTH_FROM] or judged
        base = statistics.median(j["views"] for j in pool)
        views = sum(j["views"] for j in pool)
        out.update(last=v[-1], recent=v[-LOW_RUN:], base=int(base),
                   approx=sum(j["approx"] for j in judged),
                   multiple=round(v[-1] / base, 2) if base else None,
                   like_rate=round(sum(j["likes"] for j in pool) / views * 100, 2) if views else None,
                   burst=round(sum(j["views"] >= 2 * base for j in pool) / len(pool), 2) if base else 0)

    def runs(i, ok, k):   # i에서 끝나는 k개가 전부 ok인가
        return i + 1 >= k and all(ok(x) for x in v[i + 1 - k:i + 1])

    low = lambda x: x < BLOCK_VIEWS
    high = lambda x: x >= RECOVER_VIEWS
    if info.get("state") == "rest":
        label = "휴식"
        until = info.get("until")
        test = [j["views"] for j in judged if until and j["date"] >= until][:REST_TEST_POSTS]
        if test:
            out["rest_test"] = test
            out["rest_verdict"] = ("pass" if any(high(x) for x in test)
                                   else "fail" if len(test) >= REST_TEST_POSTS else None)
    elif v and runs(len(v) - 1, low, BLOCK_RUN):
        label = "막힘"
    elif (v and runs(len(v) - 1, high, RECOVER_RUN)
          and any(runs(i, low, BLOCK_RUN) for i in range(len(v) - RECOVER_RUN))):
        label = "회복"
    elif v and statistics.median(v[-LOW_RUN:]) < RECOVER_VIEWS:
        label = "저조"
    else:
        label = "정상" if v else ""
    out["label"] = label
    return out


def accounts_health(posts, accs, st=None):
    """계정별 상태. read_signals는 프로젝트별이라 글이 갈리면 표본이 줄어 판정이 흔들린다 — 여기선 계정의 전 글로 잰다."""
    st = account_status() if st is None else st
    out = {}
    for a in accs:
        info = st.get(a, {})
        out[a] = {**health([p for p in posts if p["account"] == a], info),
                  "state": info.get("state", "active"), "until": info.get("until")}
    return out


def proposals(acc_health, posts, sched, st=None, today=None):
    """status.json을 바꾸자는 제안. 쓰지는 않는다 — 사람이 보고 status.json을 고친다.

    막힘인 유지 계정 → 2주 휴식. 휴식 계정 복귀 테스트 pass → 유지, fail → 중단.
    휴식이 끝났는데 테스트 글이 올라가지도 예약되지도 않았으면 예약하라고 알린다.
    날짜는 계정 현지 기준이다(gate.py가 until을 현지 날짜로 본다).
    """
    from datetime import date
    st = account_status() if st is None else st
    out = []
    for a, h in sorted(acc_health.items()):
        info = st.get(a, {})
        state, until = info.get("state", "active"), info.get("until")
        day = today or datetime.now(meta(a)[1]).date()
        if state == "active" and h.get("label") == "막힘":
            out.append({"account": a, "from": "active", "to": "rest",
                        "until": (day + timedelta(days=REST_DAYS)).isoformat(),
                        "reason": f"48시간 조회수 {BLOCK_VIEWS} 미만 {BLOCK_RUN}회 연속 ({', '.join(map(str, h.get('recent', [])))})"})
        elif state == "rest" and until:
            test = ", ".join(map(str, h.get("rest_test", [])))
            done = sum(p["account"] == a and p["date"] >= until and p.get("kind") != "REPOST_FACADE" for p in posts)
            queued = any(s["account"] == a and s["local"][:10] >= until for s in sched)
            if h.get("rest_verdict") == "pass":
                out.append({"account": a, "from": "rest", "to": "active",
                            "reason": f"복귀 테스트 통과 — 48시간 조회수 {test} ({RECOVER_VIEWS} 이상 있음)"})
            elif h.get("rest_verdict") == "fail":
                out.append({"account": a, "from": "rest", "to": "paused",
                            "reason": f"복귀 테스트 {REST_TEST_POSTS}건 모두 {RECOVER_VIEWS} 미만 ({test})"})
            elif day >= date.fromisoformat(until) and not done and not queued:
                out.append({"account": a, "from": "rest", "to": "rest",
                            "reason": f"복귀 테스트 예약 필요 — {until} 휴식 끝, 올라간 글도 예약도 없음"})
            elif done == 1 and len(h.get("rest_test", [])) == 1 and not queued:   # 첫 건이 500 미만으로 판정됐다
                out.append({"account": a, "from": "rest", "to": "rest",
                            "reason": f"두 번째 복귀 테스트 예약 필요 — 첫 건 48시간 조회수 {test}"})
    return out


# posted.log는 run.py가 이날부터 적는다. 그 전 글은 대조할 기록이 없다.
LOOP_FROM = "2026-10-23"
# 발행 규칙(하루 1개·휴식·중단·리포스트 금지) 검사 시작일. 10/22 당일 글은 재정비 전에 예약된 것이다.
RULES_FROM = "2026-10-23"


def posted_log(path=None):
    """run.py가 Threads 본문 발행마다 남기는 기록(TSV: utc account platform post_id textfile).
    → (게시물 id 집합, 첫 기록 UTC). 파일이 없거나 비었으면 None — 대조를 건너뛴다."""
    try:
        lines = Path(path or ROOT / "posted.log").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    ids, first = set(), None
    for line in lines:
        c = line.split("\t")
        if line.startswith("#") or len(c) < 4 or not c[3].strip():
            continue
        try:
            t = datetime.fromisoformat(c[0].strip().replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
        ids.add(c[3].strip())
        first = min(first or t, t)
    return (ids, first) if ids else None


def violations(posts, st=None, log=None):
    """규칙 위반·루프 밖 발행. 전 계정이 이 레포 Actions(run.py)로만 올리기로 했다(10/22 Plan A).
    posted.log에 없는 글은 다른 경로로 올라간 것이다. log가 None이면 그 대조만 건너뛴다."""
    from collections import defaultdict
    st = account_status() if st is None else st
    out = []

    def add(kind, p, detail):
        out.append({"kind": kind, "account": p["account"], "date": p["date"], "utc": p["utc"],
                    "detail": detail, "link": p.get("link", "")})

    own = [p for p in posts if p.get("kind") != "REPOST_FACADE"]
    if log:
        ids, first = log
        start = max(LOOP_FROM, first)   # 로그가 늦게 시작했으면 그 전 글은 묻지 않는다
        for p in own:
            if p["utc"] >= start and p["id"] not in ids:
                add("루프 밖 발행", p, "posted.log에 없다 — Actions run.py 밖에서 올라간 글")
    day = defaultdict(list)
    after = defaultdict(list)
    for p in sorted(own, key=lambda p: p["utc"]):
        if p["date"] < RULES_FROM:
            continue
        day[(p["account"], p["date"])].append(p)
        info = st.get(p["account"], {})
        state, until = info.get("state", "active"), info.get("until")
        if state in ("paused", "banned", "dead"):
            add("중단 계정 발행", p, f"상태 {state}")
        elif state == "rest" and until and p["date"] < until:
            add("휴식 중 발행", p, f"{until}까지 휴식")
        elif state == "rest" and until:
            after[p["account"]].append(p)
            if len(after[p["account"]]) > REST_TEST_POSTS:
                add("복귀 테스트 초과", p, f"휴식 뒤 테스트는 {REST_TEST_POSTS}건까지 — 판정 후 상태부터 바꾼다")
    for (a, d), ps in day.items():
        if len(ps) > 1:
            add("하루 상한 초과", ps[-1], f"현지 {d}에 {len(ps)}건 (계정당 하루 1개)")
    for p in posts:
        if p.get("kind") == "REPOST_FACADE" and p["date"] >= RULES_FROM:
            add("리포스트", p, "계정끼리 리포스트하지 않는다")
    return sorted(out, key=lambda r: r["utc"], reverse=True)


HIT_LIKES = 100


def hits(posts):
    """좋아요 100 이상 글. 다음 회차 문구의 기준(스펙 §5) — threads 스킬이 여기서 베이스를 고른다."""
    keep = ["account", "country", "project", "utc", "views", "likes", "reposts", "text", "link"]
    rows = [p for p in posts if (p.get("likes") or 0) >= HIT_LIKES and p.get("kind") != "REPOST_FACADE"]
    return [{k: p.get(k) for k in keep} for p in sorted(rows, key=lambda p: -p["likes"])]


def read_signals(posts):
    """올린 글에서 바로 읽히는 것들. 계정 체력이 100배씩 차이나므로 절대 조회수가
    아니라 "그 계정 평소 대비 몇 배"(배수)로 잰다. 1.0이 평소 수준.

    표본이 적은 구간이 많아 숫자를 단정으로 읽으면 안 된다. n을 같이 내보내
    화면에서 판단 강도를 구분한다.
    """
    import statistics
    from collections import defaultdict
    from datetime import date

    live = [p for p in posts if p.get("views")]
    if not live:
        return {}

    base = {}
    per = defaultdict(list)
    for p in live:
        per[p["account"]].append(p["views"])
    for a, v in per.items():
        base[a] = statistics.mean(v) or 1

    def ratio(p):
        return p["views"] / base[p["account"]]

    def group(keyfn, rows=None):
        g = defaultdict(list)
        for p in (rows or live):
            g[keyfn(p)].append(p)
        return {k: {"n": len(v),
                    "score": round(statistics.median(ratio(x) for x in v), 2),
                    "median": int(statistics.median(x["views"] for x in v))}
                for k, v in g.items()}

    hour = lambda p: int(p["local"].split()[1].split(":")[0])
    wday = lambda p: "월화수목금토일"[date.fromisoformat(p["date"]).weekday()]

    # 계정별 최적 시간대 — 표본 1건짜리는 근거가 못 되니 건수를 같이 넘긴다
    st = account_status()
    by_acc = {}
    for a in sorted(per, key=lambda a: -base[a]):
        rows = [p for p in live if p["account"] == a]
        g = group(hour, rows)
        best = max(g.items(), key=lambda kv: (kv[1]["median"], kv[1]["n"]))
        info = st.get(a, {})
        by_acc[a] = {
            "flag": rows[0]["country"], "posts": len(rows),
            "avg": int(base[a]), "max": max(p["views"] for p in rows),
            "hours": dict(sorted(g.items())),
            "best_hour": best[0], "best_n": best[1]["n"],
            "state": info.get("state", "active"), "note": info.get("note", ""),
            "until": info.get("until"),
            "health": health([p for p in posts if p["account"] == a], info),
        }
    # 최근 글이 없어 위 루프에 안 잡힌 계정도 상태는 보여준다
    for a, info in st.items():
        if a not in by_acc:
            by_acc[a] = {"flag": meta(a)[0] if (ROOT/"accounts"/a).is_dir() else "??",
                         "posts": 0, "avg": 0, "max": 0, "hours": {},
                         "best_hour": None, "best_n": 0,
                         "state": info.get("state", "active"), "note": info.get("note", ""),
                         "until": info.get("until"),
                         "health": health([p for p in posts if p["account"] == a], info)}

    return {
        "hour": dict(sorted(group(hour).items())),
        "wday": {k: group(wday)[k] for k in "월화수목금토일" if k in group(wday)},
        "media": group(lambda p: p.get("kind") or "?"),
        "accounts": by_acc,
    }


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


PROJECTS = {"moonlight": "문라이트", "cortex": "코르텍스", "trace": "트레이스"}


def project_of_file(name):
    """texts/cortex/kr01.txt → cortex. 프로젝트는 폴더로 가른다. 루트(폴더 없음)는 trace."""
    parts = str(name).replace("\\", "/").split("/")
    for seg in parts[:-1]:
        if seg in PROJECTS:
            return seg
    return "trace"


def text_dirs(proj):
    """프로젝트의 본문 폴더. trace는 루트, 나머지는 하위 폴더."""
    if proj == "trace":
        return [ROOT / "done", ROOT / "texts"]
    return [ROOT / "done" / proj, ROOT / "texts" / proj]


_body_proj = None


def project_of_text(text, account):
    """게시물 본문을 texts/·done/ 파일과 대조해 프로젝트를 찾는다.
    못 찾으면 계정의 프로젝트(meta.txt) — 팀원 글은 이 레포 texts/를 거치지 않는다."""
    global _body_proj
    if _body_proj is None:
        _body_proj = {}
        for d in (ROOT / "done", ROOT / "texts"):
            if d.is_dir():
                for t in d.rglob("*.txt"):
                    body = t.read_text(encoding="utf-8").partition("\n---\n")[0]
                    _body_proj[_norm(body)] = project_of_file(t.relative_to(ROOT))
    return _body_proj.get(_norm(text or "")) or account_project(account)


def rounds_file(proj):
    """프로젝트별 실험 파일. trace는 rounds.json, 나머지는 rounds_<proj>.json."""
    return ROOT / ("rounds.json" if proj == "trace" else f"rounds_{proj}.json")


def accounts(who):
    # 영구정지(banned)는 토큰이 없어 수집하면 매번 오류만 난다.
    st = account_status()
    return sorted(d.name for d in (ROOT / "accounts").iterdir()
                  if d.is_dir() and owner(d.name) == who and st.get(d.name, {}).get("state") != "banned")


def scheduled(accs):
    """아직 안 나간 예약 중 accs 계정 것. 시각은 계정 현지로도 같이 준다."""
    f = ROOT / "schedule.txt"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        when, acc, textfile, tw, ig, done = parse(line)
        if acc not in accs:
            continue
        code, tz = meta(acc)
        utc = datetime.fromisoformat(when)
        body = ""
        p = ROOT / textfile
        if p.exists():
            body = p.read_text(encoding="utf-8").strip()
        out.append({
            "account": acc, "project": project_of_file(textfile), "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "local": utc.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "text": body, "media": tw, "ig": [x for x in ig if x != "-"], "done": sorted(done),
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
        # 실패하면 빈 dict다. 0으로 채우면 진짜 0(노출 막힘)과 구분이 안 돼 막힘 판정을 오염시킨다 → None.
        m = insights(p["id"], token)
        out.append({
            "id": p["id"], "account": account, "project": None, "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "date": utc.astimezone(tz).strftime("%Y-%m-%d"),
            "local": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "text": (p.get("text") or "").strip(),
            "kind": p.get("media_type", ""),
            "link": p.get("permalink", ""),
            **{k: (m.get(k, 0) if m else None) for k in METRICS},
        })
        out[-1]["project"] = project_of_text(out[-1]["text"], account)
    return out


PT = ZoneInfo("America/Los_Angeles")


def link_clicks(account, posts):
    """앱 링크 클릭을 각 글에 붙인다.

    Threads는 링크 클릭을 글 단위로 주지 않는다(글 insights의 clicks는 늘 0). 계정 단위
    threads_insights?metric=clicks만 잡히고, 그것도 태평양 시간 하루 단위로 끊긴다.
    그래서 날마다 받아서 그날까지 올라온 글들에 나눠 준다(spread_clicks).
    """
    if not posts:
        return
    token, uid = creds(account)

    def clicks(day):
        a = datetime.combine(day, datetime.min.time(), PT)
        b = min(a + timedelta(days=1) - timedelta(seconds=1), datetime.now(timezone.utc))
        d = api(f"{uid}/threads_insights", token, metric="clicks",
                since=int(a.timestamp()), until=int(b.timestamp()))
        return sum(x.get("value", 0) for x in (d.get("data") or [{}])[0].get("link_total_values", []))

    ps = sorted(posts, key=lambda p: p["utc"])
    pday = lambda p: datetime.fromisoformat(p["utc"]).astimezone(PT).date()
    first, today = pday(ps[0]), datetime.now(PT).date()
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    # 기간 전체가 0이면 날마다 물을 필요가 없다 — 대부분 계정이 여기서 끝난다
    a = datetime.combine(first, datetime.min.time(), PT)
    total = api(f"{uid}/threads_insights", token, metric="clicks",
                since=int(a.timestamp()), until=int(datetime.now(timezone.utc).timestamp()))
    daily = {d: 0 for d in days}
    if sum(x.get("value", 0) for x in (total.get("data") or [{}])[0].get("link_total_values", [])):
        daily = {d: clicks(d) for d in days}
    spread_clicks(ps, daily, pday)


def spread_clicks(ps, daily, pday):
    """그날 클릭을 그날까지 올라온 글들에 조회수 비율로 나눈다.

    가장 최근 글 하나에 몰아주면 늦게 터진 글이 0이 된다(pim 10/13 글 115만 조회 → 0).
    조회 0인 리포스트는 자연히 몫이 없다. 조회가 전부 0인 날만 가장 최근 글에 준다.
    ponytail: 누적 조회 비율이라 오래된 대박 글이 새 글 몫을 조금씩 가져간다. 글마다 링크를 다르게 달면 정확해진다.
    """
    share = {id(p): 0.0 for p in ps}
    for d, c in daily.items():
        owner = [p for p in ps if pday(p) <= d]
        w = sum(p.get("views") or 0 for p in owner)
        for p in owner:
            share[id(p)] += c * (p.get("views") or 0) / w if w else 0
        if owner and not w:
            share[id(owner[-1])] += c
    for p in ps:
        p["clicks"] = round(share[id(p)])


IG_GRAPH = "https://graph.instagram.com/v23.0"
IG_METRICS = ["views", "likes", "comments", "saved", "shares"]


def ig_token(account):
    """인스타 토큰. 없는 계정(한국·대만)은 None — 조용히 건너뛴다."""
    f = ROOT / "accounts" / account / "ig_token.txt"
    if f.exists():                       # 로컬은 토큰 파일만 있어도 된다 (me/media라 user_id 불필요)
        return f.read_text().strip()
    try:
        return creds(account, ig=True)[0]
    except (KeyError, FileNotFoundError):
        return None


def ig_posts_of(account, days):
    """계정의 최근 인스타 게시물 + 지표. 스레드와 같은 키로 맞춰 화면을 공유한다.
    replies=댓글, saved=저장(스레드의 리포스트 자리)."""
    token = ig_token(account)
    if not token:
        return []
    code, tz = meta(account)
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    q = urllib.parse.urlencode({"fields": "id,caption,timestamp,permalink,media_type",
                                "limit": 100, "access_token": token})
    with urllib.request.urlopen(f"{IG_GRAPH}/me/media?{q}", timeout=30) as r:
        data = json.load(r)
    out = []
    for p in data.get("data", []):
        utc = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        if utc.timestamp() < since:
            continue
        try:
            q = urllib.parse.urlencode({"metric": ",".join(IG_METRICS), "access_token": token})
            with urllib.request.urlopen(f"{IG_GRAPH}/{p['id']}/insights?{q}", timeout=30) as r:
                m = {d["name"]: (d.get("values") or [{}])[0].get("value", 0)
                     for d in json.load(r)["data"]}
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
            m = {}
        out.append({
            "id": p["id"], "account": account, "project": None, "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "date": utc.astimezone(tz).strftime("%Y-%m-%d"),
            "local": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "text": (p.get("caption") or "").strip(),
            "kind": p.get("media_type", ""),
            "link": p.get("permalink", ""),
            "views": m.get("views", 0), "likes": m.get("likes", 0),
            "replies": m.get("comments", 0), "saved": m.get("saved", 0),
            "shares": m.get("shares", 0),
        })
        out[-1]["project"] = project_of_text(out[-1]["text"], account)
    return out


def pending_of(account, posts, days):
    """최근 게시물들의 미답변 답글. 오래된 글은 안 본다 - 답글이 수백 건이라 느리다."""
    cut = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    for p in posts:
        if datetime.fromisoformat(p["utc"]).timestamp() < cut:
            continue
        for r in unanswered(account, p["id"]):
            out.append({**r, "account": account, "project": p.get("project") or "trace", "country": p["country"],
                        "flag": p["flag"], "post": p["id"],
                        "post_text": p["text"].splitlines()[0][:40] if p["text"] else "",
                        "post_link": p["link"]})
    return out


def main():
    if "--merge-h48" in sys.argv:   # dashboard.yml 커밋 단계: 원격 위에 방금 적은 기록을 합친다
        h = merge_h48(load_h48(), load_h48(sys.argv[sys.argv.index("--merge-h48") + 1]))
        prune_h48(h)
        save_h48(h)
        return print(f"{H48_FILE.name} {len(h)}건")
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    rdays = (int(sys.argv[sys.argv.index("--replies-days") + 1])
             if "--replies-days" in sys.argv else 14)

    who = sys.argv[sys.argv.index("--owner") + 1] if "--owner" in sys.argv else actions_owner()
    out = data_file(who)   # team.json에 없는 아이디면 수집 전에 여기서 멈춘다
    accs = accounts(who)

    all_posts, all_ig, all_pending, all_skipped, errors = [], [], [], [], []
    failed = set()
    for a in accs:
        try:
            all_ig += ig_posts_of(a, days)
        except Exception as e:
            errors.append(f"{a} 인스타: {e}")
        try:
            ps = posts_of(a, days)
            all_posts += ps
        except Exception as e:
            errors.append(f"{a} 게시물: {e}")
            failed.add(a)
            continue
        try:
            link_clicks(a, ps)
        except Exception as e:
            errors.append(f"{a} 링크 클릭: {e}")
        try:
            skip = skiplist(a)
            for r in pending_of(a, ps, rdays):
                if r["id"] in skip:
                    all_skipped.append({**r, "why": skip[r["id"]]})
                else:
                    all_pending.append(r)
        except Exception as e:
            errors.append(f"{a} 답글: {e}")

    if accs and failed == set(accs):
        # 토큰이 통째로 없을 때(시크릿 누락) 빈 파일로 덮으면 남의 대시보드가 지워진다. 쓰지 않고 멈춘다.
        print(f"{out.name} · 계정 {len(accs)}개 전부 수집 실패 — 파일을 그대로 둔다")
        for e in errors[:5]:
            print(" ", e)
        sys.exit(1)

    # 48시간 조회수 기록. 커밋은 Actions(dashboard.yml)만 한다 — 로컬 팀원 갱신은 자기 파일만 푸시하므로
    # 여기서 h48.json을 고치면 pull --autostash 충돌만 만든다. 로컬에선 메모리로만 쓴다.
    H48.clear()
    H48.update(load_h48())
    fresh = record_h48(H48, all_posts)
    if os.environ.get("GITHUB_ACTIONS"):
        prune_h48(H48)
        save_h48(H48)

    experiments = {}
    for proj in PROJECTS:
        rs = rounds(proj)
        mine = [p for p in all_posts if p["project"] == proj]
        tag_rounds(mine, rs)
        rj = json.loads(rounds_file(proj).read_text(encoding="utf-8")) if rounds_file(proj).exists() else {}
        watching = rj.get("관측", {})
        all_arms = arm_scores(mine, rs)
        for w in watching.values():   # 갈래점수 표시가 있는 관측 항목은 현재값을 매 갱신마다 계산해 채운다
            if isinstance(w, dict) and w.get("갈래점수"):
                # 카드마다 자기 갈래만. 라운드별 arms(R16 H·C)가 생겨 최상위 arms 카드(W39)에 섞이던 것을 막는다
                labels = w.get("갈래") or list(rj.get("arms", {}))
                arms = {k: v for k, v in all_arms.items() if k in labels}
                w["현재값"] = {k: v["score"] for k, v in arms.items()}
                w["표본"] = {k: v["n"] for k, v in arms.items()}
                w["계정별"] = {k: v["accounts"] for k, v in arms.items()}
                w["현재해석"] = ("  ·  ".join(f"{k} {v['score']} (n={v['n']})" for k, v in arms.items())
                              if arms else "아직 발행 전")
        experiments[proj] = {"rounds": compare(mine, rs), "insights": read_signals(mine),
                             "plan": rj.get("plan", []), "tournament": rj.get("tournament", {}),
                             # 확정/관측은 rounds.json이 단일 출처다. 화면은 이 둘을 맨 위에 보여준다.
                             "settled": rj.get("확정", {}), "watching": watching}
    ok = [a for a in accs if a not in failed]   # 수집 실패 계정은 글이 0건으로 보여 판정·제안이 틀어진다
    health_all = accounts_health(all_posts, ok)
    sched = scheduled(accs)
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "projects": PROJECTS,
        "experiments": experiments,
        "window_days": days,
        "scheduled": sched,
        # 계정 상태는 계정의 전 프로젝트 글로 잰다(experiments의 health는 프로젝트별). 화면은 이쪽을 먼저 쓴다.
        "accounts_health": health_all,
        "proposals": proposals(health_all, all_posts, sched),
        "violations": violations(all_posts, log=posted_log()),
        "hits": hits(all_posts),
        "posts": sorted(all_posts, key=lambda r: r["utc"], reverse=True),
        "ig_posts": sorted(all_ig, key=lambda r: r["utc"], reverse=True),
        "pending": sorted(all_pending, key=lambda r: r["when"]),
        "skipped": sorted(all_skipped, key=lambda r: r["when"]),
        "errors": errors,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out.name} · 계정 {len(accs)} · 예약 {len(data['scheduled'])} · 게시물 {len(data['posts'])} · 인스타 {len(data['ig_posts'])} · "
          f"미답변 {len(data['pending'])} · 답안함 {len(data['skipped'])} · 오류 {len(errors)} · "
          f"48시간 기록 +{fresh} · 제안 {len(data['proposals'])} · 위반 {len(data['violations'])}")
    for e in errors:
        print(" ", e)


if __name__ == "__main__":
    main()


def _selfcheck():
    """import한 이름을 덮어쓰지 않았는지 본다. report.insights(post_id, token)를
    같은 이름 함수로 가린 적이 있어 전 계정 수집이 통째로 죽었다."""
    import inspect
    assert list(inspect.signature(insights).parameters) == ["post_id", "token"], \
        "report.insights가 가려졌다"
    assert list(inspect.signature(read_signals).parameters) == ["posts"]
    # 판정 규칙. 글은 전부 48시간이 지난 것으로 만든다
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    mk = lambda vs: [{"id": str(i), "account": "x", "utc": (t0 + timedelta(hours=i)).isoformat(),
                      "date": HEALTH_FROM, "views": v, "likes": 0} for i, v in enumerate(vs)]
    lab = lambda vs, info={}: health(mk(vs), info, h48={})["label"]
    assert lab([4000, 4, 0, 0]) == "막힘"
    assert lab([4000, 800, 90, 300]) == "저조"            # 막힘은 아니지만 최근 3건 중앙값 300
    assert lab([50, 50, 50, 600, 700]) == "회복"
    assert lab([900, None, None]) == "정상"               # 조회수 못 받은 글은 0이 아니라 판정 제외
    assert health(mk([900, None, None]), {}, h48={})["n"] == 1
    assert lab([]) == ""
    rest = {"state": "rest", "until": HEALTH_FROM}
    assert health(mk([300, 600]), rest, h48={})["rest_verdict"] == "pass"
    assert health(mk([300, 400]), rest, h48={})["rest_verdict"] == "fail"
    assert health(mk([300]), rest, h48={})["rest_verdict"] is None
    assert health(mk([50, 50, 50]), {}, h48={"0": {"views": 5000}})["label"] == "저조"   # h48 값이 지금 값보다 우선
    print("ok")
