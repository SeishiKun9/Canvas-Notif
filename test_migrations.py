import unittest

from migrations import load_migrations


class MigrationTests(unittest.TestCase):
    def test_migrations_are_ordered_and_unique(self):
        migrations = load_migrations()
        versions = [version for version, _ in migrations]

        self.assertEqual(versions, sorted(versions))
        self.assertEqual(len(versions), len(set(versions)))
        self.assertGreaterEqual(len(migrations), 1)

    def test_migration_sql_uses_postgresql_schema(self):
        sql = "\n".join(
            path.read_text(encoding="utf-8") for _, path in load_migrations()
        ).upper()

        self.assertIn("CREATE TABLE SEEN", sql)
        self.assertIn("CREATE TABLE SENT_REMINDERS", sql)
        self.assertIn("CREATE TABLE METADATA", sql)
        self.assertIn("DOUBLE PRECISION", sql)
        self.assertNotIn("INSERT OR IGNORE", sql)


if __name__ == "__main__":
    unittest.main()
