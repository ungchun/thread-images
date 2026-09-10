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
import urllib.error
import urllib.parse
import urllib.request
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


def rounds(proj="trace"):
    """라운드 정의 + 그 라운드에 나간 문구 본문. done/<코드><id>.txt 로 찾는다."""
    f = rounds_file(proj)
    if not f.exists():
        return []
    out = []
    for r in json.loads(f.read_text(encoding="utf-8"))["rounds"]:
        bodies = []          # [(본문, 변종)] — 변종은 파일명 접미 a/b → A/B. 짝(a·b 둘 다)이 있을 때만.
        files = [t for d in text_dirs(proj) if d.is_dir()
                 for t in list(d.glob(f"*{r['id']}.txt")) + list(d.glob(f"*{r['id']}[ab].txt"))]
        stems = {t.stem for t in files}
        for t in files:
            pair = t.stem[:-1] + ("b" if t.stem[-1] == "a" else "a")
            var = t.stem[-1].upper() if t.stem[-1] in "ab" and pair in stems else None
            bodies.append((t.read_text(encoding="utf-8").strip(), var))
        out.append({**r, "bodies": bodies})
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
        p["round"], p["variant"] = hits[0][0]["id"], hits[0][1]
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
        views = [p.get("views", 0) for p in ps]
        # 하트율은 조회가 0이면 정의되지 않는다
        ers = [p.get("likes", 0) / p["views"] for p in ps if p.get("views", 0) > 0]
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
    reach = p.get("views", 0) / base["views"]
    er_base = base["er"]
    if not er_base or not p.get("views"):
        return reach, None
    return reach, (p.get("likes", 0) / p["views"]) / er_base


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
    base = baselines(by_acc)

    reach, resp = {}, {}
    for acc, ps in by_acc.items():
        if len({p["round"] for p in ps}) < 2:   # 한 라운드만 있는 계정은 비교 불가
            continue
        for p in ps:
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
            "views": sum(p.get("views", 0) for p in got),
            "likes": sum(p.get("likes", 0) for p in got),
            "median": int(statistics.median([p.get("views", 0) for p in got])) if got else 0,
            "score": round(statistics.median(rr), 2) if rr else None,
            "sample": len(rr),
            "er_score": round(statistics.median(er), 2) if er else None,
            "er_sample": len(er),
            "variants": variant_scores(got, by_acc, base),
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
        for p in ps:
            mine = by_acc.get(p["account"], [])
            if len({x["round"] for x in mine}) < 2:
                continue
            a, b = ratios_of(p, base[p["account"]])
            rr.append(a)
            if b is not None:
                er.append(b)
        out[k] = {"posts": len(ps),
                  "median": int(statistics.median([p.get("views", 0) for p in ps])),
                  "score": round(statistics.median(rr), 2) if rr else None,
                  "sample": len(rr),
                  "er_score": round(statistics.median(er), 2) if er else None,
                  "er_sample": len(er)}
    return out


def account_status():
    """계정 운영 상태. accounts/status.json이 단일 출처다."""
    f = ROOT / "accounts" / "status.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8")).get("accounts", {})


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
        }
    # 최근 글이 없어 위 루프에 안 잡힌 계정도 상태는 보여준다
    for a, info in st.items():
        if a not in by_acc:
            by_acc[a] = {"flag": meta(a)[0] if (ROOT/"accounts"/a).is_dir() else "??",
                         "posts": 0, "avg": 0, "max": 0, "hours": {},
                         "best_hour": None, "best_n": 0,
                         "state": info.get("state", "active"), "note": info.get("note", "")}

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


def project_of_text(text):
    """게시물 본문을 texts/·done/ 파일과 대조해 프로젝트를 찾는다. 못 찾으면 trace."""
    global _body_proj
    if _body_proj is None:
        _body_proj = {}
        for d in (ROOT / "done", ROOT / "texts"):
            if d.is_dir():
                for t in d.rglob("*.txt"):
                    body = t.read_text(encoding="utf-8").partition("\n---\n")[0]
                    _body_proj[_norm(body)] = project_of_file(t.relative_to(ROOT))
    return _body_proj.get(_norm(text or ""), "trace")


def rounds_file(proj):
    """프로젝트별 실험 파일. trace는 rounds.json, 나머지는 rounds_<proj>.json."""
    return ROOT / ("rounds.json" if proj == "trace" else f"rounds_{proj}.json")


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
        m = insights(p["id"], token)
        out.append({
            "id": p["id"], "account": account, "project": None, "country": code, "flag": flag(code),
            "utc": utc.isoformat(),
            "date": utc.astimezone(tz).strftime("%Y-%m-%d"),
            "local": utc.astimezone(tz).strftime("%m/%d %H:%M"),
            "text": (p.get("text") or "").strip(),
            "kind": p.get("media_type", ""),
            "link": p.get("permalink", ""),
            **{k: m.get(k, 0) for k in METRICS},
        })
        out[-1]["project"] = project_of_text(out[-1]["text"])
    return out


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
        out[-1]["project"] = project_of_text(out[-1]["text"])
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
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    rdays = (int(sys.argv[sys.argv.index("--replies-days") + 1])
             if "--replies-days" in sys.argv else 14)

    all_posts, all_ig, all_pending, all_skipped, errors = [], [], [], [], []
    for a in accounts():
        try:
            all_ig += ig_posts_of(a, days)
        except Exception as e:
            errors.append(f"{a} 인스타: {e}")
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

    experiments = {}
    for proj in PROJECTS:
        rs = rounds(proj)
        mine = [p for p in all_posts if p["project"] == proj]
        tag_rounds(mine, rs)
        rj = json.loads(rounds_file(proj).read_text(encoding="utf-8")) if rounds_file(proj).exists() else {}
        experiments[proj] = {"rounds": compare(mine, rs), "insights": read_signals(mine),
                             "plan": rj.get("plan", []), "tournament": rj.get("tournament", {}),
                             # 확정/관측은 rounds.json이 단일 출처다. 화면은 이 둘을 맨 위에 보여준다.
                             "settled": rj.get("확정", {}), "watching": rj.get("관측", {})}
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "projects": PROJECTS,
        "experiments": experiments,
        "window_days": days,
        "scheduled": scheduled(),
        "posts": sorted(all_posts, key=lambda r: r["utc"], reverse=True),
        "ig_posts": sorted(all_ig, key=lambda r: r["utc"], reverse=True),
        "pending": sorted(all_pending, key=lambda r: r["when"]),
        "skipped": sorted(all_skipped, key=lambda r: r["when"]),
        "errors": errors,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"예약 {len(data['scheduled'])} · 게시물 {len(data['posts'])} · 인스타 {len(data['ig_posts'])} · "
          f"미답변 {len(data['pending'])} · 답안함 {len(data['skipped'])} · 오류 {len(errors)}")
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
    print("ok")
