"""Exact, user-authorized reservations for jeongmin_trace, 2026-11-28..12-09.

Only account exclusion and the fixed-time recommendation are excepted. The
existing runner, one-post-per-day limit, reply recovery and locking still apply.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "campaigns/20261128-jeongmin-kitty"
PREFIX = "texts/trace/20261128-jeongmin-kitty/"


def manifest():
    data = json.loads((DIRECTORY / "manifest.json").read_text())
    assert data["publish_authorized"] is True
    posts = data["posts"]
    assert len(posts) == 12 and len({p["textfile"] for p in posts}) == 12
    start = datetime(2026, 11, 28, tzinfo=ZoneInfo("Asia/Seoul"))
    for index, row in enumerate(posts):
        day = start + timedelta(days=index)
        expected = day.replace(hour=10 if day.weekday() == 5 else 11 if day.weekday() == 6 else 9)
        assert row["account"] == "jeongmin_trace"
        assert datetime.fromisoformat(row["scheduled_utc"]) == expected.astimezone(timezone.utc)
        assert len(row["images"]) == 3
    return data


def entry(when, account, textfile, images, caption):
    if not textfile.startswith(PREFIX):
        return None
    matches = [p for p in manifest()["posts"] if p["textfile"] == textfile]
    assert len(matches) == 1, "Unknown Kitty campaign reservation"
    row = matches[0]
    assert (when, account, images, caption) == (
        row["scheduled_utc"], row["account"], row["images"], row["caption"]
    ), "Kitty campaign differs from user-authorized reservation"
    assert hashlib.sha256((ROOT / textfile).read_bytes()).hexdigest() == row["text_sha256"], "Changed caption/reply"
    for name, expected in zip(images, row["sha256"]):
        assert hashlib.sha256((ROOT / "images" / name).read_bytes()).hexdigest() == expected, "Changed image"
    return row


def authorized_states(states, when, account, textfile, images, caption):
    if entry(when, account, textfile, images, caption) is None:
        return states
    return {**states, account: {**states.get(account, {}), "state": "active"}}


def preflight():
    """Read-only: check the actual Actions secret, all reservations and serving."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.request import urlopen
    from campaign_publish import api
    from run import RAW, creds, parse, reply_block

    data = manifest()
    token, uid = creds("jeongmin_trace")
    identity = api(token, "me", fields="id,username")
    assert identity == {"id": str(uid), "username": "jeongmin_trace"}
    debug = api(token, "debug_token", input_token=token)["data"]
    assert debug["is_valid"] and {"threads_basic", "threads_content_publish"} <= set(debug["scopes"])
    assert debug.get("expires_at", 0) > datetime.fromisoformat(data["posts"][-1]["scheduled_utc"]).timestamp() + 3600
    quota = api(token, uid + "/threads_publishing_limit", fields="quota_usage,config")["data"][0]
    assert quota["quota_usage"] < quota["config"]["quota_total"]
    scheduled = [parse(line) for line in (ROOT / "schedule.txt").read_text().splitlines()
                 if line.strip() and not line.startswith("#")]
    history = api(token, uid + "/threads", fields="id,text", limit=100).get("data", [])
    captions = {p.get("text") for p in history}
    for row in data["posts"]:
        candidates = [s for s in scheduled if s[2] == row["textfile"]]
        assert len(candidates) == 1
        when, account, textfile, images, ig, done = candidates[0]
        assert not ig and not done and row["caption"] not in captions
        entry(when, account, textfile, images, row["caption"])
        inline = (ROOT / textfile).read_text().partition("\n---\n")[2].strip()
        reply, media, _ = reply_block(inline, account)
        assert reply == data["reply"] and media == [] and len(reply) <= 500
    assets = {name: sha for row in data["posts"] for name, sha in zip(row["images"], row["sha256"])}
    def check_asset(item):
        name, sha = item
        with urlopen(RAW + "/images/" + name, timeout=45) as response:
            assert hashlib.sha256(response.read()).hexdigest() == sha, name
        return name
    with ThreadPoolExecutor(max_workers=6) as pool:
        checked = list(pool.map(check_asset, assets.items()))
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "identity": identity,
              "token_valid": True, "publish_scope": True, "expires_at": debug["expires_at"],
              "reservations_verified": len(data["posts"]), "images_verified": len(checked),
              "reply_verified": True, "published_during_preflight": 0}
    (DIRECTORY / "preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    preflight()
