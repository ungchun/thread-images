"""달력 데이터: 일본 祝日, 대만 放假日, 대만 農曆·節氣.

공휴일은 calendar/data/*.csv (원문에서 뽑은 표)만 읽는다. 손으로 외운 날짜는 없다.
농력·절기는 lunar_python(UTC+8 기준, 대만과 같은 시간대)으로 계산하고,
표기는 대만 政府行政機關辦公日曆表를 따른다: 달 이름 「正月·二月…十月·十一月·十二月」+「大/小」
(「冬月」「臘月」을 쓰지 않는다), 날 이름 「初一…初十·十一…十九·二十·廿一…廿九·三十」.
"""
import csv
import datetime as dt
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"

RANGE_FIRST = dt.date(2026, 12, 1)
RANGE_LAST = dt.date(2027, 12, 31)


class DataRangeError(ValueError):
    pass


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def ensure_in_range(year, month):
    first = dt.date(year, month, 1)
    if not (RANGE_FIRST <= first <= RANGE_LAST):
        raise DataRangeError(
            f"{year}-{month:02d}: 공휴일 데이터 범위({RANGE_FIRST:%Y-%m}~{RANGE_LAST:%Y-%m}) 밖. "
            "tools/ 의 추출기로 원문을 새로 받아 넓힌 뒤 렌더한다.")


# ---------------------------------------------------------------- 일본
def jp_holidays():
    """{date: label}. label은 표시용(「休日」→「振替休日」 등)."""
    return {dt.date.fromisoformat(r["date"]): r["label"] for r in _read_csv(DATA / "jp_holidays.csv")}


# ---------------------------------------------------------------- 대만
def tw_holidays():
    """{date: {kind, name, label}}. 補班(makeup_workday)도 여기 올 수 있지만 그리지 않는다."""
    out = {}
    for r in _read_csv(DATA / "tw_holidays.csv"):
        out[dt.date.fromisoformat(r["date"])] = {"kind": r["kind"], "name": r["name"], "label": r["label"]}
    return out


def tw_official_days():
    """정부 辦公日曆表 xlsx에서 뽑은 날별 {date: (off, lunar_text)}. check()의 두 번째 출처."""
    return {dt.date.fromisoformat(r["date"]): (r["off"] == "1", r["lunar"])
            for r in _read_csv(DATA / "tw_dgpa_days.csv")}


# ---------------------------------------------------------------- 農曆·節氣
_DIGITS = "一二三四五六七八九十"
_MONTHS = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

# lunar_python은 簡體 이름(또는 다음 해 몫은 병음 키)을 돌려준다 → 대만 정자.
_JIEQI_TW = {
    "立春": "立春", "雨水": "雨水", "惊蛰": "驚蟄", "春分": "春分", "清明": "清明", "谷雨": "穀雨",
    "立夏": "立夏", "小满": "小滿", "芒种": "芒種", "夏至": "夏至", "小暑": "小暑", "大暑": "大暑",
    "立秋": "立秋", "处暑": "處暑", "白露": "白露", "秋分": "秋分", "寒露": "寒露", "霜降": "霜降",
    "立冬": "立冬", "小雪": "小雪", "大雪": "大雪", "冬至": "冬至", "小寒": "小寒", "大寒": "大寒",
    "DONG_ZHI": "冬至", "XIAO_HAN": "小寒", "DA_HAN": "大寒", "LI_CHUN": "立春",
    "YU_SHUI": "雨水", "JING_ZHE": "驚蟄",
}


def lunar_day_name(n):
    if not 1 <= n <= 30:
        raise ValueError(n)
    if n <= 10:
        return "初" + _DIGITS[n - 1]
    if n < 20:
        return "十" + _DIGITS[n - 11]
    if n == 20:
        return "二十"
    if n < 30:
        return "廿" + _DIGITS[n - 21]
    return "三十"


def lunar_info(day):
    """대만 달력 칸에 들어갈 농력 정보.

    returns dict:
      month, day, leap, month_days(29/30),
      month_label  e.g. 「十二月小」「正月大」「閏六月小」 (그 달 初一에만 씀)
      day_name     e.g. 「初二」「十五」
      jieqi        e.g. 「冬至」 or ""
      text         칸에 그릴 한 줄: 初一이면 month_label, 節氣 날이면 節氣, 그 외 day_name
      extra        初一과 節氣가 겹친 날의 節氣(그 밖엔 "")
      emphasis     칸에 쓴 글자가 初一(달 이름)이나 十五일 때만(節氣로 바뀐 날은 강조 안 함)
    """
    from lunar_python import LunarMonth, Solar

    lun = Solar.fromYmd(day.year, day.month, day.day).getLunar()
    m = lun.getMonth()
    leap = m < 0
    month_days = LunarMonth.fromYm(lun.getYear(), m).getDayCount()
    raw_jq = lun.getJieQi()
    jieqi = _JIEQI_TW[raw_jq] if raw_jq else ""
    month_label = ("閏" if leap else "") + _MONTHS[abs(m) - 1] + "月" + ("大" if month_days == 30 else "小")
    d = lun.getDay()
    day_name = lunar_day_name(d)
    if d == 1:
        text, extra = month_label, jieqi
    elif jieqi:
        text, extra = jieqi, ""
    else:
        text, extra = day_name, ""
    return {
        "lunar_year": lun.getYear(), "month": abs(m), "day": d, "leap": leap, "month_days": month_days,
        "month_label": month_label, "day_name": day_name, "jieqi": jieqi,
        "text": text, "extra": extra, "emphasis": text in (month_label, "十五"),
    }
