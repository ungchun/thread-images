#!/usr/bin/env python3
"""월간 잠금화면 달력 배경 렌더러 (일본 今月の待受カレンダー / 대만 月曆桌布).

    python3 calendar/render.py --country jp|tw --month 2026-12 [--start sun|mon] \
        [--holidays on|off] [--bg path.png] --out <폴더>

→ <out>/<country>_<YYMM>_<start>_<holidays>_<W>x<H>.png  (기본 1290x2796, 1179x2556 두 벌)

세로 구역: 0~28% 시계 자리(그리지 않음) / 30~60% 달력 카드 / 60~100% 캐릭터 장면(그리지 않음).
그리기 전에 check()가 「이 달의 빨간 날」을 원문 데이터와 대조하고, 그린 뒤 구역 침범을 검사한다.
어긋나면 예외를 던지고 파일을 쓰지 않는다.
"""
import argparse
import datetime as dt
import pathlib
import sys
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import caldata  # noqa: E402

FONTS = HERE / "fonts"
MASTER_W = 1290
DEFAULT_SIZES = [(1290, 2796), (1179, 2556)]

CLOCK_ZONE_END = 0.28      # 이 위로는 아무것도 그리지 않는다
CARD_TOP = 0.30
CARD_ZONE_END = 0.60       # 이 아래로는 아무것도 그리지 않는다

INK = (59, 53, 80)
SUB = (124, 117, 143)
RED = (220, 66, 88)
BLUE = (52, 112, 212)
ACCENT = (132, 92, 196)    # 初一·十五
CARD_FILL = (255, 255, 255, 206)
SHADOW = (84, 60, 136, 40)
GRAD_TOP = (232, 225, 250)     # 라벤더
GRAD_BOTTOM = (252, 225, 237)  # 핑크

MONTH_EN = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
WEEKDAY_JP = "月火水木金土日"   # date.weekday() 순서
WEEKDAY_TW = "一二三四五六日"
FORBIDDEN_TW = ("補班",)


class CalendarCheckError(AssertionError):
    pass


# ====================================================================== 모델
@dataclass
class Cell:
    date: dt.date
    row: int
    col: int
    color: str = "ink"                    # ink | red | blue
    holiday: str = ""                     # 작게 쓰는 휴일 이름
    lunar: str = ""                       # 대만: 農曆/節氣 한 줄
    lunar_extra: str = ""                 # 대만: 初一과 겹친 節氣
    emphasis: bool = False                # 대만: 初一·十五


@dataclass
class MonthModel:
    country: str
    year: int
    month: int
    start: str
    holidays_on: bool
    weekday_labels: list
    weekday_colors: list
    rows: int
    cells: list = field(default_factory=list)


def _days(year, month):
    d = dt.date(year, month, 1)
    while d.month == month:
        yield d
        d += dt.timedelta(days=1)


def _col_of(day, start):
    return day.isoweekday() % 7 if start == "sun" else day.weekday()


def build_month(country, year, month, start="sun", holidays_on=True):
    caldata.ensure_in_range(year, month)
    if country == "tw" and start != "sun":
        raise ValueError("대만 달력은 週日 시작만 낸다(정부 辦公日曆表 기준)")
    order = list(range(6, 13)) if start == "sun" else list(range(7))   # weekday() 값 순서
    order = [w % 7 for w in order]
    names = WEEKDAY_JP if country == "jp" else WEEKDAY_TW
    labels = [names[w] for w in order]
    colors = []
    for w in order:
        if w == 6:
            colors.append("red")
        elif w == 5 and country == "jp":
            colors.append("blue")
        else:
            colors.append("ink")

    lead = _col_of(dt.date(year, month, 1), start)
    days = list(_days(year, month))
    rows = (lead + len(days) + 6) // 7
    model = MonthModel(country, year, month, start, holidays_on, labels, colors, rows)

    jp_hol = caldata.jp_holidays() if country == "jp" else {}
    tw_hol = caldata.tw_holidays() if country == "tw" else {}
    for i, d in enumerate(days):
        row, col = divmod(lead + i, 7)
        cell = Cell(d, row, col)
        if country == "jp":
            if holidays_on and d in jp_hol:
                cell.color, cell.holiday = "red", jp_hol[d]
            elif d.weekday() == 6:
                cell.color = "red"
            elif d.weekday() == 5:
                cell.color = "blue"
        else:
            h = tw_hol.get(d)
            if holidays_on and h and h["kind"] in ("holiday", "makeup_holiday"):
                cell.color, cell.holiday = "red", h["label"]
            elif d.weekday() == 6:
                cell.color = "red"
            info = caldata.lunar_info(d)
            cell.lunar, cell.lunar_extra, cell.emphasis = info["text"], info["extra"], info["emphasis"]
        model.cells.append(cell)
    return model


