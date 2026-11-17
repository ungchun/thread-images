"""손 사진을 초록 화면 중심으로 4:5 그대로 잘라 폰이 프레임 높이의 target 비율이 되게 한다.

    python3 crop_hand.py <hand.png> <out.png> [target=0.65]
화면(초록)은 나중에 잠금화면 원본으로 덮이니 확대해도 흐려지지 않는다. 손·배경만 늘어난다.
"""
import sys

import numpy as np
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
target = float(sys.argv[3]) if len(sys.argv) > 3 else 0.65
im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(int)
g = (a[..., 1] > 180) & (a[..., 0] < 120) & (a[..., 2] < 120)
ys, xs = np.nonzero(g)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
W, H = im.size
phone_h = (y1 - y0) * 1.08          # 테두리 포함
ch = min(H, phone_h / target)
cw = ch * W / H
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
left = min(max(0, cx - cw / 2), W - cw)
top = min(max(0, cy - ch / 2), H - ch)
im.crop((round(left), round(top), round(left + cw), round(top + ch))).resize((W, H), Image.LANCZOS).save(dst)
print("screen %.0f%% → crop %.2f" % (100 * (y1 - y0) / H, ch / H))
