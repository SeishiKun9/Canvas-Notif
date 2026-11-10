import unittest
from datetime import datetime

from daily_reset import parse_reset_timezone, reset_notification_state_if_new_day


class FakeCursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeConnection:
    def __init__(self, reset_date):
        self.reset_date = reset_date
        self.statements = []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, query, parameters=None):
        self.statements.append((query, parameters))
        if query.startswith("SELECT value FROM metadata"):
            return FakeCursor((self.reset_date,) if self.reset_date else None)
        return FakeCursor(None)


class FakePool:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def connection(self):
        return self


class DailyResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_resets_notification_tables_once_for_new_local_date(self):
        connection = FakeConnection("2026-11-09")
        pool = FakePool(connection)

        reset = await reset_notification_state_if_new_day(
            pool,
            parse_reset_timezone("Asia/Manila"),
            datetime.fromisoformat("2026-11-10T00:01:00+08:00"),
        )

        self.assertTrue(reset)
        queries = [query for query, _ in connection.statements]
        self.assertIn("DELETE FROM seen", queries)
        self.assertIn("DELETE FROM sent_reminders", queries)
        self.assertIn("DELETE FROM metadata WHERE key LIKE 'baseline:%'", queries)
        self.assertFalse(any("schema_migrations" in query for query in queries))
        reset_marker = next(
            parameters
            for query, parameters in connection.statements
            if query.startswith("INSERT INTO metadata")
        )
        self.assertEqual(reset_marker, ("daily_reset_date", "2026-11-10"))

    async def test_does_not_reset_twice_on_same_local_date(self):
        connection = FakeConnection("2026-11-10")
        pool = FakePool(connection)

        reset = await reset_notification_state_if_new_day(
            pool,
            parse_reset_timezone("Asia/Manila"),
            datetime.fromisoformat("2026-11-10T23:59:00+08:00"),
        )

        self.assertFalse(reset)
        self.assertFalse(
            any(query.startswith("DELETE") for query, _ in connection.statements)
        )

    def test_rejects_unknown_timezone(self):
        with self.assertRaises(ValueError):
            parse_reset_timezone("Asia/NotARealCity")


if __name__ == "__main__":
    unittest.main()