# ====================================================================== 검사
def _fail(msg):
    raise CalendarCheckError(msg)


def check(model):
    """그리기 전 대조. 빨간 날·요일 칸·휴일 이름·農曆을 원문 데이터와 맞춰 보고, 어긋나면 예외."""
    y, m = model.year, model.month
    caldata.ensure_in_range(y, m)
    days = list(_days(y, m))

    # 1) 날짜가 빠짐·중복 없이 다 있다
    if sorted(c.date for c in model.cells) != days:
        _fail(f"{y}-{m:02d}: 칸의 날짜 목록이 그 달과 다르다")

    # 2) 칸 위치 = 요일. 머리글 글자와 날짜의 실제 요일이 같은 열인지도 본다
    names = WEEKDAY_JP if model.country == "jp" else WEEKDAY_TW
    first = dt.date(y, m, 1)
    lead = _col_of(first, model.start)
    for c in model.cells:
        if divmod(lead + c.date.day - 1, 7) != (c.row, c.col):
            _fail(f"{c.date}: 칸 위치 ({c.row},{c.col}) 틀림")
        if model.weekday_labels[c.col] != names[c.date.weekday()]:
            _fail(f"{c.date}: {model.weekday_labels[c.col]} 열에 놓였지만 실제는 {names[c.date.weekday()]}")
    if model.rows != (lead + len(days) + 6) // 7:
        _fail("주 수 틀림")

    red = {c.date for c in model.cells if c.color == "red"}
    blue = {c.date for c in model.cells if c.color == "blue"}
    labelled = {c.date: c.holiday for c in model.cells if c.holiday}
    sundays = {d for d in days if d.weekday() == 6}
    saturdays = {d for d in days if d.weekday() == 5}

    if model.country == "jp":
        import extract_jp  # 원문 Shift_JIS CSV를 jp_holidays.csv와 별개 경로로 다시 읽는다
        raw = extract_jp.read_raw()
        raw_month = {d: extract_jp.display_name(d, raw) for d in raw if (d.year, d.month) == (y, m)}
        csv_month = {d: n for d, n in caldata.jp_holidays().items() if (d.year, d.month) == (y, m)}
        if raw_month != csv_month:
            _fail(f"jp_holidays.csv가 内閣府 원문과 다르다: {csv_month} vs {raw_month}")
        expected_hol = raw_month if model.holidays_on else {}
        expected_red = sundays | set(expected_hol)
        expected_blue = saturdays - expected_red
        if red != expected_red:
            _fail(f"빨간 날 불일치: 그림 {sorted(red)} / 원문 {sorted(expected_red)}")
        if blue != expected_blue:
            _fail(f"파란 날 불일치: 그림 {sorted(blue)} / 원문 {sorted(expected_blue)}")
        if labelled != expected_hol:
            _fail(f"祝日 이름 불일치: 그림 {labelled} / 원문 {expected_hol}")
        if any(c.lunar for c in model.cells):
            _fail("일본 달력에 農曆이 들어갔다")
        return True

    # ---- 대만: 정부 辦公日曆表 xlsx(날별 放假日·農曆)를 두 번째 출처로
    official = caldata.tw_official_days()
    tw_hol = caldata.tw_holidays()
    if blue:
        _fail("대만 달력에 파란 날이 있다")
    for d in days:
        off, _ = official[d]
        if d.weekday() >= 5 and not off:
            # 補班: 빨갛지 않아야 하고 「補班」 글자도 없어야 한다
            if d in red:
                _fail(f"{d} 補班인데 빨갛다")
        h = tw_hol.get(d)
        if h and h["kind"] != "makeup_workday" and not off:
            _fail(f"{d} tw_holidays.csv엔 放假日({h['name']})인데 정부 표엔 上班日")
    if not sundays <= red:
        _fail(f"빨갛지 않은 週日: {sorted(sundays - red)}")
    expected_named = ({d: h["label"] for d, h in tw_hol.items()
                       if (d.year, d.month) == (y, m) and h["kind"] != "makeup_workday"}
                      if model.holidays_on else {})
    weekday_red = {d for d in red if d.weekday() < 5}
    expected_weekday_red = ({d for d in days if d.weekday() < 5 and official[d][0]}
                            if model.holidays_on else set())
    if weekday_red != expected_weekday_red:
        _fail(f"평일 빨간 날 불일치: 그림 {sorted(weekday_red)} / 정부 표 {sorted(expected_weekday_red)}")
    sat_red = {d for d in red if d.weekday() == 5}
    if sat_red != {d for d in expected_named if d.weekday() == 5}:
        _fail(f"土曜 빨간 날 불일치: {sorted(sat_red)}")
    if labelled != expected_named:
        _fail(f"放假日 이름 불일치: 그림 {labelled} / 데이터 {expected_named}")
    if not set(labelled) <= red:
        _fail("이름은 있는데 빨갛지 않은 날")
    festival_texts = {h["label"] for h in tw_hol.values()} | {h["name"] for h in tw_hol.values()}
    for c in model.cells:
        for text in (c.holiday, c.lunar, c.lunar_extra):
            if any(f in text for f in FORBIDDEN_TW):
                _fail(f"{c.date}: 「補班」 글자")
        off_text = official[c.date][1]
        if off_text in festival_texts:      # 정부 표는 節日 칸에 農曆 대신 節日 이름을 쓴다
            continue
        if c.lunar + c.lunar_extra != off_text:     # 初一+節氣 겹친 날은 정부 표도 두 줄(「四月大」「立夏」)
            _fail(f"{c.date} 農曆 불일치: 계산 {c.lunar}{c.lunar_extra} / 정부 표 {off_text}")
        if c.emphasis != (c.lunar.endswith(("月大", "月小")) or c.lunar == "十五"):
            _fail(f"{c.date} 初一·十五 강조 틀림")
    return True


