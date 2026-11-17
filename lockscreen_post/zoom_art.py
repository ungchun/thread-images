#!/usr/bin/env python3
"""구름이 그림을 줌아웃해 캐릭터를 화면 아래 20% 남짓으로 줄인다 — 월간 달력이 위 70%를 덮어도 캐릭터가 보이게.

10/27 운영 글(month_tw_lock.png)의 배치: 달력 31~75%, 캐릭터 79~98%.

    GEMINI_API_KEY=... python3 zoom_art.py <입력.png> <출력.png> [--size 1206x2622] [--model gemini-3-pro-image]

키는 환경변수로만 받는다. 출력·로그에 남기지 않는다.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
PROMPT = (
    "Edit this image: zoom the camera out. The cloud character together with its immediate props "
    "(the table or kotatsu, the bowl, the cup, the scarf) becomes much smaller and sits at the very bottom "
    "of the frame, horizontally centered: the whole character group occupies only the bottom 22 percent "
    "of the image height, with its floor or table surface running across the full width at the bottom edge. "
    "Everything above it, the top 75 percent of the frame, is the same soft clean background gradient as "
    "the original, continuing upward smoothly, completely empty: no windows, no lamps, no snowflakes, "
    "no objects, no text, no patterns. Keep the character's design, face, colors, glow, lighting, materials "
    "and 3D rendering style identical to the original. Phone wallpaper, portrait."
)


def find_images(obj, found):
    if isinstance(obj, dict):
        if obj.get("type") == "image" and isinstance(obj.get("data"), str):
            found.append(obj["data"])
        for v in obj.values():
            find_images(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_images(v, found)
    return found


def main():
    argv = sys.argv[1:]
    model, size = "gemini-3-pro-image", (1206, 2622)
    if "--model" in argv:
        i = argv.index("--model"); model = argv[i + 1]; del argv[i:i + 2]
    if "--size" in argv:
        i = argv.index("--size"); size = tuple(int(v) for v in argv[i + 1].split("x")); del argv[i:i + 2]
    prompt = PROMPT
    if "--small" in argv:
        argv.remove("--small")
        prompt += (" The character must be tiny in the frame: the character group's total height is at most "
                   "15 percent of the image height, like a small figure sitting at the foot of a tall empty wall.")
    src, dst = argv[0], argv[1]
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY 없음")
    im = Image.open(src).convert("RGB")
    im.thumbnail((1024, 2048))
    tmp_png = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    im.save(tmp_png)
    with open(tmp_png, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    os.remove(tmp_png)
    body = {
        "model": model,
        "input": [{"type": "text", "text": prompt},
                  {"type": "image", "mime_type": "image/png", "data": data}],
        "response_format": {"type": "image", "mime_type": "image/jpeg",
                            "aspect_ratio": "9:16", "image_size": "2K"},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump(body, t)
        body_path = t.name
    try:
        proc = subprocess.run(
            ["curl", "-s", "-X", "POST", URL, "-H", f"x-goog-api-key: {key}",
             "-H", "Content-Type: application/json", "--max-time", "300", "-d", f"@{body_path}"],
            capture_output=True, text=True)
    finally:
        os.remove(body_path)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"응답 파싱 실패: {proc.stdout[:300]}")
    imgs = find_images(payload, [])
    if not imgs:
        sys.exit(f"이미지 없음: {json.dumps(payload)[:400]}")
    raw = dst + ".raw.jpg"
    with open(raw, "wb") as f:
        f.write(base64.b64decode(imgs[-1]))
    out = Image.open(raw).convert("RGB")
    w, h = out.size
    want = size[0] / size[1]
    if w / h > want:
        nw = round(h * want)
        out = out.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = round(w / want)
        out = out.crop((0, h - nh, w, h))   # 아래(캐릭터)를 살리고 위를 자른다
    out.resize(size, Image.LANCZOS).save(dst)
    print(f"{src} -> {dst} (raw {w}x{h})")


if __name__ == "__main__":
    main()
