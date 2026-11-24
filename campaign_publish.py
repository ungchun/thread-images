"""The 16 user-approved 11/24 posts, within the existing schedule runner.

Exceptions affect only exact manifest entries. No account state changes or replies.
"""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "campaigns/20261124-landmark-bts"
MANIFEST = DIRECTORY / "manifest.json"
STATE = DIRECTORY / "state.json"
FIELDS = "id,username,text,timestamp,permalink,media_type,children,topic_tag"


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def api(token, path, *, post=False, **params):
    url = "https://graph.threads.com/v1.0/" + path
    data = urlencode(params).encode()
    request = Request(url if post else url + "?" + data.decode(),
                      data=data if post else None,
                      headers={"Authorization": "Bearer " + token})
    try:
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            detail = json.load(error).get("error", {})
        except ValueError:
            detail = {}
        raise RuntimeError(f"Meta HTTP {error.code}, code={detail.get('code')}, "
                           f"subcode={detail.get('error_subcode')}") from None


def manifest():
    data = json.loads(MANIFEST.read_text())
    assert data["publish_authorized"] is True and len(data["posts"]) == 16
    assert len({p["id"] for p in data["posts"]}) == 16
    assert "jeongmin_trace" not in {p["account"] for p in data["posts"]}
    return data


def entry(when, account, textfile, images, caption):
    if not textfile.startswith("texts/trace/20261124-landmark-bts/"):
        return None
    rows = [p for p in manifest()["posts"] if p["textfile"] == textfile]
    assert len(rows) == 1, "Unknown campaign reservation"
    row = rows[0]
    assert (when, account, images, caption) == (
        row["scheduled_utc"], row["account"], row["images"], row["caption"]
    ), "Campaign differs from approved manifest"
    assert len(images) == 2
    for name, sha in zip(images, row["sha256"]):
        assert hashlib.sha256((ROOT / "images" / name).read_bytes()).hexdigest() == sha
    assert row["topic_tag"] == ("BTS" if row["kind"] == "bts" else None)
    return row


def ready(token, container):
    for _ in range(20):
        result = api(token, container, fields="id,status,error_message")
        if result.get("status") == "FINISHED":
            return
        if result.get("status") in {"ERROR", "EXPIRED", "PUBLISHED"}:
            raise RuntimeError("Container state " + result["status"])
        time.sleep(5)
    raise RuntimeError("Container processing timeout")


def verify(root, row):
    assert root["username"] == row["account"] and root.get("text") == row["caption"]
    assert root["media_type"] in {"CAROUSEL", "CAROUSEL_ALBUM"}
    assert len(root.get("children", {}).get("data", [])) == 2
    assert root.get("topic_tag") == row["topic_tag"], "Published topic differs"
    return root


def history(token, uid, row):
    params = {"fields": FIELDS, "limit": 100,
              "since": int(datetime.fromisoformat(manifest()["created_at"]).timestamp())}
    found = []
    for _ in range(10):
        page = api(token, uid + "/threads", **params)
        found.extend(p for p in page.get("data", []) if p.get("text") == row["caption"])
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not page.get("paging", {}).get("next") or not after:
            break
        params["after"] = after
    else:
        raise RuntimeError("History pagination incomplete")
    assert len(found) <= 1, "Multiple matching posts; refusing duplicate"
    return found


def publish(row):
    from run import creds
    token, uid = creds(row["account"])
    me = api(token, "me", fields="id,username")
    assert me == {"id": str(uid), "username": row["account"]}, "Token account mismatch"
    assert datetime.now(timezone.utc) >= datetime.fromisoformat(row["scheduled_utc"])
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    record = state.setdefault(row["id"], {})
    if record.get("published_id"):
        root = verify(api(token, record["published_id"], fields=FIELDS), row)
    else:
        matches = history(token, uid, row)
        if matches:
            root = verify(matches[0], row)
        else:
            if record.get("publish_requested_at"):
                raise RuntimeError("Previous publish outcome uncertain; no repeat publication")
            if not record.get("container_id"):
                children = record.setdefault("children", [])
                for name in row["images"][len(children):]:
                    children.append(api(token, uid + "/threads", post=True, media_type="IMAGE",
                                        is_carousel_item="true", image_url=row["media_base"] + name)["id"])
                    save(STATE, state)
                for child in children:
                    ready(token, child)
                params = {"media_type": "CAROUSEL", "children": ",".join(children), "text": row["caption"]}
                if row["topic_tag"]:
                    params["topic_tag"] = row["topic_tag"]
                record["container_id"] = api(token, uid + "/threads", post=True, **params)["id"]
                save(STATE, state)
            ready(token, record["container_id"])
            record["publish_requested_at"] = now()
            save(STATE, state)
            post_id = api(token, uid + "/threads_publish", post=True,
                          creation_id=record["container_id"])["id"]
            record["published_id"] = post_id
            save(STATE, state)
            root = verify(api(token, post_id, fields=FIELDS), row)
    record.update(published_id=root["id"], permalink=root.get("permalink"),
                  verified_at=now(), topic_tag=root.get("topic_tag"), status="PUBLISHED")
    save(STATE, state)
    return root["id"]


def preflight():
    from run import creds
    data = manifest()
    def account_check(account):
        token, uid = creds(account)
        assert api(token, "me", fields="id,username") == {"id": str(uid), "username": account}
        meta = api(token, "debug_token", input_token=token)["data"]
        assert meta["is_valid"] and {"threads_basic", "threads_content_publish"} <= set(meta["scopes"])
        quota = api(token, uid + "/threads_publishing_limit", fields="quota_usage,config")["data"][0]
        remaining = quota["config"]["quota_total"] - quota["quota_usage"]
        assert remaining >= 2
        posts = api(token, uid + "/threads", fields=FIELDS, limit=100).get("data", [])
        captions = {p["caption"] for p in data["posts"] if p["account"] == account}
        assert not any(p.get("text") in captions for p in posts), "Caption already published"
        return {"account": account, "identity_ok": True, "read_ok": True, "publish_scope": True,
                "quota_remaining": remaining, "expires_at": meta.get("expires_at")}
    with ThreadPoolExecutor(max_workers=8) as pool:
        accounts = list(pool.map(account_check, sorted({r["account"] for r in data["posts"]})))
    assets = {name: (p["media_base"] + name, sha) for p in data["posts"]
              for name, sha in zip(p["images"], p["sha256"])}
    def asset_check(item):
        name, (url, sha) = item
        with urlopen(url, timeout=45) as response:
            assert hashlib.sha256(response.read()).hexdigest() == sha, name
        return name
    with ThreadPoolExecutor(max_workers=8) as pool:
        checked = list(pool.map(asset_check, assets.items()))
    report = {"checked_at": now(), "accounts": accounts, "assets_verified": len(checked),
              "scheduled_posts": len(data["posts"]), "published_during_preflight": 0}
    save(DIRECTORY / "preflight.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true", required=True)
    parser.parse_args()
    preflight()