# ====================================================================== 글꼴
class FontBook:
    """글자마다 주 글꼴에 있는지 cmap으로 확인하고, 없으면 Noto로, 그래도 없으면 예외(두부 □ 방지)."""

    def __init__(self, country):
        from fontTools.ttLib import TTFont
        if country == "jp":
            self.specs = {
                "bold": (FONTS / "zenmarugothic/ZenMaruGothic-Bold.ttf", None),
                "medium": (FONTS / "zenmarugothic/ZenMaruGothic-Medium.ttf", None),
            }
            self.fallback = {"bold": (FONTS / "notosansjp/NotoSansJP[wght].ttf", 700),
                             "medium": (FONTS / "notosansjp/NotoSansJP[wght].ttf", 500)}
        else:
            huninn = FONTS / "huninn/Huninn-Regular.ttf"
            self.specs = {"bold": (huninn, None), "medium": (huninn, None)}
            self.fallback = {"bold": (FONTS / "notosanstc/NotoSansTC[wght].ttf", 700),
                             "medium": (FONTS / "notosanstc/NotoSansTC[wght].ttf", 500)}
        self.country = country
        self._cmaps = {}
        for path, _ in list(self.specs.values()) + list(self.fallback.values()):
            if path not in self._cmaps:
                tt = TTFont(str(path), lazy=True)
                self._cmaps[path] = set(tt.getBestCmap())
                tt.close()
        self._cache = {}

    def _load(self, spec, size):
        key = (spec, size)
        if key not in self._cache:
            path, weight = spec
            f = ImageFont.truetype(str(path), size)
            if weight is not None:
                f.set_variation_by_axes([weight])
            self._cache[key] = f
        return self._cache[key]

    def font_for(self, text, style, size):
        chars = {ord(ch) for ch in text if not ch.isspace()}
        primary = self.specs[style]
        if chars <= self._cmaps[primary[0]]:
            return self._load(primary, size), primary[0].name
        fb = self.fallback[style]
        if chars <= self._cmaps[fb[0]]:
            return self._load(fb, size), fb[0].name
        missing = "".join(sorted(chr(c) for c in chars - self._cmaps[fb[0]]))
        raise CalendarCheckError(f"글꼴에 없는 글자(두부가 됨): {missing!r} in {text!r}")


