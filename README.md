# Canvas Discord Notifier

A lightweight Discord bot that checks Canvas LMS for new course announcements,
new assignments, and upcoming assignment due dates.

## Requirements

- Python 3.10 or newer
- PostgreSQL 14 or newer
- A Discord application with a bot user
- A Canvas access token with permission to read your courses, announcements, and assignments

## Setup on Windows

1. Create a Discord application and add a bot user in the Discord Developer
   Portal. Invite it to your server with permission to view the target channel
   and send messages. Copy the bot token and target channel ID.
2. Create a Canvas access token in your Canvas account's approved integrations
   or profile settings. Keep the token private.
3. Ensure the local PostgreSQL Windows service is running and create a database
   named `canvas_notifier`.
4. Copy `.env.example` to `.env`. Set `DISCORD_BOT_TOKEN`,
   `DISCORD_CHANNEL_ID`, `CANVAS_BASE_URL`, `CANVAS_API_TOKEN`, and
   `DATABASE_URL` to your PostgreSQL connection URL. For example:

   ```text
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/canvas_notifier
   ```

   `CANVAS_BASE_URL` is your school's Canvas site, such as
   `https://school.instructure.com`. Keep `.env` private.
5. Optionally set `CANVAS_COURSE_IDS` to a comma-separated list of course IDs.
   When empty, the bot watches all active courses the Canvas account can access.
6. Install dependencies from PowerShell in the project folder:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   py -m pip install -r requirements.txt
   ```

Start and stop the bot from PowerShell in the project folder:

```powershell
.\Start-Bot.ps1
.\Stop-Bot.ps1
```

The start script runs the bot in the background, and the stop script only stops
the verified bot process. Output is written to `logs\bot.log` and
`logs\bot-error.log`; the PID file and logs are ignored by Git. The laptop must
remain on, awake, and connected to the internet to poll Canvas and post
notifications. After a Windows restart, run `.\Start-Bot.ps1` again.
When the bot connects, it posts a one-time active message in the configured
Discord channel. Reconnecting to Discord does not post another active message
for the same bot process.

The bot runs pending versioned SQL migrations at startup. The first successful
poll records existing announcements and assignments without posting a history
dump. New items are posted on later polls. Assignments receive reminders at the
thresholds in `DUE_REMINDER_HOURS` (default: 24 and 1 hour before due time).

## Daily database cleanup

At the first poll after each midnight in `DAILY_RESET_TIMEZONE` (default:
`Asia/Manila`), the bot clears the `seen`, `sent_reminders`, and baseline
notification state. This keeps runtime state from accumulating. It retains the
database tables and migration history, and does not delete or alter messages
already posted in Discord. If the laptop is asleep or the bot is stopped at
midnight, the reset runs on the next poll after it resumes.

## Database migrations

The database schema is versioned under `migrations/sql/`. Add a new, higher
numbered SQL file for future schema changes. Applied migrations are recorded in
`schema_migrations` and run transactionally at startup. Existing SQLite state
is not imported automatically; the PostgreSQL database starts with empty state.

## Add the bot to a Discord server

In the Discord Developer Portal, open the application and go to **Installation**
or **OAuth2 > URL Generator**. Select the `bot` scope and grant only the needed
permissions, including **View Channel** and **Send Messages**. Open the
generated install link, choose your server, and authorize it. You need permission
to manage that server.

Keep `.env` private. If a token is exposed, revoke it in the corresponding
service and create a replacement.
