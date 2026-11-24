import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign_publish as campaign


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.row = {"id": "test-bts", "account": "test", "caption": "plans", "topic_tag": "BTS",
                    "scheduled_utc": "2020-01-01T00:00:00+00:00", "images": ["a.png", "b.png"],
                    "media_base": "https://example.org/"}
        self.root = {"id": "post", "username": "test", "text": "plans", "media_type": "CAROUSEL_ALBUM",
                     "children": {"data": [{"id": "1"}, {"id": "2"}]}, "topic_tag": "BTS"}
        self.patchers = [patch.object(campaign, "STATE", self.state), patch("run.creds", return_value=("test-token", "uid"))]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def identity(self, token, path, **kwargs):
        if path == "me":
            return {"id": "uid", "username": "test"}
        if path == "post":
            return self.root
        raise AssertionError("Unexpected API call " + path)

    def test_future_does_not_create_or_publish(self):
        self.row["scheduled_utc"] = "2099-01-01T00:00:00+00:00"
        with patch.object(campaign, "api", side_effect=self.identity) as api:
            with self.assertRaises(AssertionError):
                campaign.publish(self.row)
            self.assertEqual(len(api.call_args_list), 1)

    def test_history_reconciles_without_republication(self):
        with patch.object(campaign, "api", side_effect=self.identity), patch.object(campaign, "history", return_value=[self.root]):
            self.assertEqual(campaign.publish(self.row), "post")
        self.assertEqual(json.loads(self.state.read_text())["test-bts"]["status"], "PUBLISHED")

    def test_uncertain_publish_never_repeats(self):
        self.state.write_text(json.dumps({"test-bts": {"publish_requested_at": "earlier"}}))
        with patch.object(campaign, "api", side_effect=self.identity), patch.object(campaign, "history", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "outcome uncertain"):
                campaign.publish(self.row)

    def test_bts_tag_and_two_images_are_sent(self):
        sent = []
        def api(token, path, **kwargs):
            if path == "me" or path == "post":
                return self.identity(token, path, **kwargs)
            sent.append((path, kwargs))
            if path == "uid/threads_publish":
                return {"id": "post"}
            return {"id": "container" + str(len(sent))}
        with patch.object(campaign, "api", side_effect=api), patch.object(campaign, "history", return_value=[]), patch.object(campaign, "ready"):
            self.assertEqual(campaign.publish(self.row), "post")
            self.assertEqual(campaign.publish(self.row), "post")
        self.assertEqual(len([x for x in sent if x[1].get("is_carousel_item")]), 2)
        parents = [x for x in sent if x[1].get("media_type") == "CAROUSEL"]
        self.assertEqual(parents[0][1]["topic_tag"], "BTS")
        self.assertEqual(len([x for x in sent if x[0].endswith("threads_publish")]), 1)

    def test_unrelated_schedule_has_no_exception(self):
        self.assertIsNone(campaign.entry("any", "test", "texts/other.txt", [], "plans"))


if __name__ == "__main__":
    unittest.main()