# ====================================================================== 그리기
def _cover(img, size):
    w, h = size
    scale = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((left, top, left + w, top + h))


def _gradient(size):
    w, h = size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(GRAD_TOP, GRAD_BOTTOM)))
    return col.resize((w, h))


class Painter:
    def __init__(self, layer, fonts, scale, country):
        self.draw = ImageDraw.Draw(layer)
        self.fonts = fonts
        self.s = scale
        self.country = country
        self.log = []          # (text, font file, bbox) — 겹침 검사·보고용

    def px(self, v):
        return round(v * self.s)

    def text(self, xy, text, style, size, fill, anchor="ms", stroke=0):
        if self.country == "tw" and any(f in text for f in FORBIDDEN_TW):
            raise CalendarCheckError("「補班」은 그리지 않는다")
        font, fname = self.fonts.font_for(text, style, self.px(size))
        sw = self.px(stroke) if stroke else 0
        self.draw.text(xy, text, font=font, fill=fill, anchor=anchor,
                       stroke_width=sw, stroke_fill=fill if sw else None)
        bbox = self.draw.textbbox(xy, text, font=font, anchor=anchor, stroke_width=sw)
        self.log.append((text, fname, bbox))
        return font

    def width(self, text, style, size, stroke=0):
        font, _ = self.fonts.font_for(text, style, self.px(size))
        return font.getlength(text) + 2 * (self.px(stroke) if stroke else 0)

    def extent(self, text, style, size, stroke=0):
        """기준선 위로 몇 px, 아래로 몇 px 차지하는지(실제 글리프 기준)."""
        font, _ = self.fonts.font_for(text, style, self.px(size))
        sw = self.px(stroke) if stroke else 0
        _, top, _, bottom = font.getbbox(text, anchor="ls", stroke_width=sw)
        return -top, bottom

    def fit_size(self, text, style, size, max_w):
        """칸 폭을 넘으면 글자 크기를 줄인다(이름이 긴 祝日)."""
        while size > 12 and self.width(text, style, size) > max_w:
            size -= 1
        return size


COLOR = {"ink": INK, "red": RED, "blue": BLUE}

# 글자 크기는 마스터(폭 1290) 기준 px. 6주짜리 달에서 칸이 모자라면 날짜 칸 글자만 같이 줄인다.
STYLE = {
    "jp": dict(header=104, header_stroke=0, header_small=42, weekday=34, weekday_stroke=0,
               top_pad=38, head_gap=44,
               num=52, num_stroke=0, lunar=0, hol=26, gap1=12, gap2=0,
               sample_hol="建国記念の日"),
    "tw": dict(header=84, header_stroke=1.3, header_small=40, weekday=34, weekday_stroke=0.5,
               top_pad=34, head_gap=30,
               num=44, num_stroke=1.0, lunar=26, hol=23, gap1=7, gap2=4,
               sample_hol="和平紀念日"),
}
MIN_ROW_GAP = 14          # 위 칸 맨 아래 글자와 아래 칸 숫자 사이(칸 안 간격보다 커야 묶음이 읽힌다)
MIN_SIZES = dict(num=38, lunar=22, hol=20)


def _cell_metrics(p, st):
    """날짜 칸 글자 묶음의 높이와 기준선 간격(px)."""
    num_up, _ = p.extent("28", "bold", st["num"], st["num_stroke"])
    hol_up, hol_down = p.extent(st["sample_hol"], "medium", st["hol"])
    gap1, gap2 = p.px(st["gap1"]), p.px(st["gap2"])
    if st["lunar"]:
        lun_up, lun_down = p.extent("十二月小", "medium", st["lunar"])
        lunar_base = num_up + gap1 + lun_up
        hol_base = lunar_base + lun_down + gap2 + hol_up
    else:
        lunar_base = None
        hol_base = num_up + gap1 + hol_up
    return dict(num_base=num_up, lunar_base=lunar_base, hol_base=hol_base, block=hol_base + hol_down)


