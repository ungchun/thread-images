import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kitty_campaign as campaign
import run


class KittyCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.textfile = campaign.PREFIX + "20261128.txt"
        text = self.root / self.textfile
        text.parent.mkdir(parents=True)
        text.write_text("caption\n---\nmedia: -\n이거야\n\nhttps://example.com\n")
        (self.root / "images").mkdir()
        (self.root / "images/a.png").write_bytes(b"image")
        self.row = {"account": "jeongmin_trace", "textfile": self.textfile,
                    "scheduled_utc": "2026-11-28T01:00:00+00:00", "caption": "caption",
                    "images": ["a.png"], "sha256": [hashlib.sha256(b"image").hexdigest()],
                    "text_sha256": hashlib.sha256(text.read_bytes()).hexdigest()}
        self.args = (self.row["scheduled_utc"], "jeongmin_trace", self.textfile, ["a.png"], "caption")
        for patcher in [patch.object(campaign, "ROOT", self.root),
                        patch.object(campaign, "manifest", return_value={"posts": [self.row]})]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_exact_reservation_can_override_exclusion(self):
        states = {"jeongmin_trace": {"state": "excluded"}, "other": {"state": "paused"}}
        authorized = campaign.authorized_states(states, *self.args)
        self.assertEqual(authorized["jeongmin_trace"]["state"], "active")
        self.assertEqual(states["jeongmin_trace"]["state"], "excluded")
        self.assertEqual(authorized["other"], states["other"])
        self.assertIsNone(campaign.entry("any", "jeongmin_trace", "texts/unrelated.txt", [], "caption"))
        with self.assertRaises(AssertionError):
            campaign.entry("2026-11-29T01:00:00+00:00", *self.args[1:])

    def test_changed_reply_is_rejected(self):
        (self.root / self.textfile).write_text("caption\n---\nwrong reply")
        with self.assertRaisesRegex(AssertionError, "caption/reply"):
            campaign.entry(*self.args)

    def test_changed_image_is_rejected(self):
        (self.root / "images/a.png").write_bytes(b"different image")
        with self.assertRaisesRegex(AssertionError, "Changed image"):
            campaign.entry(*self.args)

    def test_daily_cap_still_applies(self):
        states = campaign.authorized_states({"jeongmin_trace": {"state": "excluded"}}, *self.args)
        now = campaign.datetime.fromisoformat(self.args[0])
        self.assertEqual(run.hold_reason("jeongmin_trace", now, states, count=lambda *_: 1), "cap")
        self.assertIsNone(run.hold_reason("jeongmin_trace", now, states, count=lambda *_: 0))


if __name__ == "__main__":
    unittest.main()
