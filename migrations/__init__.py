import logging
import re
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger("canvas_notifier.migrations")
MIGRATION_DIR = Path(__file__).parent / "sql"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
MIGRATION_LOCK_ID = 687316279401


def load_migrations() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    seen_versions: set[int] = set()
    for path in MIGRATION_DIR.glob("*.sql"):
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid migration filename: {path.name}")
        version = int(match.group(1))
        if version in seen_versions:
            raise ValueError(f"Duplicate migration version: {version}")
        if not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"Migration is empty: {path.name}")
        seen_versions.add(version)
        migrations.append((version, path))
    if not migrations:
        raise ValueError(f"No database migrations found in {MIGRATION_DIR}")
    return sorted(migrations)


async def run_migrations(pool: AsyncConnectionPool) -> None:
    migrations = load_migrations()
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,)
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "filename TEXT NOT NULL, "
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                ")"
            )
            cursor = await connection.execute(
                "SELECT version, filename FROM schema_migrations ORDER BY version"
            )
            applied = dict(await cursor.fetchall())
            known = {version: path for version, path in migrations}
            unknown_versions = set(applied) - set(known)
            if unknown_versions:
                raise RuntimeError(
                    "Database contains migrations unknown to this bot version: "
                    + ", ".join(str(version) for version in sorted(unknown_versions))
                )

            for version, path in migrations:
                if version in applied:
                    if applied[version] != path.name:
                        raise RuntimeError(
                            f"Migration {version} was recorded as "
                            f"{applied[version]}, not {path.name}"
                        )
                    continue
                if any(applied_version > version for applied_version in applied):
                    raise RuntimeError(
                        f"Cannot apply migration {path.name}: a later version "
                        "is already recorded"
                    )

                await connection.execute(path.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO schema_migrations (version, filename) "
                    "VALUES (%s, %s)",
                    (version, path.name),
                )
    for version, path in migrations:
        if version not in applied:
            logger.info("Applied database migration %s", path.name)
