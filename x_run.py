#!/usr/bin/env python3
"""x_schedule.txt 에서 시각이 지난 예약을 X에 올린다. post.yml이 run.py 다음에 부른다.

x_schedule.txt 한 줄 (탭 구분):
    <ISO시각(UTC)>  <계정>  <본문파일>  <images/ 아래 이미지(쉼표로 최대 4장) 또는 mp4 하나 | ->  [완료표시]

본문 파일에서 `---` 한 줄 아래는 자기 글에 바로 다는 답글이다(없으면 답글 없음).
앱 링크는 `{link}` 로만 쓴다. 계정 설정(accounts/x.json)의 링크 하나로 바뀐다 — X에서는
ct=x_ourtrace 링크만 쓰기로 했다(2026-10-26 오너). 본문에 apps.apple.com 을 직접 쓰면 세운다.

X는 Threads와 규칙이 다르다(research/threads_expert/x1_platform.md).
- API로는 원글과 자기 글 답글만 올린다. 남의 글 답글·좋아요·팔로우·인용은 사람이 앱에서 한다.
- 같은 문구를 여러 계정에 올리면 스팸으로 잡힌다. 나라(언어)당 계정 하나다.
- 계정당 현지 날짜로 하루 1개, 직전 글과 18시간 이상 띄운다. 걸리면 done:hold-<사유>를 붙여 세운다.

발행 기록은 posted.log(platform=x)에 남는다. 요금은 글 $0.015, 링크 든 글 $0.20(2026-04 기준).

  python3 x_run.py           발행
  python3 x_run.py --dry     올릴 줄만 보여 준다(API 호출 없음)
  python3 x_run.py --check   자체 검사
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
SCHEDULE = ROOT / "x_schedule.txt"
CONFIG = ROOT / "accounts" / "x.json"
POSTED_LOG = ROOT / "posted.log"
IMAGES = ROOT / "images"
API = "https://api.x.com/2"
DAILY_CAP = 1
MIN_GAP = timedelta(hours=18)
MAX_MEDIA = 4
OPEN_STATES = {"active", "official"}


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["accounts"]


def keys(cfg):
    """계정 키 4개. 시크릿 이름은 <prefix>_API_KEY 식이다(X_JP_API_KEY …)."""
    p = cfg["secret_prefix"]
    names = ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET")
    vals = [os.environ.get(f"{p}_{n}") for n in names]
    if not all(vals):
        raise RuntimeError(f"{p}_* 시크릿이 비어 있다")
    return dict(zip(names, vals))


def _q(s):
    return urllib.parse.quote(str(s), safe="~")


def oauth_header(k, method, url, query=None):
    """OAuth 1.0a 서명. 쿼리는 서명에 넣고, JSON·multipart 본문은 넣지 않는다."""
    o = {"oauth_consumer_key": k["API_KEY"], "oauth_nonce": uuid.uuid4().hex,
         "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
         "oauth_token": k["ACCESS_TOKEN"], "oauth_version": "1.0"}
    params = "&".join(f"{_q(a)}={_q(b)}" for a, b in sorted({**o, **(query or {})}.items()))
    base = "&".join([method, _q(url), _q(params)])
    key = f"{_q(k['API_SECRET'])}&{_q(k['ACCESS_SECRET'])}"
    o["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_q(a)}="{_q(b)}"' for a, b in o.items())


def call(k, path, body=None, content_type=None, method="POST", query=None):
    url = f"{API}/{path}"
    headers = {"Authorization": oauth_header(k, method, url, query)}
    if content_type:
        headers["Content-Type"] = content_type
    full = url + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(full, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:   # 크레딧 부족(402)·권한·중복 글은 본문에 이유가 온다
        raise RuntimeError(f"{e.code} {e.read().decode()[:800]}") from None


def _multipart(fields, name, filename, data):
    boundary = uuid.uuid4().hex
    head = "".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{a}\"\r\n\r\n{b}\r\n" for a, b in fields.items())
    body = (head + f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def upload_image(k, path):
    """이미지 한 장 업로드 → media id."""
    body, ctype = _multipart({"media_category": "tweet_image"}, "media", path.name, path.read_bytes())
    return call(k, "media/upload", body, ctype)["data"]["id"]


CHUNK = 4 * 1024 * 1024


def upload_video(k, path):
    """mp4 분할 업로드(initialize → append → finalize) 후 처리가 끝날 때까지 기다린다 → media id."""
    data = path.read_bytes()
    mid = call(k, "media/upload/initialize", json.dumps({
        "media_type": "video/mp4", "total_bytes": len(data), "media_category": "tweet_video"}).encode(),
        "application/json")["data"]["id"]
    for i in range(0, len(data), CHUNK):
        body, ctype = _multipart({"segment_index": str(i // CHUNK)}, "media", path.name, data[i:i + CHUNK])
        call(k, f"media/upload/{mid}/append", body, ctype)
    info = call(k, f"media/upload/{mid}/finalize").get("data", {}).get("processing_info")
    deadline = time.time() + 300
    while info and info.get("state") in ("pending", "in_progress"):
        if time.time() > deadline:
            raise RuntimeError(f"영상 처리 5분 초과: {path.name}")
        time.sleep(max(1, int(info.get("check_after_secs", 3))))
        info = call(k, "media/upload", method="GET", query={"command": "STATUS", "media_id": mid}).get("data", {}).get("processing_info")
    if info and info.get("state") == "failed":
        raise RuntimeError(f"영상 처리 실패: {info}")
    return mid


def upload(k, path):
    return upload_video(k, path) if path.suffix.lower() == ".mp4" else upload_image(k, path)


def create_post(k, text, media_ids=(), reply_to=None):
    payload = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": list(media_ids)}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    return call(k, "tweets", json.dumps(payload).encode(), "application/json")["data"]["id"]


def split_text(raw, link):
    """(본문, 답글|None). `{link}`를 계정 링크로 바꾸고, 링크를 직접 쓴 글은 막는다."""
    if "apps.apple.com" in raw:
        raise ValueError("앱 링크는 {link}로만 쓴다")
    body, sep, reply = raw.partition("\n---\n")
    body, reply = body.strip().replace("{link}", link), reply.strip().replace("{link}", link)
    if not body:
        raise ValueError("본문이 비었다")
    return body, (reply or None)


def parse(line):
    cols = line.rstrip("\n").split("\t")
    when, account, textfile, media = cols[:4]
    done = set(cols[4].split(",")) if len(cols) > 4 and cols[4] else set()
    return when, account, textfile, ([] if media == "-" else media.split(",")), done


def render(when, account, textfile, media, done):
    return "\t".join([when, account, textfile, ",".join(media) or "-", ",".join(sorted(done))]).rstrip("\t")


def posted_times(account, log=None):
    """posted.log에 남은 이 계정의 X 발행 시각들(UTC)."""
    text = log if log is not None else (POSTED_LOG.read_text(encoding="utf-8") if POSTED_LOG.exists() else "")
    out = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and not line.startswith("#") and cols[1] == account and cols[2] == "x":
            out.append(datetime.fromisoformat(cols[0]))
    return out


def hold_reason(account, cfg, now, times):
    """발행해도 되는가. 걸리면 사유 코드, 통과면 None."""
    if cfg is None:
        return "unknown"
    if cfg.get("state") not in OPEN_STATES:
        return cfg.get("state") or "unknown"
    tz = ZoneInfo(cfg["tz"])
    today = now.astimezone(tz).date()
    if sum(1 for t in times if t.astimezone(tz).date() == today) >= DAILY_CAP:
        return "cap"
    if times and now - max(times) < MIN_GAP:
        return "gap"
    return None


def lint_reason(account, cfg, textfile):
    """현지어 린터 block이 있으면 "lint". X 계정은 전부 공식이라 block을 그대로 적용한다."""
    from locale_lint import COUNTRY_LANG, fmt, lint
    lang = COUNTRY_LANG.get(((cfg or {}).get("country") or "").upper())
    if not lang:
        return None
    blocks = [f for f in lint((ROOT / textfile).read_text(encoding="utf-8"), lang) if f.severity == "block"]
    for f in blocks:
        print(f"LINT {account} {textfile}: {fmt(f)}", flush=True)
    return "lint" if blocks else None


def log_post(account, post_id, textfile):
    with POSTED_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\t{account}\tx\t{post_id}\t{textfile}\n")


def main(dry=False):
    if not SCHEDULE.exists():
        return
    accounts = load_config()
    now = datetime.now(timezone.utc)
    kept, failed = [], 0
    for line in SCHEDULE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            kept.append(line)
            continue
        when, account, textfile, media, done = parse(line)
        if datetime.fromisoformat(when) > now or any(d.startswith("hold-") for d in done):
            kept.append(line)
            continue
        cfg = accounts.get(account)
        try:
            body, reply = split_text((ROOT / textfile).read_text(encoding="utf-8"), (cfg or {}).get("link", ""))
            if len(media) > MAX_MEDIA:
                raise ValueError(f"이미지 {len(media)}장 — 최대 {MAX_MEDIA}")
            if any(m.endswith(".mp4") for m in media) and len(media) > 1:
                raise ValueError("영상은 한 글에 하나만, 이미지와 섞지 않는다")
            posted = next((d.split(":", 1)[1] for d in done if d.startswith("x:")), None)
            if not posted:
                why = hold_reason(account, cfg, now, posted_times(account)) or lint_reason(account, cfg, textfile)
                if why:
                    print(f"HOLD {account} {textfile}: {why}", flush=True)
                    kept.append(render(when, account, textfile, media, done | {f"hold-{why}"}))
                    continue
                if dry:
                    print(f"DRY {account} {textfile} media={media} reply={'y' if reply else 'n'}\n{body}\n", flush=True)
                    kept.append(line)
                    continue
                k = keys(cfg)
                ids = [upload(k, IMAGES / m) for m in media]
                posted = create_post(k, body, ids)
                log_post(account, posted, textfile)
                done.add(f"x:{posted}")
                print(f"OK {account} {posted} {textfile}", flush=True)
            if reply and not dry:
                create_post(keys(cfg), reply, reply_to=posted)
                print(f"OK-REPLY {account} {posted}", flush=True)
        except Exception as e:   # 본문만 올라갔으면 done:x 표시가 남아 다음 회차가 답글만 다시 민다
            failed += 1
            print(f"FAIL {account} {textfile}: {e}", flush=True)
            kept.append(render(when, account, textfile, media, done))
            continue
    if not dry:
        SCHEDULE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    if failed:
        sys.exit(1)


def _selfcheck():
    link = "https://apps.apple.com/app/apple-store/id6503812022?pt=126570331&ct=x_ourtrace&mt=8"
    assert split_text("本文\n{link}", link) == (f"本文\n{link}", None)
    assert split_text("本文\n---\nリンク {link}\n", link) == ("本文", f"リンク {link}")
    for bad in ("https://apps.apple.com/app/id6503812022", "\n---\nreply"):
        try:
            split_text(bad, link)
            raise AssertionError(bad)
        except ValueError:
            pass
    row = "2026-10-27T12:00:00+00:00\tx_trace_jp\ttexts/trace/x/a.txt\ttrace/x/a.png,trace/x/b.png"
    assert render(*parse(row)) == row
    cfg = {"state": "active", "tz": "Asia/Tokyo"}
    jst = ZoneInfo("Asia/Tokyo")
    now = datetime(2026, 10, 27, 21, 0, tzinfo=jst)
    assert hold_reason("a", cfg, now, []) is None
    assert hold_reason("a", cfg, now, [datetime(2026, 10, 27, 8, 0, tzinfo=jst)]) == "cap"
    assert hold_reason("a", cfg, datetime(2026, 10, 28, 1, 0, tzinfo=jst),
                       [datetime(2026, 10, 27, 20, 0, tzinfo=jst)]) == "gap"
    assert hold_reason("a", cfg, now, [datetime(2026, 10, 26, 21, 0, tzinfo=jst)]) is None
    assert hold_reason("a", None, now, []) == "unknown"
    h = oauth_header({"API_KEY": "a", "API_SECRET": "b", "ACCESS_TOKEN": "c", "ACCESS_SECRET": "d"},
                     "GET", f"{API}/media/upload", {"command": "STATUS", "media_id": "1"})
    assert h.startswith("OAuth ") and "command" not in h   # 쿼리는 서명에만, 헤더엔 안 들어간다
    body, ctype = _multipart({"segment_index": "0"}, "media", "v.mp4", b"xyz")
    assert b'name="segment_index"\r\n\r\n0' in body and body.endswith(b"--\r\n") and "boundary=" in ctype
    assert hold_reason("a", {**cfg, "state": "paused"}, now, []) == "paused"
    log = "2026-10-27T03:00:00+00:00\tx_trace_jp\tx\t1\tt\n2026-10-27T03:00:00+00:00\tx_trace_jp\tthreads\t2\tt\n"
    assert len(posted_times("x_trace_jp", log)) == 1
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        global ROOT
        old, ROOT = ROOT, Path(d)
        try:
            (ROOT / "bad.txt").write_text("すごい!!\n12/1は休み", encoding="utf-8")
            (ROOT / "ok.txt").write_text("今日の予定です\n12/1(火)は休み", encoding="utf-8")
            assert lint_reason("a", {"country": "JP"}, "bad.txt") == "lint"
            assert lint_reason("a", {"country": "JP"}, "ok.txt") is None
            assert lint_reason("a", {"country": "KR"}, "bad.txt") is None
        finally:
            ROOT = old
    print("x_run selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _selfcheck()
    else:
        main(dry="--dry" in sys.argv)
