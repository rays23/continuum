import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from continuum.schedule import backoff_delay, parse_reset_time

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=BERLIN)


class ParseResetTimeTest(unittest.TestCase):
    def test_parses_hour_with_meridiem(self):
        now = berlin(2026, 8, 14, 16, 15)
        self.assertEqual(parse_reset_time("7pm (Europe/Berlin)", now), berlin(2026, 8, 14, 19))

    def test_parses_hour_and_minutes(self):
        now = berlin(2026, 8, 14, 16, 15)
        self.assertEqual(
            parse_reset_time("6:50pm (Europe/Berlin)", now), berlin(2026, 8, 14, 18, 50)
        )

    def test_midnight_rolls_into_the_next_day(self):
        """12am ist Mitternacht, und die liegt nach 20:32 im Morgen danach."""
        now = berlin(2026, 8, 14, 20, 32)
        self.assertEqual(parse_reset_time("12am (Europe/Berlin)", now), berlin(2026, 8, 15, 0))

    def test_noon_is_not_midnight(self):
        now = berlin(2026, 8, 14, 9, 0)
        self.assertEqual(parse_reset_time("12pm (Europe/Berlin)", now), berlin(2026, 8, 14, 12))

    def test_time_already_passed_moves_to_tomorrow(self):
        now = berlin(2026, 8, 14, 23, 0)
        self.assertEqual(parse_reset_time("9am (Europe/Berlin)", now), berlin(2026, 8, 15, 9))

    def test_uses_the_timezone_from_the_hint(self):
        now = datetime(2026, 8, 14, 16, 0, tzinfo=ZoneInfo("UTC"))
        parsed = parse_reset_time("7pm (Europe/Berlin)", now)
        self.assertEqual(parsed, berlin(2026, 8, 14, 19))

    def test_twenty_four_hour_format(self):
        now = berlin(2026, 8, 14, 16, 15)
        self.assertEqual(parse_reset_time("19:00 (Europe/Berlin)", now), berlin(2026, 8, 14, 19))

    def test_unknown_wording_returns_none(self):
        """Die 7-Tage-Limits nennen vermutlich einen Wochentag."""
        now = berlin(2026, 8, 14, 16, 15)
        self.assertIsNone(parse_reset_time("Monday", now))
        self.assertIsNone(parse_reset_time("", now))
        self.assertIsNone(parse_reset_time(None, now))

    def test_unknown_timezone_falls_back_without_crashing(self):
        now = berlin(2026, 8, 14, 16, 15)
        parsed = parse_reset_time("7pm (Mars/Olympus)", now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 19)

    def test_impossible_hour_returns_none(self):
        now = berlin(2026, 8, 14, 16, 15)
        self.assertIsNone(parse_reset_time("25:00", now))


class BackoffTest(unittest.TestCase):
    def test_grows_and_then_stops_growing(self):
        delays = [backoff_delay(n) for n in range(1, 7)]
        self.assertEqual(
            delays,
            [
                timedelta(minutes=10),
                timedelta(minutes=20),
                timedelta(minutes=40),
                timedelta(minutes=80),
                timedelta(minutes=120),
                timedelta(minutes=120),
            ],
        )

    def test_first_attempt_is_never_shorter_than_one_tick(self):
        self.assertGreaterEqual(backoff_delay(0), timedelta(minutes=10))


if __name__ == "__main__":
    unittest.main()
