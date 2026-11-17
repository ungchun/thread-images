"""内閣府「国民の祝日」CSV(Shift_JIS 원문) → calendar/data/jp_holidays.csv.

    python3 calendar/tools/extract_jp.py

원문은 calendar/data/source/cao_syukujitsu.csv 에 받은 그대로 둔다.
범위(RANGE_FIRST~RANGE_LAST)만 잘라 UTF-8로 옮기고, 「休日」은 표시용 이름을 붙인다.
"""
import csv
import datetime as dt
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source" / "cao_syukujitsu.csv"
OUT = ROOT / "data" / "jp_holidays.csv"
SOURCE_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
FETCHED = "2026-11-17"
RANGE_FIRST = dt.date(2026, 12, 1)
RANGE_LAST = dt.date(2027, 12, 31)
WEEKDAY_JA = "月火水木金土日"


def read_raw(path=SRC):
    """원문 CSV 전체를 {date: name}으로. 다른 코드(check)도 이 함수를 독립 경로로 쓴다."""
    out = {}
    with open(path, encoding="shift_jis", newline="") as f:
        rows = list(csv.reader(f))
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        y, m, d = (int(x) for x in row[0].strip().split("/"))
        out[dt.date(y, m, d)] = row[1].strip()
    return out


def display_name(day, raw):
    """원문의 「休日」은 振替休日인지 国民の休日인지 구분해 보여 준다.

    振替休日: 거슬러 올라가 연속된 祝日 가운데 일요일이 있다(祝日法 3조 2항).
    国民の休日: 앞뒤가 祝日인 평일(祝日法 3조 3항).
    """
    name = raw[day]
    if name != "休日":
        return name
    prev = day - dt.timedelta(days=1)
    while prev in raw:
        if prev.weekday() == 6:
            return "振替休日"
        prev -= dt.timedelta(days=1)
    nxt = day + dt.timedelta(days=1)
    if (day - dt.timedelta(days=1)) in raw and nxt in raw:
        return "国民の休日"
    raise ValueError(f"休日 {day}: 振替休日도 国民の休日도 아님 — 원문 확인 필요")


def main():
    raw = read_raw()
    rows = sorted((d, n) for d, n in raw.items() if RANGE_FIRST <= d <= RANGE_LAST)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(f"# source: 内閣府「国民の祝日について」 {SOURCE_URL} (Shift_JIS)\n")
        f.write(f"# fetched: {FETCHED} / raw copy: data/source/cao_syukujitsu.csv\n")
        f.write(f"# range: {RANGE_FIRST} ~ {RANGE_LAST} (2026-12 has no 祝日 in the source)\n")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "weekday", "name", "label"])
        for d, n in rows:
            w.writerow([d.isoformat(), WEEKDAY_JA[d.weekday()], n, display_name(d, raw)])
    print(f"wrote {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
