"""달력 렌더러 검증.

    .work/venv/bin/python -m unittest discover -s calendar/tests -v
"""
import copy
import datetime as dt
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import caldata  # noqa: E402
import extract_jp  # noqa: E402
import render  # noqa: E402

D = dt.date


def month_days(y, m):
    return list(render._days(y, m))


class LunarAnchors(unittest.TestCase):
    """브리프에 박힌 기준값 — 라이브러리 계산이 이 값과 다르면 실패."""

    def test_jieqi(self):
        for day, name in [(D(2026, 12, 22), "冬至"), (D(2027, 1, 5), "小寒"),
                          (D(2027, 1, 20), "大寒"), (D(2027, 2, 4), "立春")]:
            self.assertEqual(caldata.lunar_info(day)["jieqi"], name, day)
            # 그 節氣가 앞뒤 날에는 없다(하루짜리)
            for nb in (day - dt.timedelta(days=1), day + dt.timedelta(days=1)):
                self.assertNotEqual(caldata.lunar_info(nb)["jieqi"], name)

    def test_lamyue_first_day(self):          # 臘月初一 2027-01-08
        info = caldata.lunar_info(D(2027, 1, 8))
        self.assertEqual((info["month"], info["day"], info["leap"]), (12, 1, False))
        self.assertEqual(info["text"], "十二月小")           # W7·xlsx 표기: 臘月 아님
        self.assertEqual(caldata.lunar_info(D(2027, 1, 7))["month"], 11)

    def test_new_year_and_eve(self):          # 正月初一 2027-02-06, 除夕 2027-02-05
        ny = caldata.lunar_info(D(2027, 2, 6))
        self.assertEqual((ny["month"], ny["day"]), (1, 1))
        self.assertEqual(ny["text"], "正月大")
        eve = caldata.lunar_info(D(2027, 2, 5))
        self.assertEqual(eve["month"], 12)
        self.assertEqual(eve["day"], eve["month_days"])    # 섣달 마지막 날 = 除夕
        self.assertEqual(eve["day_name"], "廿九")           # 十二月小라서 三十 없음

    def test_month_names_follow_dgpa(self):
        self.assertEqual(caldata.lunar_info(D(2026, 12, 9))["text"], "十一月大")  # 冬月 아님
        texts = {caldata.lunar_info(d)["text"] for d in month_days(2027, 1) + month_days(2026, 12)}
        for bad in ("冬月", "臘月", "腊月"):
            self.assertFalse(any(bad in t for t in texts), bad)

    def test_day_names(self):
        names = [caldata.lunar_day_name(n) for n in range(1, 31)]
        self.assertEqual(names[:3], ["初一", "初二", "初三"])
        self.assertEqual(names[9:12], ["初十", "十一", "十二"])
        self.assertEqual(names[19:22], ["二十", "廿一", "廿二"])
        self.assertEqual(names[29], "三十")


class LunarVsOfficialTable(unittest.TestCase):
    """2026-12 ~ 2027-12 매일: 계산한 農曆·節氣 == 정부 辦公日曆表 xlsx 칸 글자."""

    def test_full_range(self):
        official = caldata.tw_official_days()
        festival = {h["label"] for h in caldata.tw_holidays().values()}
        skipped, both, d = [], 0, caldata.RANGE_FIRST
        while d <= caldata.RANGE_LAST:
            text = official[d][1]
            if text in festival:
                skipped.append((d, text))
            else:
                info = caldata.lunar_info(d)
                self.assertEqual(info["text"] + info["extra"], text, d)   # 初一+節氣는 표에서 붙어 나온다
                both += bool(info["extra"])
            d += dt.timedelta(days=1)
        # 정부 표가 農曆 대신 節日 이름을 쓴 칸은 이 넷뿐이어야 한다
        self.assertEqual(skipped, [(D(2027, 4, 4), "兒童節"), (D(2027, 4, 5), "清明節"),
                                   (D(2027, 6, 9), "端午節"), (D(2027, 9, 15), "中秋節")])
        self.assertEqual(caldata.lunar_info(D(2027, 4, 5))["jieqi"], "清明")
        self.assertGreaterEqual(both, 1)                                  # 2027-05-06 四月大·立夏
        self.assertEqual(caldata.lunar_info(D(2027, 5, 6))["extra"], "立夏")


