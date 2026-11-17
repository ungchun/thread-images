#!/usr/bin/env python3
"""현지어 린터. 일본(ja)·대만(zh-TW) 홍보 글의 번역체·간체·대륙용어·반각 기호를 잡는다.

규칙 데이터는 코드 밖 research/lint/<lang>.tsv — 오너가 tsv만 고쳐도 된다.
칸: severity(block|warn) · kind · pattern · hint · 출처.
  kind가 emoji(pattern=임계 개수)·length(pattern=가중 글자 한도, 全角=2)·count(pattern이 2회 이상)·date(曜日 없는 날짜)면
  특별 처리하고, 그 밖의 kind는 pattern을 정규식으로 찾는다. kind는 scan 집계의 규칙 이름이 된다.

검사에서 뺀다: URL·{link}·`delay:`/`media:` 줄. 본문(`---` 위)과 답글(아래)은 따로 검사한다.

block은 공식 계정(status.json state=official인 Threads 계정, accounts/x.json의 X 계정)에만 적용한다.
팀원이 운영하는 계정은 같은 결과를 warn으로만 보여 주고 막지 않는다(팀원 운영 방식을 바꾸지 않기 위해서다).

  python3 locale_lint.py 글.txt [글2.txt ...] --lang ja|zh-TW
  python3 locale_lint.py --scan texts --country JP|TW
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent
LINT_DIR = ROOT / "research" / "lint"
COUNTRY_LANG = {"JP": "ja", "TW": "zh-TW"}
URL = re.compile(r"https?://\S+|\{link\}")
CTRL = re.compile(r"^\s*(delay|media):.*$", re.I | re.M)
WEEKDAY_AFTER = re.compile(r"\s*[（(][月火水木金土日]")
RANGE_AFTER = re.compile(r"\s*[〜~～ー–-]\s*\d{1,2}/\d{1,2}")
EMOJI = re.compile("[\U0001F000-\U0001F2FF\U0001F300-\U0001FAFF☀-➿⭐⭕⬛⬜⤴⤵⬅-⬇]")


class Finding(NamedTuple):
    severity: str
    rule: str
    match: str
    hint: str
    part: str = "body"      # body | reply


def load_rules(lang, directory=None):
    f = Path(directory or LINT_DIR) / f"{lang}.tsv"
    rules = []
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        c = line.split("\t")
        if len(c) < 4 or c[0] not in ("block", "warn"):
            raise ValueError(f"{f.name}:{n} — severity|kind|pattern|hint|출처 5칸이 아니다")
        rules.append((c[0], c[1], c[2], c[3], c[4] if len(c) > 4 else ""))
    return rules


def split_parts(text):
    """(본문, 답글). 파일은 `---` 한 줄 아래가 자기 글 답글이다."""
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        return "", text[4:]
    body, _, reply = text.partition("\n---\n")
    return body, reply


def clean(part):
    return URL.sub("", CTRL.sub("", part)).strip()


def weight(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _lint_part(text, rules, part):
    out, seen = [], set()

    def add(sev, kind, m, hint):
        key = (sev, kind, m)
        if key not in seen:
            seen.add(key)
            out.append(Finding(sev, kind, m, hint, part))

    for sev, kind, pat, hint, _src in rules:
        if kind == "emoji":
            found = EMOJI.findall(text)
            if len(found) >= int(pat):
                add(sev, kind, "".join(found[:6]), f"{hint} ({len(found)}개)")
        elif kind == "length":
            if part == "body" and weight(text) > int(pat):
                add(sev, kind, f"{weight(text)}/{pat}", hint)
        elif kind == "count":
            hits = re.findall(pat, text, re.M)
            if len(hits) >= 2:
                add(sev, kind, f"{hits[0]}×{len(hits)}", hint)
        elif kind == "date":
            for m in re.finditer(pat, text, re.M):
                if sev == "block":          # `12/1` 꼴: 뒤에 (曜日)가 없으면. 범위의 앞 날짜는 넘어간다
                    tail = text[m.end():]
                    if WEEKDAY_AFTER.match(tail) or RANGE_AFTER.match(tail):
                        continue
                add(sev, kind, m.group(0), hint)
        else:
            for m in re.finditer(pat, text, re.M):
                add(sev, kind, m.group(0).strip()[:24] or repr(m.group(0)), hint)
    return out


def lint(text, lang, rules_dir=None):
    """본문·답글을 따로 검사해 Finding 목록을 돌려 준다. lang: ja | zh-TW."""
    rules = load_rules(lang, rules_dir)
    body, reply = split_parts(text)
    out = []
    for part, t in (("body", body), ("reply", reply)):
        t = clean(t)
        if t:
            out += _lint_part(t, rules, part)
    return out


# ---- 계정·나라 ----

def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("accounts", {})
    except (OSError, ValueError):
        return {}


def official_accounts(root=None):
    """공식 계정 = status.json state official(Threads) + x.json의 X 계정 전부."""
    root = Path(root or ROOT)
    st = {a for a, i in _json(root / "accounts" / "status.json").items() if i.get("state") == "official"}
    return st | set(_json(root / "accounts" / "x.json"))


def account_country(account, root=None):
    root = Path(root or ROOT)
    x = _json(root / "accounts" / "x.json").get(account)
    if x and x.get("country"):
        return x["country"].upper()
    f = root / "accounts" / account / "meta.txt"
    if f.exists():
        parts = f.read_text(encoding="utf-8").split()
        return parts[0].upper() if parts else None
    return None


def lint_for_account(text, account, root=None, rules_dir=None):
    """(막는 것, 알리기만 하는 것). 공식 계정의 block만 막고, 그 밖은 전부 알리기만 한다."""
    lang = COUNTRY_LANG.get(account_country(account, root) or "")
    if not lang:
        return [], []
    found = lint(text, lang, rules_dir)
    if account in official_accounts(root):
        return [f for f in found if f.severity == "block"], [f for f in found if f.severity != "block"]
    return [], found


def fmt(f):
    return f"[{f.severity}] {f.rule}{'/답글' if f.part == 'reply' else ''} 「{f.match}」 — {f.hint}"


def summary(findings, limit=3):
    head = "; ".join(f"{f.rule}「{f.match}」" for f in findings[:limit])
    return head + (f" 외 {len(findings) - limit}건" if len(findings) > limit else "")


# ---- scan ----

def _file_accounts(root):
    """본문 파일 → 계정. schedule·x_schedule·posted.log에서 모은다."""
    m = {}
    for name, cols in (("schedule.txt", (1, 2)), ("x_schedule.txt", (1, 2)), ("posted.log", (1, 4))):
        f = root / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            c = line.split("\t")
            if line.startswith("#") or len(c) <= max(cols):
                continue
            m.setdefault(c[cols[1]], c[cols[0]])
    return m


def file_country(path, root, mapping, accounts):
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    acc = mapping.get(rel)
    if not acc:
        hits = [a for a in accounts if a in path.stem]
        acc = max(hits, key=len) if hits else None
    if acc:
        return account_country(acc, root), acc
    stem = path.stem.lower()
    m = re.match(r"(jp|tw)(?=\d|[_-]|$)", stem) or re.search(r"[_-](jp|tw)$", stem)
    return (m.group(1).upper() if m else None), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--lang", choices=["ja", "zh-TW"])
    ap.add_argument("--scan", help="폴더. 계정 meta로 나라를 찾아 --country 글만 검사한다")
    ap.add_argument("--country", choices=["JP", "TW"])
    a = ap.parse_args(argv)
    if a.scan:
        if not a.country:
            ap.error("--scan은 --country가 필요하다")
        lang, folder = COUNTRY_LANG[a.country], Path(a.scan).resolve()
        mapping = _file_accounts(ROOT)
        accounts = [d.name for d in (ROOT / "accounts").iterdir() if d.is_dir()]
        todo = []
        for p in sorted(folder.rglob("*.txt")):
            c, acc = file_country(p, ROOT, mapping, accounts)
            if c == a.country:
                todo.append((p, acc))
    elif a.files and a.lang:
        lang, todo = a.lang, [(Path(f), None) for f in a.files]
    else:
        ap.error("파일과 --lang, 또는 --scan과 --country")
    count, files_hit, total = Counter(), set(), 0
    for p, acc in todo:
        found = lint(p.read_text(encoding="utf-8"), lang)
        total += 1
        for f in found:
            count[(f.severity, f.rule, f.match)] += 1
            files_hit.add((f.severity, f.rule, p))
            if not a.scan:
                print(f"{p}: {fmt(f)}")
    if a.scan:
        by_rule = Counter()
        for (sev, rule, _), n in count.items():
            by_rule[(sev, rule)] += n
        print(f"{a.country} {total}개 파일")
        for (sev, rule), n in sorted(by_rule.items()):
            nf = len({p for s, r, p in files_hit if (s, r) == (sev, rule)})
            top = ", ".join(f"{m}×{c}" for (s, r, m), c in count.most_common() if (s, r) == (sev, rule))[:90]
            print(f"  {sev:5} {rule:10} {n:3}건/{nf}파일  {top}")
    blocks = sum(n for (s, _, _), n in count.items() if s == "block")
    return 1 if blocks and not a.scan else 0


if __name__ == "__main__":
    sys.exit(main())
