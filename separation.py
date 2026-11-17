"""분리 관문. 공식 계정과 개인처럼 보이는 계정이 같은 이미지·답글로 묶이지 않게 한다.

근거: 묶이면 대만 Dcard 業配 영구정지·일본 ステマ(스텔스 마케팅) 위험.
  - 공식 계정 줄이 최근 30일 안에 공식이 아닌 계정이 쓴 이미지·답글 문장을 쓰면 block
  - 반대(비공식 계정이 공식 계정의 것을 쓰는 것)는 warn

비교 대상은 schedule.txt 줄(이미지·본문 파일)과 posted.log(본문 파일)이다. posted.log에는 이미지가 없어
이미 나간 글의 이미지는 schedule.txt에 줄이 남아 있을 때만 잡힌다. 이미지는 파일 해시가 있으면 해시로,
없으면 basename으로 같은 것을 가른다(basename만 보면 sun_1.png처럼 흔한 이름이 오탐한다).
답글은 URL·공백을 뺀 한 줄이 8자 이상일 때 문장으로 센다.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from locale_lint import CTRL, URL, official_accounts, split_parts

WINDOW = timedelta(days=30)
MIN_SENTENCE = 8
STRIP = re.compile(r"[\s　]+")


def _norm(line):
    return STRIP.sub("", line).lower()


def reply_sentences(text):
    """답글 블록의 문장(줄) 집합. 링크·delay/media 줄은 뺀다."""
    _, reply = split_parts(text)
    out = set()
    for line in URL.sub("", CTRL.sub("", reply)).splitlines():
        n = _norm(line)
        if len(n) >= MIN_SENTENCE:
            out.add(n)
    return out


def image_key(root, rel):
    """(basename, 해시|None)."""
    rel = rel.strip().lstrip("!")
    for base in ("images", "done/images"):
        f = Path(root) / base / rel
        if f.is_file():
            return Path(rel).name, hashlib.sha1(f.read_bytes()).hexdigest()
    return Path(rel).name, None


def same_image(a, b):
    return a[1] == b[1] if a[1] and b[1] else a[0] == b[0]


def _utc(s):
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _read(root, rel):
    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def usages(root):
    """[{account, when, images[(basename,hash)], sentences}] — schedule.txt와 posted.log."""
    root, out = Path(root), []
    f = root / "schedule.txt"
    for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        c = line.split("\t")
        if line.startswith("#") or len(c) < 3 or not c[0].strip():
            continue
        imgs = []
        for col in c[3:5]:
            imgs += [image_key(root, x) for x in col.lstrip("!").split(",") if x.strip() and x.strip() != "-"]
        out.append({"account": c[1], "when": _utc(c[0]), "images": imgs, "sentences": reply_sentences(_read(root, c[2]))})
    f = root / "posted.log"
    for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        c = line.split("\t")
        if line.startswith("#") or len(c) < 5:
            continue
        out.append({"account": c[1], "when": _utc(c[0]), "images": [], "sentences": reply_sentences(_read(root, c[4]))})
    return out


def check_row(root, account, when, images, textfile, used=None):
    """이 줄과 반대편 계정(공식↔비공식)의 최근 30일 사용을 대조한다. [(severity, 메시지)]."""
    root = Path(root)
    official = official_accounts(root)
    mine_official = account in official
    when = _utc(when) if isinstance(when, str) else when
    mine_imgs = [image_key(root, x) for x in images]
    mine_sent = reply_sentences(_read(root, textfile))
    sev = "block" if mine_official else "warn"
    seen, out = set(), []
    for u in used if used is not None else usages(root):
        if (u["account"] in official) == mine_official or abs(u["when"] - when) > WINDOW:
            continue
        for a in mine_imgs:
            if any(same_image(a, b) for b in u["images"]) and (u["account"], a[0]) not in seen:
                seen.add((u["account"], a[0]))
                out.append((sev, f"이미지 {a[0]} — {u['account']}({'비공식' if mine_official else '공식'})가 {u['when']:%m/%d}에 쓴 것"))
        for s in sorted(mine_sent & u["sentences"]):
            if (u["account"], s) not in seen:
                seen.add((u["account"], s))
                out.append((sev, f"답글 문장 「{s[:20]}…」 — {u['account']}({'비공식' if mine_official else '공식'})가 {u['when']:%m/%d}에 쓴 것"))
    return out
