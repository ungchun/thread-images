"""12월 공식 글 3장(손 사진·잠금화면·확대 슬라이드)을 만든다 — 10/27 운영 글(v1027)과 같은 공정.

    ~/github/Trace_iOS/appium/venv/bin/python make_post_dec.py <jp|tw>

입력: 시뮬 렌더(out_<c>/*.png), 배경 그림(final/), 손 사진(hand/<c>/hand-r*.png)
출력: ~/Desktop/trace-imagegen/cloud/dec-month/post_<c>/
"""
import datetime
import glob
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

APPIUM = os.path.expanduser("~/github/Trace_iOS/appium")
sys.path.insert(0, APPIUM)
import lockscreen_overlay as lo  # noqa: E402

ROOT = os.path.expanduser("~/Desktop/trace-imagegen/cloud/dec-month")
ASSETS = os.path.expanduser("~/github/Trace_iOS/.claude/presets/wallpaper/assets")
TOOLS = os.path.dirname(os.path.abspath(__file__))

CFG = {
    "jp": dict(render="out_jp/jp-m1201_jp_kotatsu.png", art="final/jp_kotatsu.png", lang="ja-JP",
               time="7:42", date=datetime.date(2026, 12, 1), font="ZenMaruGothic-Medium.ttf",
               t1="アプリを開かなくても", t2="ロック画面で12月がぜんぶ見える"),
    "tw": dict(render="out_tw/tw-m1202_tw_tangyuan.png", art="final/tw_tangyuan.png", lang="zh-TW",
               time="8:15", date=datetime.date(2026, 12, 2), font="ChironGoRoundTC-500M.ttf",
               t1="不用打開 App", t2="鎖定畫面一眼看完整個 12 月"),
}
INK_TEXT = (31, 42, 68)


def lock_ui(src, dst):
    """상태바·손전등·카메라·홈 인디케이터 — v1027 좌표 그대로(1170x2532)."""
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    ui = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ui)
    ink = (20, 24, 32, 255)
    y = 78
    for i, h in enumerate((14, 20, 26, 32)):
        x = 845 + i * 14
        d.rounded_rectangle((x, y + 32 - h, x + 9, y + 32), 2, fill=ink)
    cx, cy = 945, y + 33
    for r, w in ((30, 7), (20, 7), (9, 0)):
        if w:
            d.arc((cx - r, cy - r, cx + r, cy + r), 225, 315, fill=ink, width=w)
        else:
            d.pieslice((cx - r, cy - r, cx + r, cy + r), 225, 315, fill=ink)
    d.rounded_rectangle((990, y + 2, 1056, y + 32), 9, outline=ink, width=3)
    d.rounded_rectangle((996, y + 8, 1040, y + 26), 5, fill=ink)
    d.rounded_rectangle((1059, y + 11, 1064, y + 23), 2, fill=ink)
    for cx in (170, 1000):
        cy, r = 2330, 78
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 105), outline=(255, 255, 255, 150), width=2)
    cx, cy = 170, 2330
    d.polygon([(cx - 20, cy - 30), (cx + 20, cy - 30), (cx + 12, cy - 8), (cx - 12, cy - 8)], fill=ink)
    d.rounded_rectangle((cx - 12, cy - 8, cx + 12, cy + 32), 5, fill=ink)
    d.ellipse((cx - 4, cy + 2, cx + 4, cy + 10), fill=(255, 255, 255, 200))
    cx = 1000
    d.rounded_rectangle((cx - 34, cy - 20, cx + 34, cy + 26), 9, fill=ink)
    d.rounded_rectangle((cx - 14, cy - 30, cx + 14, cy - 16), 4, fill=ink)
    d.ellipse((cx - 14, cy - 11, cx + 14, cy + 17), fill=(255, 255, 255, 210))
    d.ellipse((cx - 8, cy - 5, cx + 8, cy + 11), fill=ink)
    d.rounded_rectangle((W // 2 - 210, H - 34, W // 2 + 210, H - 22), 6, fill=ink)
    Image.alpha_composite(im, ui).convert("RGB").save(dst)


def panel_box(im):
    """달력 패널 상자. 같은 프리셋·같은 5주 달이면 v1027 값 그대로다(일본 렌더에서 픽셀로 재서 783–1908 확인).
    밝기로 찾으면 배경 그라데이션이 진한 그림(탕위안)에서 틀린다."""
    return 46, 784, 1125, 1909


def close_slide(lock_flat, art, font, t1, t2, dst):
    """확대 슬라이드 1170x1462 — v1027 코드 그대로, 패널 위치만 찾아서."""
    im = Image.open(lock_flat).convert("RGB")
    bg = Image.open(art).convert("RGB")
    box = panel_box(im)
    crop = im.crop(box)
    CW, CH = 1170, 1462
    canvas = bg.crop((0, 0, bg.width, int(bg.width * CH / CW))).resize((CW, CH))
    d = ImageDraw.Draw(canvas)
    f1 = ImageFont.truetype(os.path.join(ASSETS, font), 72)
    f2 = ImageFont.truetype(os.path.join(ASSETS, font), 44)
    for t, f, y in ((t1, f1, 70), (t2, f2, 168)):
        bb = d.textbbox((0, 0), t, font=f)
        d.text(((CW - (bb[2] - bb[0])) / 2 - bb[0], y), t, font=f, fill=INK_TEXT)
    avail_h = CH - 260 - 50
    sc = min((CW - 70) / crop.width, avail_h / crop.height)
    cr = crop.resize((int(crop.width * sc), int(crop.height * sc)), Image.LANCZOS)
    x = (CW - cr.width) // 2
    y = 260 + (avail_h - cr.height) // 2
    m = Image.new("L", cr.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, cr.width - 1, cr.height - 1), int(30 * sc), fill=255)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x, y + 10, x + cr.width, y + cr.height + 10), 30, fill=(40, 60, 90, 50))
    sh = sh.filter(ImageFilter.GaussianBlur(16))
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(sh)
    canvas = canvas.convert("RGB")
    canvas.paste(cr, (x, y), m)
    canvas.save(dst)
    return box


def main():
    c = sys.argv[1]
    k = CFG[c]
    out = os.path.join(ROOT, "post_%s" % c)
    os.makedirs(out, exist_ok=True)
    flat = os.path.join(out, "flat_1170.png")
    Image.open(os.path.join(ROOT, k["render"])).convert("RGB").resize((1170, 2532), Image.LANCZOS).save(flat)
    lock = os.path.join(out, "flat_1170_lock.png")
    lo.overlay(flat, lock, lang=k["lang"], time_str=k["time"], dt=k["date"])
    lock_ui_path = os.path.join(out, "month_%s_lock.png" % c)
    lock_ui(lock, lock_ui_path)
    box = close_slide(lock, os.path.join(ROOT, k["art"]), k["font"], k["t1"], k["t2"],
                      os.path.join(out, "month_%s_close.png" % c))
    print("panel", box)
    for hand in sorted(glob.glob(os.path.join(ROOT, "hand", c, "hand-r*.png"))):
        r = os.path.basename(hand)[len("hand-"):-len(".png")]
        dst = os.path.join(out, "month_%s_hand_%s.jpg" % (c, r))
        # compose_hand는 numpy가 필요하다 — appium venv엔 없어서 시스템 python3로 돈다.
        subprocess.run(["python3", os.path.join(TOOLS, "compose_hand.py"), hand, lock_ui_path, dst],
                       check=True, capture_output=True)
        print("hand", dst)


if __name__ == "__main__":
    main()
