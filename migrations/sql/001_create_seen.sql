CREATE TABLE seen (
    kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (kind, item_id)
);
