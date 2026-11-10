import asyncio
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import aiohttp
import discord
from dotenv import load_dotenv
from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from migrations import run_migrations

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("canvas_notifier")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set in the environment or .env file")
    return value


def parse_course_ids(value: str) -> set[str]:
    course_ids = {course_id.strip() for course_id in value.split(",") if course_id.strip()}
    if any(not course_id.isdecimal() for course_id in course_ids):
        raise ValueError("CANVAS_COURSE_IDS must contain comma-separated numeric IDs")
    return course_ids


def parse_reminder_hours(value: str) -> list[float]:
    try:
        hours = sorted({float(item.strip()) for item in value.split(",")}, reverse=True)
    except ValueError as exc:
        raise ValueError("DUE_REMINDER_HOURS must be comma-separated numbers") from exc
    if not hours or any(not math.isfinite(hour) or hour <= 0 for hour in hours):
        raise ValueError("DUE_REMINDER_HOURS must contain positive numbers")
    return hours


def parse_canvas_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Skipping invalid Canvas date: %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class CanvasClient:
    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        parsed_base = urlparse(base_url)
        if parsed_base.scheme != "https" or not parsed_base.netloc:
            raise ValueError("CANVAS_BASE_URL must be an HTTPS URL")
        self.api_root = f"{base_url.rstrip('/')}/api/v1"
        self.origin = urlparse(self.api_root)
        self.session = session

    async def get_pages(
        self, url: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        while url:
            async with self.session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                next_url = self._next_link(response.headers.get("Link", ""))
            if not isinstance(data, list):
                raise ValueError(f"Canvas returned an unexpected response for {url}")
            for item in data:
                yield item
            url = next_url
            params = None

    def _next_link(self, header: str) -> str:
        for link in header.split(","):
            target, *attributes = link.split(";")
            if any(attribute.strip() == 'rel="next"' for attribute in attributes):
                url = target.strip().strip("<>")
                parsed = urlparse(url)
                if (parsed.scheme, parsed.netloc) != (
                    self.origin.scheme,
                    self.origin.netloc,
                ):
                    raise ValueError("Canvas pagination link changed origin")
                return url
        return ""

    async def courses(self) -> list[dict[str, Any]]:
        return [
            item
            async for item in self.get_pages(
                f"{self.api_root}/courses",
                {"enrollment_state": "active", "per_page": 100},
            )
        ]

    async def announcements(self, course_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self.get_pages(
                f"{self.api_root}/announcements",
                {
                    "context_codes[]": f"course_{course_id}",
                    "per_page": 100,
                },
            )
        ]

    async def assignments(self, course_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self.get_pages(
                f"{self.api_root}/courses/{course_id}/assignments",
                {"per_page": 100},
            )
        ]


class NotifierBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.channel_id = int(required_env("DISCORD_CHANNEL_ID"))
        if self.channel_id <= 0:
            raise ValueError("DISCORD_CHANNEL_ID must be a positive numeric ID")
        self.canvas_base_url = required_env("CANVAS_BASE_URL").rstrip("/")
        self.canvas_token = required_env("CANVAS_API_TOKEN")
        self.database_url = required_env("DATABASE_URL")
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
        if self.poll_interval < 30:
            raise ValueError("POLL_INTERVAL_SECONDS must be at least 30")
        self.course_ids = parse_course_ids(os.getenv("CANVAS_COURSE_IDS", ""))
        self.reminder_hours = parse_reminder_hours(
            os.getenv("DUE_REMINDER_HOURS", "24,1")
        )
        self.db: AsyncConnectionPool | None = None
        self.http: aiohttp.ClientSession | None = None
        self.poller: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        self.db = AsyncConnectionPool(
            conninfo=self.database_url,
            min_size=1,
            max_size=2,
            open=False,
            kwargs={"row_factory": tuple_row},
        )
        await self.db.open()
        await run_migrations(self.db)
        self.http = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.canvas_token}"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        self.poller = asyncio.create_task(self._poll_forever())

    async def close(self) -> None:
        if self.poller:
            self.poller.cancel()
            try:
                await self.poller
            except asyncio.CancelledError:
                pass
        if self.http:
            await self.http.close()
        if self.db:
            await self.db.close()
        await super().close()

    def _database(self) -> AsyncConnectionPool:
        if self.db is None:
            raise RuntimeError("Notifier database is not initialized")
        return self.db

    async def _has_seen(self, kind: str, item_id: str) -> bool:
        async with self._database().connection() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM seen WHERE kind = %s AND item_id = %s",
                (kind, item_id),
            )
            return await cursor.fetchone() is not None

    async def _mark_seen(self, kind: str, item_id: str) -> None:
        async with self._database().connection() as connection:
            await connection.execute(
                "INSERT INTO seen (kind, item_id) VALUES (%s, %s) "
                "ON CONFLICT (kind, item_id) DO NOTHING",
                (kind, item_id),
            )

    async def _is_baselined(self, kind: str) -> bool:
        async with self._database().connection() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM metadata WHERE key = %s", (f"baseline:{kind}",)
            )
            return await cursor.fetchone() is not None

    async def _set_baseline(self, kind: str) -> None:
        async with self._database().connection() as connection:
            await connection.execute(
                "INSERT INTO metadata (key, value) VALUES (%s, 'done') "
                "ON CONFLICT (key) DO NOTHING",
                (f"baseline:{kind}",),
            )

    async def _reminder_sent(
        self, assignment_id: str, due_at: str, hours: float
    ) -> bool:
        async with self._database().connection() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM sent_reminders "
                "WHERE assignment_id = %s AND due_at = %s AND reminder_hours = %s",
                (assignment_id, due_at, hours),
            )
            return await cursor.fetchone() is not None

    async def _mark_reminder_sent(
        self, assignment_id: str, due_at: str, hours: float
    ) -> None:
        async with self._database().connection() as connection:
            await connection.execute(
                "INSERT INTO sent_reminders "
                "(assignment_id, due_at, reminder_hours) VALUES (%s, %s, %s) "
                "ON CONFLICT (assignment_id, due_at, reminder_hours) DO NOTHING",
                (assignment_id, due_at, hours),
            )

    async def _get_channel(self) -> discord.abc.Messageable:
        channel = self.get_channel(self.channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.channel_id)
        if not hasattr(channel, "send"):
            raise TypeError(f"Discord channel {self.channel_id} cannot receive messages")
        return channel

    async def _send(self, message: str, url: str | None = None) -> None:
        channel = await self._get_channel()
        if url:
            message = f"{message}\n{url}"
        await channel.send(
            message[:2000],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _poll_forever(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Canvas polling failed; will retry")
            await asyncio.sleep(self.poll_interval)

    async def poll_once(self) -> None:
        if self.http is None:
            raise RuntimeError("Canvas HTTP session is not initialized")
        client = CanvasClient(self.canvas_base_url, self.http)
        courses = await client.courses()
        if self.course_ids:
            courses = [
                course for course in courses if str(course.get("id")) in self.course_ids
            ]

        announcement_items: list[tuple[dict[str, Any], str]] = []
        assignment_items: list[tuple[dict[str, Any], str]] = []
        for course in courses:
            course_id = str(course["id"])
            course_name = str(course.get("name") or f"Course {course_id}")
            announcements, assignments = await asyncio.gather(
                client.announcements(course_id),
                client.assignments(course_id),
            )
            announcement_items.extend((item, course_name) for item in announcements)
            assignment_items.extend((item, course_name) for item in assignments)

        await self._process_new_items("announcement", announcement_items)
        await self._process_new_items("assignment", assignment_items)
        await self._process_due_reminders(assignment_items)

    async def _process_new_items(
        self, kind: str, items: list[tuple[dict[str, Any], str]]
    ) -> None:
        baselined = await self._is_baselined(kind)
        for item, course_name in items:
            item_id = str(item.get("id", ""))
            if not item_id or await self._has_seen(kind, item_id):
                continue
            if baselined:
                title = str(item.get("title") or f"New {kind}")
                await self._send(
                    f"**Canvas {kind.title()}: {course_name}**\n{title}",
                    item.get("html_url"),
                )
            await self._mark_seen(kind, item_id)
        if not baselined:
            await self._set_baseline(kind)
            logger.info("Recorded existing %ss without posting a history dump", kind)

    async def _process_due_reminders(
        self, items: list[tuple[dict[str, Any], str]]
    ) -> None:
        now = datetime.now(timezone.utc)
        for assignment, course_name in items:
            due_at_raw = assignment.get("due_at")
            due_at = parse_canvas_datetime(due_at_raw)
            assignment_id = str(assignment.get("id", ""))
            if due_at is None or not assignment_id or due_at <= now:
                continue

            hours_left = (due_at - now).total_seconds() / 3600
            eligible = [
                hours
                for hours in self.reminder_hours
                if hours_left <= hours
                and not await self._reminder_sent(
                    assignment_id, str(due_at_raw), hours
                )
            ]
            if not eligible:
                continue
            # If a poll was delayed across multiple thresholds, send only the nearest one.
            reminder_hours = min(eligible)
            title = str(assignment.get("name") or "Assignment")
            due_text = due_at.strftime("%Y-%m-%d %H:%M UTC")
            await self._send(
                f"**Canvas due date: {course_name}**\n"
                f"{title} is due in about {hours_left:.1f} hours "
                f"(due {due_text}).",
                assignment.get("html_url"),
            )
            await self._mark_reminder_sent(
                assignment_id, str(due_at_raw), reminder_hours
            )


def main() -> None:
    token = required_env("DISCORD_BOT_TOKEN")
    NotifierBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
