CREATE TABLE sent_reminders (
    assignment_id TEXT NOT NULL,
    due_at TEXT NOT NULL,
    reminder_hours DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (assignment_id, due_at, reminder_hours)
);