class JapanHolidays(unittest.TestCase):
    def month(self, y, m):
        return {d: n for d, n in caldata.jp_holidays().items() if (d.year, d.month) == (y, m)}

    def test_2026_12_none(self):
        self.assertEqual(self.month(2026, 12), {})

    def test_2027_01(self):
        self.assertEqual(self.month(2027, 1), {D(2027, 1, 1): "元日", D(2027, 1, 11): "成人の日"})

    def test_2027_02(self):
        self.assertEqual(self.month(2027, 2), {D(2027, 2, 11): "建国記念の日", D(2027, 2, 23): "天皇誕生日"})

    def test_csv_equals_raw_source(self):
        raw = extract_jp.read_raw()
        in_range = {d for d in raw if caldata.RANGE_FIRST <= d <= caldata.RANGE_LAST}
        self.assertEqual(in_range, set(caldata.jp_holidays()))
        self.assertEqual(caldata.jp_holidays()[D(2027, 3, 22)], "振替休日")   # 원문 「休日」

    def test_nenmatsu_nenshi_not_red(self):
        for y, m in [(2026, 12), (2027, 1)]:
            model = render.build_month("jp", y, m)
            for c in model.cells:
                if D(2026, 12, 29) <= c.date <= D(2027, 1, 3):
                    expect = c.date.weekday() == 6 or c.date == D(2027, 1, 1)
                    self.assertEqual(c.color == "red", expect, c.date)

    def test_holidays_off_variant(self):
        model = render.build_month("jp", 2027, 1, holidays_on=False)
        render.check(model)
        self.assertEqual({c.date for c in model.cells if c.color == "red"},
                         {d for d in month_days(2027, 1) if d.weekday() == 6})
        self.assertFalse(any(c.holiday for c in model.cells))
        self.assertEqual(next(c for c in model.cells if c.date == D(2027, 1, 1)).color, "ink")


class TaiwanHolidays(unittest.TestCase):
    def setUp(self):
        self.hol = caldata.tw_holidays()
        self.official = caldata.tw_official_days()

    def test_spring_festival_2027(self):
        span = [D(2027, 2, 4) + dt.timedelta(days=i) for i in range(7)]
        for d in span:
            self.assertIn(d, self.hol, d)
            self.assertTrue(self.official[d][0], d)
        for d in (D(2027, 2, 3), D(2027, 2, 11)):
            self.assertNotIn(d, self.hol)
            self.assertFalse(self.official[d][0], d)
        self.assertEqual([self.hol[d]["label"] for d in span],
                         ["小年夜", "除夕", "春節", "春節", "春節", "補假", "補假"])

    def test_2026_12_25_is_off(self):            # 115年 附表3: 行憲紀念日 12/25（五）放假
        self.assertTrue(self.official[D(2026, 12, 25)][0])
        self.assertEqual(self.hol[D(2026, 12, 25)]["name"], "行憲紀念日")
        dec = {d for d in self.hol if (d.year, d.month) == (2026, 12)}
        self.assertEqual(dec, {D(2026, 12, 25)})

    def test_holiday_csv_matches_official_table(self):
        off_weekdays = {d for d, (off, _) in self.official.items() if off and d.weekday() < 5}
        csv_weekdays = {d for d, h in self.hol.items() if d.weekday() < 5 and h["kind"] != "makeup_workday"}
        self.assertEqual(off_weekdays, csv_weekdays)
        for d, h in self.hol.items():
            self.assertTrue(self.official[d][0], d)

    def test_no_makeup_workday(self):            # 補班 없음 — 원문 확인
        weekend_work = [d for d, (off, _) in self.official.items() if d.weekday() >= 5 and not off]
        self.assertEqual(weekend_work, [])
        self.assertFalse(any(h["kind"] == "makeup_workday" for h in self.hol.values()))

    def test_2027_total_off_days_121(self):      # 新聞稿 「總放假日數121日」
        self.assertEqual(sum(1 for d, (off, _) in self.official.items() if d.year == 2027 and off), 121)

    def test_dec_2027_makeup_days(self):        # 新聞稿: 117/1/1(六) → 116/12/31(五) 補假
        self.assertEqual(self.hol[D(2027, 12, 31)]["kind"], "makeup_holiday")
        self.assertEqual(self.hol[D(2027, 12, 24)]["kind"], "makeup_holiday")


class Layout(unittest.TestCase):
    def test_first_day_position(self):
        self.assertEqual(D(2026, 12, 1).weekday(), 1)                   # 火
        sun = render.build_month("jp", 2026, 12, "sun")
        mon = render.build_month("jp", 2026, 12, "mon")
        first = lambda m: next(c for c in m.cells if c.date.day == 1)   # noqa: E731
        self.assertEqual((first(sun).row, first(sun).col), (0, 2))
        self.assertEqual(sun.weekday_labels[2], "火")
        self.assertEqual((first(mon).row, first(mon).col), (0, 1))
        self.assertEqual(mon.weekday_labels, list("月火水木金土日"))
        tw = render.build_month("tw", 2026, 12)
        self.assertEqual(tw.weekday_labels, list("日一二三四五六"))
        self.assertEqual(tw.weekday_labels[first(tw).col], "二")

    def test_tw_rejects_monday_start(self):
        with self.assertRaises(ValueError):
            render.build_month("tw", 2027, 1, "mon")

    def test_out_of_range_month(self):
        with self.assertRaises(caldata.DataRangeError):
            render.build_month("jp", 2028, 1)