def _draw_overlay(model, W, H, fonts):
    s = W / MASTER_W
    st = dict(STYLE[model.country])
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    p = Painter(layer, fonts, s, model.country)

    # 카드 자리: 30% ~ (60% - 그림자 여유)
    cl, cr = round(56 * s), W - round(56 * s)
    ct, cb = round(CARD_TOP * H), round(CARD_ZONE_END * H) - round(24 * s)
    radius = round(56 * s)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((cl, ct + round(5 * s), cr, cb + round(5 * s)),
                                             radius=radius, fill=SHADOW)
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(round(8 * s))))
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((cl, ct, cr, cb), radius=radius, fill=CARD_FILL)
    layer.alpha_composite(card)

    gl, gr = cl + round(30 * s), cr - round(30 * s)
    cw = (gr - gl) / 7

    # 머리: 일본 「12」+「December」 / 대만 「12月」+「2026」
    big = str(model.month) if model.country == "jp" else f"{model.month}月"
    small = MONTH_EN[model.month - 1] if model.country == "jp" else str(model.year)
    big_up, big_down = p.extent(big, "bold", st["header"], st["header_stroke"])
    header_base = ct + p.px(st["top_pad"]) + big_up
    hx = round(gl + 12 * s)
    p.text((hx, header_base), big, "bold", st["header"], INK, anchor="ls", stroke=st["header_stroke"])
    bx = hx + p.width(big, "bold", st["header"], st["header_stroke"]) + round(20 * s)
    p.text((bx, header_base), small, "medium", st["header_small"], SUB, anchor="ls")

    # 요일
    wk_up, wk_down = p.extent("日", "medium", st["weekday"], st["weekday_stroke"])
    wk_base = header_base + big_down + p.px(st["head_gap"]) + wk_up
    for i, (lab, col) in enumerate(zip(model.weekday_labels, model.weekday_colors)):
        p.text((round(gl + (i + 0.5) * cw), wk_base), lab, "medium", st["weekday"], COLOR[col],
               stroke=st["weekday_stroke"])
    rule_y = wk_base + wk_down + round(12 * s)
    p.draw.line((gl, rule_y, gr, rule_y), fill=SUB + (90,), width=max(1, round(2 * s)))

    # 날짜 칸: 줄 높이에 묶음이 들어가도록(아래 칸과 MIN_ROW_GAP 이상 띄움) 필요하면 줄인다
    gt, gb = rule_y + round(6 * s), cb - round(10 * s)
    rh = (gb - gt) / model.rows
    while True:
        mt = _cell_metrics(p, st)
        if mt["block"] + p.px(MIN_ROW_GAP) <= rh:
            break
        # 큰 숫자부터 줄이고(농력·휴일 이름의 가독성이 먼저), 그다음 작은 글씨
        if st["num"] > MIN_SIZES["num"]:
            st["num"] -= 1
        elif st["hol"] > MIN_SIZES["hol"] or (st["lunar"] and st["lunar"] > MIN_SIZES["lunar"]):
            st["hol"] = max(MIN_SIZES["hol"], st["hol"] - 1)
            if st["lunar"]:
                st["lunar"] = max(MIN_SIZES["lunar"], st["lunar"] - 1)
        else:
            _fail(f"칸이 모자람: 줄 {rh:.0f}px < 묶음 {mt['block']}+{p.px(MIN_ROW_GAP)}px")

    model.fitted = {k: st[k] for k in ("num", "lunar", "hol")}
    for c in model.cells:
        cx = round(gl + (c.col + 0.5) * cw)
        top = gt + c.row * rh + (rh - mt["block"]) / 2
        p.text((cx, round(top + mt["num_base"])), str(c.date.day), "bold", st["num"], COLOR[c.color],
               stroke=st["num_stroke"])
        if st["lunar"]:
            lsize = p.fit_size(c.lunar, "medium", st["lunar"], cw - p.px(8))
            if c.emphasis:
                p.text((cx, round(top + mt["lunar_base"])), c.lunar, "medium", lsize, ACCENT, stroke=0.6)
            else:
                p.text((cx, round(top + mt["lunar_base"])), c.lunar, "medium", lsize, SUB)
        second = c.holiday or c.lunar_extra
        if second:
            hsize = p.fit_size(second, "medium", st["hol"], cw - p.px(8))
            p.text((cx, round(top + mt["hol_base"])), second, "medium", hsize, RED if c.holiday else SUB)

    check_text_layout(p.log, (cl, ct, cr, cb), p.px(4))
    return layer, p.log


