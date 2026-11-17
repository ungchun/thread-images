"""손 사진의 초록 화면에 잠금화면 PNG를 원근 합성한다.

    python compose_hand.py <손사진.png> <잠금화면.png> <출력.jpg>

초록 마스크의 네 변을 각각 직선으로 맞추고 교점을 모서리로 쓴다(둥근 모서리는 마스크가 깎는다).
손가락처럼 화면을 가린 것은 초록이 아니므로 자동으로 위에 남는다.
"""
import sys

import numpy as np
from PIL import Image, ImageFilter

W_OUT, H_OUT = 1440, 1800


def green_mask(a):
    """크로마키 초록 중 화면 덩어리 하나만. 배경 나뭇잎도 초록이라 이어진 영역으로 가른다."""
    from PIL import ImageDraw
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    raw = (g > 150) & (g > r + 70) & (g > b + 70)
    ys, xs = np.where(raw)
    # 가장 초록이 빽빽한 곳(행·열 개수 최대)을 씨앗으로
    sy = np.bincount(ys).argmax()
    sx = int(np.median(xs[ys == sy]))
    im = Image.fromarray((raw * 255).astype("uint8")).copy()   # fromarray 이미지는 floodfill이 조용히 안 먹는다
    ImageDraw.floodfill(im, (sx, sy), 128)
    blob = np.asarray(im) == 128
    # 다이내믹 아일랜드 같은 안쪽 구멍은 화면의 일부다 — 행마다 좌우 끝 사이를 메운다
    filled = blob.copy()
    for y in np.where(blob.any(axis=1))[0]:
        xs_ = np.where(blob[y])[0]
        filled[y, xs_.min():xs_.max() + 1] = True
    return blob, filled


def fit_line(pts):
    """점들에 직선을 맞춘다(주성분). (점, 방향) 반환."""
    pts = np.asarray(pts, float)
    c = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def intersect(l1, l2):
    (p, d), (q, e) = l1, l2
    A = np.array([d, -e]).T
    t = np.linalg.solve(A, q - p)
    return p + t[0] * d


def edges(m):
    ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0, x1 - x0
    top, bot, left, right = [], [], [], []
    # 둥근 모서리를 피해 가운데 60%만 쓴다
    for x in range(int(x0 + w * 0.2), int(x1 - w * 0.2)):
        col = np.where(m[:, x])[0]
        if len(col):
            top.append((x, col.min()))
            bot.append((x, col.max()))
    for y in range(int(y0 + h * 0.2), int(y1 - h * 0.2)):
        row = np.where(m[y])[0]
        if len(row):
            left.append((row.min(), y))
            right.append((row.max(), y))
    return [fit_line(v) for v in (top, right, bot, left)]


def robust(pts_line_side):
    return pts_line_side


def perspective_coeffs(dst, src):
    """PIL transform용: 출력 좌표(dst) → 입력 좌표(src)."""
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def main():
    photo_p, screen_p, out_p = sys.argv[1:4]
    photo = Image.open(photo_p).convert("RGB").resize((W_OUT, H_OUT), Image.LANCZOS)
    a = np.asarray(photo)
    m, filled = green_mask(a)
    t, r, b, l = edges(filled)
    tl, tr, br, bl = intersect(l, t), intersect(t, r), intersect(r, b), intersect(b, l)
    # 직선 교점은 둥근 모서리 안쪽에 떨어져 모서리에 초록이 남는다 — 중심에서 2% 바깥으로 민다
    c = np.mean([tl, tr, br, bl], axis=0)
    quad = [tuple(c + (p - c) * 1.01) for p in (tl, tr, br, bl)]
    print("corners", [tuple(round(v) for v in p) for p in quad])

    scr = Image.open(screen_p).convert("RGB")
    sw, sh = scr.size
    coeffs = perspective_coeffs(quad, [(0, 0), (sw, 0), (sw, sh), (0, sh)])
    warped = scr.transform((W_OUT, H_OUT), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    # 사진 속 화면 윗변이 살짝 휘어 직선 사각형이 못 덮는 틈이 남는다 — 잠금화면 맨 윗줄 색으로 깐다
    cover = Image.new("L", scr.size, 255).transform((W_OUT, H_OUT), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
    top_col = tuple(int(v) for v in np.asarray(scr)[:20].reshape(-1, 3).mean(axis=0))
    base = Image.new("RGB", (W_OUT, H_OUT), top_col)
    base.paste(warped, (0, 0), cover)
    warped = base

    # 사진 속 화면처럼: 살짝 어둡게, 위쪽에 옅은 반사광, 사진 선명도에 맞춰 아주 약한 블러
    w = np.asarray(warped).astype(float)
    yy = np.linspace(0, 1, H_OUT)[:, None, None]
    glare = np.clip(1 - yy * 1.6, 0, 1) * 10
    w = w * 0.95 + glare
    warped = Image.fromarray(np.clip(w, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.6))

    alpha = Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.2))
    out = photo.copy()
    out.paste(warped, (0, 0), alpha)

    # 초록 번짐 제거: 마스크 경계 주변에서 g가 r·b보다 튀는 픽셀을 눌러 준다
    o = np.asarray(out).astype(int)
    r_, g_, b_ = o[..., 0], o[..., 1], o[..., 2]
    near = np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(17))) > 0
    spill = near & (g_ > np.maximum(r_, b_) + 25)   # 나무 같은 배경 초록은 건드리지 않는다
    o[..., 1] = np.where(spill, np.maximum(r_, b_) + 10, g_)
    Image.fromarray(np.clip(o, 0, 255).astype("uint8")).save(out_p, quality=93)
    print(out_p)


if __name__ == "__main__":
    main()