class EveryMonthInRange(unittest.TestCase):
    def test_check_passes_every_variant(self):
        months = [(2026, 12)] + [(2027, m) for m in range(1, 13)]
        for y, m in months:
            for on in (True, False):
                for start in ("sun", "mon"):
                    render.check(render.build_month("jp", y, m, start, on))
                render.check(render.build_month("tw", y, m, "sun", on))


class CheckCatchesMistakes(unittest.TestCase):
    """check()가 실제로 틀린 그림을 막는지 — 모델을 일부러 망가뜨려 본다."""

    def broken(self, country, y, m, mutate):
        model = render.build_month(country, y, m)
        render.check(model)
        bad = copy.deepcopy(model)
        mutate(bad)
        with self.assertRaises(render.CalendarCheckError):
            render.check(bad)

    def cell(self, model, day):
        return next(c for c in model.cells if c.date.day == day)

    def test_jp_mutations(self):
        self.broken("jp", 2027, 1, lambda m: setattr(self.cell(m, 11), "color", "ink"))       # 祝日 빠짐
        self.broken("jp", 2027, 1, lambda m: setattr(self.cell(m, 4), "color", "red"))        # 年末年始 칠함
        self.broken("jp", 2027, 1, lambda m: setattr(self.cell(m, 2), "color", "ink"))        # 土 검정
        self.broken("jp", 2027, 1, lambda m: setattr(self.cell(m, 11), "holiday", ""))        # 이름 빠짐
        self.broken("jp", 2027, 1, lambda m: setattr(self.cell(m, 5), "col", 3))              # 칸 밀림
        self.broken("jp", 2027, 1, lambda m: m.weekday_labels.reverse())                      # 요일 머리 틀림

    def test_tw_mutations(self):
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 9), "color", "ink"))        # 補假 빠짐
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 11), "color", "red"))       # 開工일 칠함
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 13), "color", "red"))       # 그냥 土曜 칠함
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 5), "lunar", "三十"))       # 農曆 틀림
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 4), "lunar", "廿八"))       # 節氣 빠짐
        self.broken("tw", 2027, 2, lambda m: setattr(self.cell(m, 10), "holiday", "補班"))    # 補班 글자
        self.broken("tw", 2026, 12, lambda m: setattr(self.cell(m, 25), "color", "ink"))      # 行憲紀念日 빠짐


class Rendering(unittest.TestCase):
    def test_render_both_sizes_zones_and_glyphs(self):
        for country, y, m in [("jp", 2027, 1), ("tw", 2027, 1), ("tw", 2027, 2)]:
            for size in render.DEFAULT_SIZES:
                img, model, log = render.render(country, y, m, size=size)
                self.assertEqual(img.size, size)
                H = size[1]
                for text, font, (x0, y0, x1, y1) in log:
                    self.assertGreaterEqual(y0, render.CARD_TOP * H, text)
                    self.assertLessEqual(y1, render.CARD_ZONE_END * H, text)
                    self.assertNotIn("補班", text)
                fonts = {f for _, f, _ in log}
                expect = {"ZenMaruGothic-Bold.ttf", "ZenMaruGothic-Medium.ttf"} if country == "jp" \
                    else {"Huninn-Regular.ttf"}
                self.assertEqual(fonts, expect)          # 폴백 없이 주 글꼴로 전부 그려짐
                # 시계 구역(0~28%)과 캐릭터 구역(60%~)은 배경 그대로
                bg = render._gradient(size)
                for y_ in (0, int(0.28 * H) - 1, int(0.60 * H) + 1, H - 1):
                    for x_ in (0, size[0] // 2, size[0] - 1):
                        self.assertEqual(img.getpixel((x_, y_)), bg.getpixel((x_, y_)), (y_, x_))

    def test_missing_glyph_raises(self):
        fb = render.FontBook("tw")
        with self.assertRaises(render.CalendarCheckError):
            fb.font_for("\U0001F9FF\U000E0100", "medium", 20)

    def test_bg_cover(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bg.png"
            Image.new("RGB", (800, 600), (10, 200, 30)).save(p)
            img, _, _ = render.render("jp", 2026, 12, bg=str(p), size=(1179, 2556))
            self.assertEqual(img.size, (1179, 2556))
            self.assertEqual(img.getpixel((5, 5)), (10, 200, 30))

    def test_cli_filename(self):
        self.assertEqual(render.out_name("jp", 2026, 12, "mon", True, (1290, 2796)),
                         "jp_2612_mon_on_1290x2796.png")


if __name__ == "__main__":
    unittest.main()
