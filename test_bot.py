import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from bot import (
    CanvasClient,
    NotifierBot,
    parse_canvas_datetime,
    parse_course_ids,
    parse_reminder_hours,
)


class ConfigTests(unittest.TestCase):
    def test_parse_course_ids(self):
        self.assertEqual(parse_course_ids(" 12,34, 12 "), {"12", "34"})
        self.assertEqual(parse_course_ids(""), set())

    def test_parse_course_ids_rejects_non_numeric_values(self):
        with self.assertRaises(ValueError):
            parse_course_ids("12,course")

    def test_parse_reminder_hours(self):
        self.assertEqual(parse_reminder_hours("1,24,1"), [24.0, 1.0])

    def test_parse_reminder_hours_rejects_non_positive_values(self):
        with self.assertRaises(ValueError):
            parse_reminder_hours("24,0")

    def test_parse_reminder_hours_rejects_non_finite_values(self):
        with self.assertRaises(ValueError):
            parse_reminder_hours("24,nan")

    def test_parse_canvas_datetime_normalizes_to_utc(self):
        self.assertEqual(
            parse_canvas_datetime("2026-11-10T12:00:00+02:00"),
            datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc),
        )

    def test_parse_canvas_datetime_skips_invalid_value(self):
        self.assertIsNone(parse_canvas_datetime("not-a-date"))

    def test_canvas_client_requires_https(self):
        with self.assertRaises(ValueError):
            CanvasClient("http://canvas.example", None)

    def test_canvas_client_rejects_cross_origin_pagination(self):
        client = CanvasClient("https://canvas.example", None)
        with self.assertRaises(ValueError):
            client._next_link(
                '<https://other.example/api/v1/courses?page=2>; rel="next"'
            )


class BotStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_posts_active_notice_only_once(self):
        bot = NotifierBot.__new__(NotifierBot)
        bot.active_notice_sent = False
        bot._send = AsyncMock()

        await bot.on_ready()
        await bot.on_ready()

        bot._send.assert_awaited_once_with(
            "Canvas notifier is online and monitoring this channel."
        )

    async def test_failed_active_notice_can_retry(self):
        bot = NotifierBot.__new__(NotifierBot)
        bot.active_notice_sent = False
        bot._send = AsyncMock(side_effect=RuntimeError("Discord unavailable"))

        with self.assertRaisesRegex(RuntimeError, "Discord unavailable"):
            await bot.on_ready()

        self.assertFalse(bot.active_notice_sent)


if __name__ == "__main__":
    unittest.main()
