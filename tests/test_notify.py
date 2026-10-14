"""Run notifications: webhook validation, payload shape, no network in tests."""
import unittest
from unittest import mock

from src import notify


class NotifyTests(unittest.TestCase):
    def test_only_discord_webhook_urls_are_accepted(self):
        ok = ["https://discord.com/api/webhooks/123/abc-DEF_9",
              "https://discordapp.com/api/webhooks/1/x/",
              "https://ptb.discord.com/api/webhooks/1/x"]
        bad = ["", "http://discord.com/api/webhooks/1/x", "https://discord.com.evil.io/api/webhooks/1/x",
               "https://discord.com/api/webhooks/x/y", "https://example.com/hook"]
        for url in ok:
            self.assertTrue(notify.is_webhook_url(url), url)
        for url in bad:
            self.assertFalse(notify.is_webhook_url(url), url)

    def test_payload_is_one_coloured_embed_with_bounded_fields(self):
        body = notify.discord_payload("Girl Wars — Failed", "1 of 12 failed", "failed",
                                      {f"k{i}": "" for i in range(14)})
        embed = body["embeds"][0]
        self.assertEqual(embed["color"], notify.COLORS["failed"])
        self.assertEqual(len(embed["fields"]), 10)
        self.assertEqual(embed["fields"][0]["value"], "-")    # Discord refuses empty values

    def test_send_refuses_a_non_webhook_without_touching_the_network(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.assertEqual(notify.send_discord("https://example.com", "t", "m"), "not a Discord webhook URL")
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
