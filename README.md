# Canvas Discord Notifier

A lightweight Discord bot that checks Canvas LMS for new course announcements,
new assignments, and upcoming assignment due dates.

## Requirements

- Python 3.10 or newer
- PostgreSQL 14 or newer
- A Discord application with a bot user
- A Canvas access token with permission to read your courses, announcements, and assignments

## Setup

1. Create a Discord application and add a bot user in the Discord Developer Portal.
   Invite it to your server with permission to view the target channel and send messages.
   Copy the bot token and the target channel ID.
2. Create a Canvas access token in your Canvas account's approved integrations/profile
   settings. Keep the token private.
3. Create a PostgreSQL database and copy `.env.example` to `.env`. Set
   `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `CANVAS_BASE_URL`,
   `CANVAS_API_TOKEN`, and `DATABASE_URL` to your PostgreSQL connection URL.
   `CANVAS_BASE_URL` is your school's Canvas site, such as
   `https://school.instructure.com`.
4. Optionally set `CANVAS_COURSE_IDS` to a comma-separated list of course IDs.
   When empty, the bot watches all active courses the Canvas account can access.
5. Install and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   py -m pip install -r requirements.txt
   py bot.py
   ```

The first successful poll records existing announcements and assignments without
posting them, avoiding a history dump. New items are posted on later polls.
Assignments receive reminders at the thresholds in `DUE_REMINDER_HOURS` (default:
24 and 1 hour before due time). A reminder missed during downtime is sent at the
next poll; if multiple thresholds were missed, only the closest threshold is sent.
The bot runs pending versioned SQL migrations at startup and stores seen items
and sent reminders in PostgreSQL.

Keep `.env` private. If either token is exposed, revoke it in the corresponding
service and create a replacement.

## Deploy on Railway

Use Railway's managed PostgreSQL service for persistent bot state:

1. Create a Railway project from this GitHub repository. The included
   `Dockerfile` runs the bot as a worker.
2. Add a PostgreSQL service to the Railway project.
3. In the bot service's **Variables**, add a reference to the database service's
   connection URL as `DATABASE_URL` (for example,
   `${{Postgres.DATABASE_URL}}`, using the actual PostgreSQL service name).
   Add `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `CANVAS_BASE_URL`, and
   `CANVAS_API_TOKEN` as service variables. Enter secrets directly in Railway;
   do not commit `.env` or paste tokens into chat.
4. Deploy the bot service. It applies pending migrations at startup; check the
   service logs for migration and Discord login messages.

Do not run multiple bot replicas unless you also add distributed polling locks
and delivery coordination. PostgreSQL supports multiple clients, but this bot's
polling loop is designed to run once.

The database schema is versioned under `migrations/sql/`. Add a new, higher
numbered SQL file for future schema changes; applied migrations are recorded in
`schema_migrations` and run transactionally at startup. Existing SQLite state is
not imported automatically; the new PostgreSQL database starts with empty state.

## Add the bot to a Discord server

In the Discord Developer Portal, open the application and go to **Installation**
or **OAuth2 > URL Generator**. Select the `bot` scope and grant only the needed
permissions, including **View Channel** and **Send Messages**. Open the generated
install link, choose your server, and authorize it. You need permission to manage
that server. This authorization is separate from deploying the bot.
