"""그림 전체를 아래 가운데 기준으로 줄이고, 비는 칸은 줄마다 가장자리 색을 이어 채운다.
배경이 세로 그라데이션 + 가로로 긴 바닥·탁자라 줄 단위로 이으면 이음매가 안 보인다.

    python3 shrink_scene.py <입력> <출력> <배율>
"""
import sys
import numpy as np
from PIL import Image, ImageFilter

src, dst, k = sys.argv[1], sys.argv[2], float(sys.argv[3])
im = Image.open(src).convert("RGB")
W, H = im.size
sw, sh = round(W * k), round(H * k)
small = im.resize((sw, sh), Image.LANCZOS)
a = np.asarray(small).astype(float)
x0, y0 = (W - sw) // 2, H - sh
out = np.zeros((H, W, 3))
# 위: 작은 그림의 맨 윗줄 몇 줄 평균을 세로로 늘려 위 끝 원본 색까지 잇는다
top_src = np.asarray(im).astype(float)[:40].mean(axis=(0, 1))
top_dst = a[:20].mean(axis=(0, 1))
for y in range(y0):
    t = y / max(1, y0)
    out[y] = top_src * (1 - t) + top_dst * t
# 가운데 띠: 작은 그림을 놓고, 좌우는 그 줄의 가장자리 8px 평균으로 채운다
for y in range(sh):
    row = a[y]
    out[y0 + y, :x0] = row[:8].mean(axis=0)
    out[y0 + y, x0 + sw:] = row[-8:].mean(axis=0)
    out[y0 + y, x0:x0 + sw] = row
img = Image.fromarray(out.clip(0, 255).astype("uint8"))
# 경계 한 줄 이음매를 지우려고 좌우 경계·위 경계 근처만 살짝 흐린다
blur = img.filter(ImageFilter.GaussianBlur(3))
m = Image.new("L", (W, H), 0)
mm = np.zeros((H, W), dtype=np.uint8)
mm[:, max(0, x0 - 6):x0 + 6] = 255
mm[:, x0 + sw - 6:x0 + sw + 6] = 255
mm[max(0, y0 - 6):y0 + 6, :] = 255
m = Image.fromarray(mm).filter(ImageFilter.GaussianBlur(4))
Image.composite(blur, img, m).save(dst)
print(dst, (x0, y0, sw, sh))
