"""One-time migration of SpeakEd data from the legacy SQLite database into PostgreSQL.

REVIEW THIS BEFORE RUNNING. It does nothing unless you pass --commit.

What it does
------------
Copies users, attempts, transcripts, prompt_usage, markings, feedback,
self_evaluations and gathered_info from a SQLite file into a PostgreSQL
database, preserving primary keys so every foreign-key relationship stays
intact. Existing password hashes are copied verbatim, so students keep the
password they already use.

Safety properties
-----------------
* The SQLite file is opened READ-ONLY and is never modified or deleted.
* Nothing is written unless --commit is passed; the default is a dry run.
* Rows whose id already exists in PostgreSQL are skipped, so re-running is safe
  and an account created directly on PostgreSQL is never overwritten.
* Password hashes are never printed. No password is ever known to this script.
* Identity sequences are resynchronised at the end so new signups do not
  collide with migrated ids.
* Runs in a single transaction: any error rolls the whole migration back.

Usage
-----
    # dry run, shows exactly what would be copied
    python scripts/migrate_sqlite_to_postgres.py --sqlite instance/speaked.db

    # perform the migration
    python scripts/migrate_sqlite_to_postgres.py --sqlite instance/speaked.db --commit

DATABASE_URL (or --postgres) must point at the target PostgreSQL database.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import normalize_postgres_dsn  # noqa: E402

# Parent tables first so foreign keys always resolve.
TABLE_ORDER = [
    "users",
    "password_resets",
    "attempts",
    "transcripts",
    "prompt_usage",
    "markings",
    "feedback",
    "self_evaluations",
    "gathered_info",
    "subscriptions",
    "webhook_events",
    "usage_counters",
]

# Columns that must never be echoed to the console.
SECRET_COLUMNS = {"password_hash", "token_hash"}


def _sqlite_columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _postgres_columns(cursor, table: str) -> list[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return [row[0] for row in cursor.fetchall()]


def _existing_ids(cursor, table: str) -> set:
    cursor.execute(f'SELECT id FROM "{table}"')
    return {row[0] for row in cursor.fetchall()}


def migrate(sqlite_path: Path, pg_dsn: str, commit: bool) -> int:
    if not sqlite_path.exists():
        print(f"SQLite file not found: {sqlite_path}")
        return 1

    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed. Run: pip install psycopg2-binary")
        return 1

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = psycopg2.connect(normalize_postgres_dsn(pg_dsn))

    copied: dict[str, int] = {}
    skipped: dict[str, int] = {}

    try:
        cursor = target.cursor()
        source_tables = {
            row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

        for table in TABLE_ORDER:
            copied[table] = 0
            skipped[table] = 0
            if table not in source_tables:
                print(f"{table}: not present in the SQLite database, skipping")
                continue

            src_cols = _sqlite_columns(source, table)
            dst_cols = _postgres_columns(cursor, table)
            if not dst_cols:
                print(f"{table}: does not exist in PostgreSQL, skipping")
                continue

            shared = [c for c in src_cols if c in dst_cols]
            dropped = [c for c in src_cols if c not in dst_cols]
            if dropped:
                print(f"{table}: columns not present in PostgreSQL and therefore not copied: {dropped}")

            present = _existing_ids(cursor, table) if "id" in dst_cols else set()
            placeholders = ", ".join(["%s"] * len(shared))
            column_list = ", ".join(f'"{c}"' for c in shared)
            insert_sql = f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})'

            for row in source.execute(f"SELECT * FROM {table}"):
                record = dict(row)
                if "id" in record and record["id"] in present:
                    skipped[table] += 1
                    continue
                cursor.execute(insert_sql, tuple(record[c] for c in shared))
                copied[table] += 1

            print(f"{table}: {copied[table]} row(s) to copy, {skipped[table]} already present")

        # Keep identity sequences ahead of the migrated ids.
        for table in TABLE_ORDER:
            if table not in source_tables:
                continue
            if "id" not in _postgres_columns(cursor, table):
                continue
            cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), "
                f'GREATEST((SELECT COALESCE(MAX(id), 1) FROM "{table}"), 1), true)'
            )

        if commit:
            target.commit()
            print("\nCOMMITTED. Verify by logging in with an existing account.")
        else:
            target.rollback()
            print("\nDRY RUN — nothing was written. Re-run with --commit to apply.")
    except Exception as exc:
        target.rollback()
        print(f"\nMigration FAILED and was rolled back: {exc}")
        return 1
    finally:
        source.close()
        target.close()

    total = sum(copied.values())
    print(f"Total rows {'copied' if commit else 'that would be copied'}: {total}")
    print(f"The SQLite file at {sqlite_path} was opened read-only and is unchanged.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default="instance/speaked.db", help="path to the legacy SQLite file")
    parser.add_argument("--postgres", default="", help="target DSN (defaults to $DATABASE_URL)")
    parser.add_argument("--commit", action="store_true", help="actually write the rows")
    args = parser.parse_args()

    dsn = args.postgres.strip() or os.environ.get("DATABASE_URL", "").strip()
    if not dsn.startswith(("postgres://", "postgresql://")):
        print("A PostgreSQL DSN is required via --postgres or DATABASE_URL.")
        return 1

    return migrate(Path(args.sqlite).resolve(), dsn, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
