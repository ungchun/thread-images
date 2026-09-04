#!/usr/bin/env python3
"""schedule.txt 에서 시각이 지난 예약을 Threads·Instagram에 올린다. cron이 30분마다 부른다.

schedule.txt 한 줄 (탭 구분):
    <ISO시각(UTC)>  <계정명>  <본문파일>  <threads미디어|->  <ig미디어|->  [완료표시]

미디어는 쉼표로 여러 개. 확장자로 이미지/영상을 가르므로 영상(.mp4/.mov)을
그냥 섞어 쓰면 된다. 예: intro.mp4,a.png,b.png (캐러셀 최대 20개).

완료표시는 이미 올라간 플랫폼을 기록한다(done:threads / done:ig). 한쪽만 성공하면
그 표시를 남기고 줄을 유지해, 다음 회차가 실패한 쪽만 다시 시도한다. 같은 글이
두 번 올라가는 일은 이 표시로 막는다.

양쪽 다 끝나면 줄을 지우고 본문·이미지를 done/ 으로 옮긴다.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
SCHEDULE = ROOT / "schedule.txt"
DONE = ROOT / "done"
RAW = "https://raw.githubusercontent.com/ungchun/thread-images/main"

# 두 플랫폼은 호스트도 필드 이름도 다르다. 나머지 흐름(컨테이너→대기→발행)은 같다.
THREADS = {
    "base": "https://graph.threads.net/v1.0",
    "images": "images",          # 이미지 폴더
    "create": "threads",         # 컨테이너 생성 엔드포인트
    "publish": "threads_publish",
    "status": "status",          # 상태 필드명
    "reply": "reply.txt",
}
INSTAGRAM = {
    "base": "https://graph.instagram.com/v23.0",
    "images": "images-ig",
    "create": "media",
    "publish": "media_publish",
    "status": "status_code",
    "reply": "reply_ig.txt",
}


def api(plat, path, token, get=False, **params):
    """API 호출. GET은 본문을 못 읽고 190을 내주므로 반드시 쿼리로 보낸다."""
    params["access_token"] = token
    query = urllib.parse.urlencode(params)
    url = f"{plat['base']}/{path}"
    req = (urllib.request.Request(f"{url}?{query}") if get
           else urllib.request.Request(url, data=query.encode()))
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # 실패 이유는 본문에 담겨 온다
        raise RuntimeError(f"{e.code} {e.read().decode()[:800]}") from None


def wait_ready(plat, container, token, tries=20):
    """컨테이너가 FINISHED 될 때까지 기다린다. 캐러셀은 묶기 전에 반드시 확인해야 한다."""
    field = plat["status"]
    for _ in range(tries):
        st = api(plat, container, token, get=True, fields=field)
        if st.get(field) == "FINISHED":
            return
        if st.get(field) in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container}: {st}")
        time.sleep(5)
    raise RuntimeError(f"container {container}: 준비 안 됨")


def creds(account, ig=False):
    """계정별 토큰. THREADS_ACCOUNTS(JSON) 우선, 없으면 로컬 파일."""
    blob = os.environ.get("THREADS_ACCOUNTS")
    if blob:
        a = json.loads(blob)[account]
        return (a["ig_token"], a["ig_user_id"]) if ig else (a["token"], a["user_id"])
    d = ROOT / "accounts" / account
    if ig:
        return (d / "ig_token.txt").read_text().strip(), (d / "ig_user_id.txt").read_text().strip()
    env = {}
    for line in (d / "env.sh").read_text().splitlines():
        if line.startswith("export "):
            k, _, v = line[7:].partition("=")
            env[k.strip()] = v.strip().strip("'\"")
    return env["THREADS_TOKEN"], env["THREADS_USER_ID"]


VIDEO_EXT = {".mp4", ".mov"}


def media_kind(name, url, ig=False):
    """파일 확장자로 이미지/영상을 가른다. 필드 이름부터 다르다.

    인스타는 이미지에 media_type을 안 받지만 영상에는 REELS가 필요하다.
    영상 컨테이너는 준비에 30초쯤 걸리는데 wait_ready(5초x20)가 이미 감당한다.
    """
    if Path(name).suffix.lower() in VIDEO_EXT:
        return {"media_type": "REELS" if ig else "VIDEO", "video_url": url}
    return {"image_url": url} if ig else {"media_type": "IMAGE", "image_url": url}


def fixed_reply(account, plat):
    """계정 고정 답글. 본문에 ---로 직접 쓰면 그쪽이 우선한다."""
    f = ROOT / "accounts" / account / plat["reply"]
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def publish(plat, account, text, images, reply=None, ig=False):
    token, user = creds(account, ig)
    base = f"{RAW}/{plat['images']}"
    create = f"{user}/{plat['create']}"
    if len(images) > 1:  # 캐러셀: 장마다 컨테이너를 만들고 전부 준비된 뒤 묶는다
        items = [api(plat, create, token, is_carousel_item="true",
                     **media_kind(i, f"{base}/{i}", ig))["id"] for i in images]
        for i in items:
            wait_ready(plat, i, token)
        kind = {"media_type": "CAROUSEL", "children": ",".join(items)}
    elif images:
        kind = media_kind(images[0], f"{base}/{images[0]}", ig)
    else:
        kind = {"media_type": "TEXT"}
    key = "caption" if ig else "text"
    container = api(plat, create, token, **{key: text}, **kind)["id"]
    wait_ready(plat, container, token)
    post_id = api(plat, f"{user}/{plat['publish']}", token, creation_id=container)["id"]
    if reply:
        if ig:  # 인스타는 댓글 엔드포인트 하나로 끝난다
            api(plat, f"{post_id}/comments", token, message=reply)
        else:   # Threads는 본문과 똑같이 컨테이너→발행 2단계
            c = api(plat, create, token, media_type="TEXT", text=reply, reply_to_id=post_id)["id"]
            wait_ready(plat, c, token)
            api(plat, f"{user}/{plat['publish']}", token, creation_id=c)
    return post_id


def parse(line):
    """한 줄을 (시각, 계정, 본문, threads이미지, ig이미지, 완료집합)으로 푼다."""
    f = line.split("\t")
    when, account, textfile = f[0], f[1], f[2]
    tw = [] if len(f) < 4 or f[3] == "-" else f[3].split(",")
    ig = [] if len(f) < 5 or f[4] == "-" else f[4].split(",")
    done = set(f[5].replace("done:", "").split(",")) if len(f) > 5 and f[5] else set()
    return when, account, textfile, tw, ig, done


def render(when, account, textfile, tw, ig, done):
    cols = [when, account, textfile, ",".join(tw) or "-", ",".join(ig) or "-"]
    if done:
        cols.append("done:" + ",".join(sorted(done)))
    return "\t".join(cols)


def main():
    if not os.environ.get("GITHUB_ACTIONS"):
        subprocess.run(["git", "-C", str(ROOT), "pull", "--quiet", "--rebase"], check=False)
    if not SCHEDULE.exists():
        return
    now = datetime.now(timezone.utc)
    kept, finished, changed = [], [], False

    for line in SCHEDULE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            kept.append(line)
            continue
        when, account, textfile, tw_imgs, ig_imgs, done = parse(line)
        if datetime.fromisoformat(when) > now:
            kept.append(line)
            continue

        body, _, inline = (ROOT / textfile).read_text(encoding="utf-8").partition("\n---\n")
        body, inline = body.strip(), inline.strip()

        # 이미지가 준비 안 된 플랫폼은 건너뛴다. 예약은 남아 다음 회차에 다시 본다.
        targets = []
        if "threads" not in done and tw_imgs:
            targets.append(("threads", THREADS, tw_imgs, False))
        if "ig" not in done and ig_imgs:
            targets.append(("ig", INSTAGRAM, ig_imgs, True))

        for name, plat, imgs, is_ig in targets:
            missing = [i for i in imgs if not (ROOT / plat["images"] / i).exists()]
            if missing:
                print(f"SKIP {account} {name}: 이미지 없음 {missing}", flush=True)
                continue
            try:
                post_id = publish(plat, account, body, imgs,
                                  inline or fixed_reply(account, plat), is_ig)
            except Exception as e:  # 실패한 플랫폼만 다음 회차에 재시도
                print(f"FAIL {account} {name} {textfile}: {e}", flush=True)
                continue
            print(f"posted {name} {post_id} {account} {textfile}", flush=True)
            done.add(name)
            changed = True

        # 예약한 플랫폼이 전부 끝났을 때만 줄을 지운다. 파일 정리는 루프 뒤에서 한다 —
        # 여러 줄이 같은 파일(공통 인트로 영상 등)을 쓰면 여기서 옮기는 순간
        # 뒤 줄이 "이미지 없음"으로 죽는다.
        need = {n for n, imgs in (("threads", tw_imgs), ("ig", ig_imgs)) if imgs}
        if need and need <= done:
            finished.append((textfile, tw_imgs, ig_imgs))
            changed = True
        else:
            kept.append(render(when, account, textfile, tw_imgs, ig_imgs, done))

    archive(finished, kept)

    if changed:
        SCHEDULE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        sync()


def archive(finished, kept):
    """끝난 예약의 파일을 done/으로 옮긴다. 남은 예약이 아직 쓰는 파일은 놔둔다."""
    live_text, live = set(), {THREADS["images"]: set(), INSTAGRAM["images"]: set()}
    for line in kept:
        if not line.strip() or line.startswith("#"):
            continue
        _, _, textfile, tw, ig, _ = parse(line)
        live_text.add(textfile)
        live[THREADS["images"]] |= set(tw)
        live[INSTAGRAM["images"]] |= set(ig)

    for textfile, tw_imgs, ig_imgs in finished:
        if textfile not in live_text:
            src = ROOT / textfile
            if src.exists():
                shutil.move(src, DONE / Path(textfile).name)
        # 두 폴더에 같은 파일명이 있을 수 있어 done 아래에서도 폴더를 나눈다
        for folder, imgs in ((THREADS["images"], tw_imgs), (INSTAGRAM["images"], ig_imgs)):
            dest = DONE / folder
            for i in imgs:
                src = ROOT / folder / i
                if i not in live[folder] and src.exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.move(src, dest / i)


def sync():
    """게시 결과를 리포에 반영해 다른 기기와 맞춘다. Actions에선 워크플로가 한다."""
    if os.environ.get("GITHUB_ACTIONS"):
        return
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "-A"], check=False)
    subprocess.run(git + ["commit", "--quiet", "-m", "posted"], check=False)
    subprocess.run(git + ["push", "--quiet"], check=False)


if __name__ == "__main__":
    main()


def _selfcheck():
    """확장자 분기만 검사. 영상은 필드 이름부터 달라서 조용히 틀리면 발행이 통째로 깨진다."""
    assert media_kind("a.png", "U") == {"media_type": "IMAGE", "image_url": "U"}
    assert media_kind("a.png", "U", ig=True) == {"image_url": "U"}
    assert media_kind("a.MP4", "U") == {"media_type": "VIDEO", "video_url": "U"}
    assert media_kind("a.mov", "U", ig=True) == {"media_type": "REELS", "video_url": "U"}
    _check_archive()
    print("ok")


def _check_archive():
    """여러 줄이 같은 영상을 쓸 때 첫 발행이 그 파일을 뺏어가지 않는지 본다."""
    import tempfile
    global ROOT, DONE
    keep_root, keep_done = ROOT, DONE
    try:
        ROOT = Path(tempfile.mkdtemp())
        DONE = ROOT / "done"
        DONE.mkdir()
        (ROOT / "images").mkdir()
        for n in ("shared.mov", "a.png", "b.png"):
            (ROOT / "images" / n).write_text("x")
        (ROOT / "texts").mkdir()
        for n in ("one.txt", "two.txt"):
            (ROOT / "texts" / n).write_text("x")

        kept = ["2030-01-01T00:00:00+00:00\tacc\ttexts/two.txt\tshared.mov,b.png\t-"]
        archive([("texts/one.txt", ["shared.mov", "a.png"], [])], kept)

        assert (ROOT / "images/shared.mov").exists(), "공유 영상이 사라졌다"
        assert (ROOT / "images/b.png").exists()
        assert (DONE / "images/a.png").exists(), "다 쓴 이미지는 치워야 한다"
        assert (DONE / "one.txt").exists()
        assert (ROOT / "texts/two.txt").exists()
    finally:
        ROOT, DONE = keep_root, keep_done
