import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger("canvas_notifier.daily_reset")
RESET_LOCK_ID = 687316279402
RESET_DATE_KEY = "daily_reset_date"


def parse_reset_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"DAILY_RESET_TIMEZONE must be a valid IANA timezone: {timezone_name}"
        ) from exc


async def reset_notification_state_if_new_day(
    pool: AsyncConnectionPool,
    reset_timezone: ZoneInfo,
    now: datetime | None = None,
) -> bool:
    reset_date = (now or datetime.now(reset_timezone)).astimezone(reset_timezone)
    reset_date_text = reset_date.date().isoformat()

    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(%s)", (RESET_LOCK_ID,)
            )
            cursor = await connection.execute(
                "SELECT value FROM metadata WHERE key = %s FOR UPDATE",
                (RESET_DATE_KEY,),
            )
            row = await cursor.fetchone()
            if row is not None and row[0] == reset_date_text:
                return False

            await connection.execute("DELETE FROM seen")
            await connection.execute("DELETE FROM sent_reminders")
            await connection.execute(
                "DELETE FROM metadata WHERE key LIKE 'baseline:%'"
            )
            await connection.execute(
                "INSERT INTO metadata (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (RESET_DATE_KEY, reset_date_text),
            )

    logger.info(
        "Cleared notification state for %s; migration history and Discord messages were kept",
        reset_date_text,
    )
    return True
