"""行政院人事行政總處 辦公日曆表 xlsx(원문) → calendar/data/tw_dgpa_days.csv.

    .work/venv/bin/python calendar/tools/extract_dgpa.py   (openpyxl 필요)

xlsx는 연 단위 표다. 날짜 칸 채움색 FFFF99FF = 放假日, 날짜 아래 칸 = 農曆·節氣 표기.
날마다 (放假日 여부, 공식 農曆 표기)를 뽑아 둔다. render.check()와 테스트가
이 표를 「두 번째 출처」로 써서 tw_holidays.csv와 農曆 계산을 대조한다.
"""
import csv
import datetime as dt
import pathlib

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "source"
OUT = ROOT / "data" / "tw_dgpa_days.csv"
SOURCES = [
    (2026, "dgpa_115_calendar.xlsx",
     "https://www.dgpa.gov.tw/information?uid=30&pid=12573"),
    (2027, "dgpa_116_calendar.xlsx",
     "https://www.dgpa.gov.tw/information?uid=30&pid=12982"),
]
FETCHED = "2026-11-17"
RANGE_FIRST = dt.date(2026, 12, 1)
RANGE_LAST = dt.date(2027, 12, 31)
OFF_FILL = "FFFF99FF"
WEEKDAY_ZH = "一二三四五六日"


def parse_year(path, year):
    """xlsx 한 해 → {date: (off, lunar_label)}. 칸 위치와 요일이 어긋나면 바로 멈춘다."""
    ws = openpyxl.load_workbook(path).worksheets[0]
    out = {}
    for band, top in enumerate((3, 17, 31, 45)):          # 석 달씩 4줄
        for k, col0 in enumerate((2, 9, 16)):            # B~H, I~O, P~V
            month = band * 3 + k + 1
            for week in range(6):
                date_row = top + 2 + week * 2
                for d in range(7):                       # 日 一 二 ... 六
                    cell = ws.cell(row=date_row, column=col0 + d)
                    if not isinstance(cell.value, int):
                        continue
                    day = dt.date(year, month, cell.value)
                    if day.isoweekday() % 7 != d:
                        raise ValueError(f"{path}: {day} 요일 칸 불일치")
                    lunar = ws.cell(row=date_row + 1, column=col0 + d).value or ""
                    fill = cell.fill
                    off = bool(fill and fill.fill_type and fill.fgColor.rgb == OFF_FILL)
                    out[day] = (off, str(lunar).replace("\n", "").strip())
    days_in_year = (dt.date(year + 1, 1, 1) - dt.date(year, 1, 1)).days
    if len(out) != days_in_year:
        raise ValueError(f"{path}: {len(out)}일만 읽힘")
    return out


def main():
    days = {}
    for year, name, _url in SOURCES:
        days.update(parse_year(SRC_DIR / name, year))
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        for year, name, url in SOURCES:
            f.write(f"# source: 政府行政機關辦公日曆表 {year} xlsx {url} -> data/source/{name}\n")
        f.write(f"# fetched: {FETCHED} / off=1 means 放假日 (cell fill {OFF_FILL}); lunar = official 農曆/節氣 text\n")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "weekday", "off", "lunar"])
        d = RANGE_FIRST
        while d <= RANGE_LAST:
            off, lunar = days[d]
            w.writerow([d.isoformat(), WEEKDAY_ZH[d.weekday()], int(off), lunar])
            d += dt.timedelta(days=1)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
