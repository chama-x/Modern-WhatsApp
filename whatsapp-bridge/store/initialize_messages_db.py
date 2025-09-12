#!/usr/bin/env python3
"""
initialize_messages_db.py

Creates (or upgrades) a local SQLite database used by the WhatsApp MCP server
for reading chats and messages. The schema matches what whatsapp.py expects.

Tables:
  chats(
      jid TEXT PRIMARY KEY,
      name TEXT,
      last_message_time TEXT   -- ISO 8601 timestamp string (UTC or local)
  )

  messages(
      id TEXT PRIMARY KEY,     -- Unique message identifier
      timestamp TEXT NOT NULL, -- ISO 8601 timestamp string
      sender TEXT NOT NULL,    -- Contact JID or phone number
      content TEXT,            -- Message body (may be NULL for pure media)
      is_from_me INTEGER NOT NULL DEFAULT 0,  -- 1 if authored by local user
      chat_jid TEXT NOT NULL,  -- FK to chats.jid
      media_type TEXT,         -- e.g. image, audio, video, document, sticker, etc.
      FOREIGN KEY(chat_jid) REFERENCES chats(jid) ON DELETE CASCADE
  )

Indexes:
  idx_messages_chat_time (chat_jid, timestamp)
  idx_messages_sender (sender)

Trigger:
  trg_messages_update_chat_last_time
    On INSERT: update chats.last_message_time if the new message is newer.

Usage:
  python initialize_messages_db.py                # Create/upgrade schema only
  python initialize_messages_db.py --seed         # Also insert small demo dataset
  python initialize_messages_db.py --reset        # Drop existing tables then recreate
  python initialize_messages_db.py --reset --seed # Recreate + demo data

The database file is created alongside this script at: ./messages.db
"""

from __future__ import annotations
import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Tuple

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "messages.db")


SCHEMA_STATEMENTS = [
    # Enable foreign keys
    "PRAGMA foreign_keys = ON;",
    # Chats table
    """
    CREATE TABLE IF NOT EXISTS chats (
        jid TEXT PRIMARY KEY,
        name TEXT,
        last_message_time TEXT
    );
    """,
    # Messages table
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        sender TEXT NOT NULL,
        content TEXT,
        is_from_me INTEGER NOT NULL DEFAULT 0,
        chat_jid TEXT NOT NULL,
        media_type TEXT,
        FOREIGN KEY(chat_jid) REFERENCES chats(jid) ON DELETE CASCADE
    );
    """,
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_jid, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);",
    # Trigger to keep last_message_time in sync
    """
    CREATE TRIGGER IF NOT EXISTS trg_messages_update_chat_last_time
    AFTER INSERT ON messages
    BEGIN
        UPDATE chats
        SET last_message_time = NEW.timestamp
        WHERE jid = NEW.chat_jid
          AND (
            last_message_time IS NULL OR
            last_message_time < NEW.timestamp
          );
    END;
    """,
]


def execute_batch(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    cur = conn.cursor()
    for stmt in statements:
        trimmed = stmt.strip()
        if not trimmed:
            continue
        cur.execute(trimmed)
    conn.commit()


def drop_existing(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF;")
    cur.execute("DROP TABLE IF EXISTS messages;")
    cur.execute("DROP TABLE IF EXISTS chats;")
    cur.execute("PRAGMA foreign_keys = ON;")
    conn.commit()


def seed_demo_data(conn: sqlite3.Connection) -> None:
    """
    Insert a minimal set of chats + messages for quick UI testing.
    """
    now = datetime.now(timezone.utc)
    chats = [
        ("123456789@s.whatsapp.net", "Alice", (now - timedelta(minutes=2)).isoformat()),
        ("987654321@s.whatsapp.net", "Bob", (now - timedelta(minutes=5)).isoformat()),
        ("family-group@g.us", "Family Group", (now - timedelta(minutes=1)).isoformat()),
    ]

    messages: Iterable[Tuple[str, str, str, str, int, str, str | None]] = [
        # id, timestamp, sender, content, is_from_me, chat_jid, media_type
        ("m1", (now - timedelta(minutes=10)).isoformat(), "123456789@s.whatsapp.net", "Hey are we still on for lunch?", 0, "123456789@s.whatsapp.net", None),
        ("m2", (now - timedelta(minutes=9, seconds=30)).isoformat(), "me@s.whatsapp.net", "Yes, 12:30 works.", 1, "123456789@s.whatsapp.net", None),
        ("m3", (now - timedelta(minutes=8)).isoformat(), "987654321@s.whatsapp.net", "Reminder: meeting at 3 PM.", 0, "987654321@s.whatsapp.net", None),
        ("m4", (now - timedelta(minutes=6, seconds=10)).isoformat(), "me@s.whatsapp.net", "Got it, thanks!", 1, "987654321@s.whatsapp.net", None),
        ("m5", (now - timedelta(minutes=3)).isoformat(), "me@s.whatsapp.net", "Family, dinner at 7?", 1, "family-group@g.us", None),
        ("m6", (now - timedelta(minutes=2, seconds=30)).isoformat(), "123456789@s.whatsapp.net", "Sounds good!", 0, "family-group@g.us", None),
        ("m7", (now - timedelta(minutes=1)).isoformat(), "987654321@s.whatsapp.net", "I'll bring dessert.", 0, "family-group@g.us", None),
    ]

    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO chats(jid, name, last_message_time) VALUES (?, ?, ?)",
        chats,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO messages(id, timestamp, sender, content, is_from_me, chat_jid, media_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        messages,
    )
    conn.commit()

    # Re-sync last_message_time explicitly (in case inserts earlier than current stored time)
    cur.execute(
        """
        UPDATE chats
        SET last_message_time = (
            SELECT MAX(timestamp) FROM messages WHERE messages.chat_jid = chats.jid
        )
        """
    )
    conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize WhatsApp MCP messages SQLite database.")
    parser.add_argument("--seed", action="store_true", help="Insert demo chats/messages for testing.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate schema.")
    parser.add_argument("--db-path", default=DB_PATH, help=f"Custom path for DB file (default: {DB_PATH})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = os.path.abspath(args.db_path)

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    creating_new = not os.path.exists(db_path) or args.reset

    with sqlite3.connect(db_path) as conn:
        if args.reset:
            print("[init] Reset requested: dropping existing schema.")
            drop_existing(conn)

        print(f"[init] Applying schema to {db_path}")
        execute_batch(conn, SCHEMA_STATEMENTS)

        if args.seed:
            print("[init] Seeding demo data...")
            seed_demo_data(conn)

    if creating_new:
        print("[init] Database created / initialized successfully.")
    else:
        print("[init] Schema ensured successfully (no destructive changes).")

    if args.seed:
        print("[init] Demo data inserted. You can now run the API server and view chats/messages.")


if __name__ == "__main__":
    main()