def check_text_layout(log, card, margin):
    """글자끼리 겹치지 않고, 모두 카드 안(모서리 여백 포함)에 있는지."""
    cl, ct, cr, cb = card
    boxes = [(t, b) for t, _, b in log]
    for t, (x0, y0, x1, y1) in boxes:
        if x0 < cl + margin or x1 > cr - margin or y0 < ct + margin or y1 > cb - margin:
            _fail(f"카드 밖으로 나간 글자: {t!r} {x0, y0, x1, y1}")
    for i in range(len(boxes)):
        ti, (a0, b0, a1, b1) = boxes[i]
        for j in range(i + 1, len(boxes)):
            tj, (c0, d0, c1, d1) = boxes[j]
            if a0 < c1 and c0 < a1 and b0 < d1 and d0 < b1:
                _fail(f"글자 겹침: {ti!r} {boxes[i][1]} / {tj!r} {boxes[j][1]}")


def check_zones(layer, H):
    """시계 구역(0~28%)과 캐릭터 구역(60~100%)에 칠해진 픽셀이 없는지."""
    alpha = layer.getchannel("A").point(lambda a: 255 if a > 2 else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        _fail("아무것도 그려지지 않았다")
    top, bottom = bbox[1], bbox[3]
    if top < CLOCK_ZONE_END * H:
        _fail(f"시계 구역 침범: y={top} < {CLOCK_ZONE_END * H:.0f}")
    if bottom > CARD_ZONE_END * H:
        _fail(f"캐릭터 구역 침범: y={bottom} > {CARD_ZONE_END * H:.0f}")
    return bbox


def render(country, year, month, start="sun", holidays_on=True, bg=None, size=(1290, 2796)):
    model = build_month(country, year, month, start, holidays_on)
    check(model)                                   # 그리기 전, 매번
    W, H = size
    fonts = FontBook(country)
    base = _cover(Image.open(bg).convert("RGB"), size) if bg else _gradient(size)
    layer, log = _draw_overlay(model, W, H, fonts)
    check_zones(layer, H)
    out = base.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB"), model, log


def out_name(country, year, month, start, holidays_on, size):
    return f"{country}_{year % 100:02d}{month:02d}_{start}_{'on' if holidays_on else 'off'}_{size[0]}x{size[1]}.png"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", required=True, choices=["jp", "tw"])
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--start", default="sun", choices=["sun", "mon"])
    ap.add_argument("--holidays", default="on", choices=["on", "off"])
    ap.add_argument("--bg", help="배경 PNG(cover로 잘라 맞춤). 없으면 라벤더→핑크 그라데이션")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default=",".join(f"{w}x{h}" for w, h in DEFAULT_SIZES))
    a = ap.parse_args(argv)
    year, month = (int(x) for x in a.month.split("-"))
    sizes = [tuple(int(v) for v in s.split("x")) for s in a.sizes.split(",")]
    out_dir = pathlib.Path(a.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        img, model, _ = render(a.country, year, month, a.start, a.holidays == "on", a.bg, size)
        path = out_dir / out_name(a.country, year, month, a.start, a.holidays == "on", size)
        img.save(path, optimize=True)
        reds = sorted(c.date.day for c in model.cells if c.color == "red")
        print(f"{path}  red={reds}  sizes={model.fitted}")


if __name__ == "__main__":
    main()
