import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import locale_lint as L  # noqa: E402
import separation as S  # noqa: E402


def rules(text, lang, sev="block"):
    return [f for f in L.lint(text, lang) if f.severity == sev]


def has(text, lang, match, sev="block"):
    return any(match in f.match for f in rules(text, lang, sev))


class TW(unittest.TestCase):
    def test_mainland_terms(self):
        self.assertTrue(has("這個視頻很好看", "zh-TW", "視頻"))
        self.assertFalse(rules("這個影片很好看", "zh-TW"))

    def test_interjection_and_cloud(self):
        self.assertTrue(has("好哦", "zh-TW", "哦"))
        self.assertFalse(rules("好喔，雲在這裡", "zh-TW"))
        self.assertTrue(has("云在這裡", "zh-TW", "云"))

    def test_japanese_nakaguro_and_halfwidth(self):
        self.assertTrue(has("Trace・行事曆", "zh-TW", "・"))
        self.assertTrue(has("今天好累,想睡", "zh-TW", ","))
        self.assertFalse(rules("今天好累，想睡。Trace, 行事曆", "zh-TW"))

    def test_simplified_and_gyeop(self):
        self.assertTrue(has("这是我们的软件", "zh-TW", "这"))
        self.assertTrue(has("我們沒業配", "zh-TW", "沒業配"))
        self.assertFalse(rules("皇后大道走了三公里", "zh-TW"))          # 后·里는 번체에도 있다
        self.assertTrue(has("走了三公里，在后面", "zh-TW", "后", "warn"))

    def test_emoji_thresholds(self):
        self.assertTrue(has("好喔💕", "zh-TW", "💕", "warn"))
        self.assertFalse(rules("好喔", "zh-TW", "warn"))
        self.assertTrue(rules("好喔💕✨🔥", "zh-TW", "block"))
        self.assertFalse(rules("好喔💕✨", "zh-TW", "block"))


class JA(unittest.TestCase):
    def test_tilde_and_exclaim(self):
        self.assertTrue(has("すごい~", "ja", "~"))
        self.assertTrue(has("すごい!!", "ja", "!!"))
        self.assertTrue(has("すごい！！", "ja", "！！"))
        self.assertFalse(rules("すごい〜！", "ja"))

    def test_weekday(self):
        self.assertTrue(has("12/1は休みです", "ja", "12/1"))
        self.assertFalse(rules("12/1(火)は休みです", "ja"))
        self.assertFalse(rules("12/25〜12/27(日)は連休です", "ja"))

    def test_style_is_warn_only(self):
        t = "あなたの予定をアップグレードしましょう！ぜひ！"
        self.assertFalse(rules(t, "ja"))
        self.assertTrue(rules(t, "ja", "warn"))
        self.assertTrue(has("☁️と👇", "ja", "☁", "warn"))

    def test_url_and_control_lines_ignored(self):
        t = "予定です\n---\ndelay: 30\nmedia: a~b!!.png\nhttps://apps.apple.com/app/x?a=1~2&b=12/1!!\n{link}"
        self.assertEqual(L.lint(t, "ja"), [])

    def test_body_and_reply_separate(self):
        f = L.lint("予定です☁️\n---\n返信です~", "ja")
        self.assertEqual([(x.part, x.rule) for x in f if x.severity == "block"], [("reply", "punct")])
        self.assertEqual([x for x in L.lint("☁️\n---\n☁️", "ja") if x.rule == "emoji"], [])   # 각각 1개라 통과


class Accounts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        a = self.root / "accounts"
        for name, meta in (("off_jp", "JP Asia/Tokyo"), ("team_jp", "JP Asia/Tokyo"), ("x_jp", "JP Asia/Tokyo")):
            (a / name).mkdir(parents=True)
            (a / name / "meta.txt").write_text(meta)
        (a / "status.json").write_text(json.dumps({"accounts": {
            "off_jp": {"state": "official"}, "team_jp": {"state": "active"}}}))
        (a / "x.json").write_text(json.dumps({"accounts": {"x_jp": {"country": "JP", "state": "active"}}}))

    def tearDown(self):
        self.d.cleanup()

    def test_block_only_for_official(self):
        t = "すごい!!"
        blocks, _ = L.lint_for_account(t, "off_jp", self.root)
        self.assertTrue(blocks)
        blocks, notes = L.lint_for_account(t, "team_jp", self.root)
        self.assertEqual(blocks, [])
        self.assertTrue(any(f.severity == "block" for f in notes))   # 알리기만
        self.assertTrue(L.lint_for_account(t, "x_jp", self.root)[0])  # X 계정은 공식

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_separation(self):
        self.write("images/a/pic.png", "same-bytes")
        self.write("images/b/other_name.png", "same-bytes")      # 이름은 달라도 같은 파일
        self.write("texts/off.txt", "本文\n---\nアプリの名前は Trace だよ\nhttps://x.example/1")
        self.write("texts/team.txt", "別の本文\n---\nアプリの名前は Trace だよ\n👇")
        self.write("schedule.txt", "2026-11-20T03:00:00+00:00\tteam_jp\ttexts/team.txt\tb/other_name.png\t-\n")
        got = S.check_row(self.root, "off_jp", "2026-11-25T03:00:00+00:00", ["a/pic.png"], "texts/off.txt")
        kinds = {m.split(" ")[0] for sev, m in got if sev == "block"}
        self.assertEqual(kinds, {"이미지", "답글"})
        # 30일 밖이면 통과
        self.assertEqual(S.check_row(self.root, "off_jp", "2027-01-25T03:00:00+00:00", ["a/pic.png"], "texts/off.txt"), [])
        # 반대 방향은 warn
        rev = S.check_row(self.root, "team_jp", "2026-11-26T03:00:00+00:00", ["a/pic.png"], "texts/team.txt",
                          used=[{"account": "off_jp", "when": S._utc("2026-11-25T03:00:00+00:00"),
                                 "images": [S.image_key(self.root, "a/pic.png")], "sentences": set()}])
        self.assertEqual([sev for sev, _ in rev], ["warn"])


if __name__ == "__main__":
    unittest.main()
