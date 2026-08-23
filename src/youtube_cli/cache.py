from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from youtube_cli.youtube import Playlist

PLAYLISTS_COLLECTION = "playlists"


@dataclass(frozen=True)
class CachedPlaylists:
    playlists: tuple[Playlist, ...]
    fetched_at: str
    truncated: bool


class LibraryCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.db_path = cache_dir / "library.sqlite"
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.chmod(0o700)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def load_playlists(self) -> CachedPlaylists | None:
        conn = self._require_conn()
        meta = conn.execute(
            "SELECT fetched_at, truncated FROM collection_meta WHERE name = ?",
            (PLAYLISTS_COLLECTION,),
        ).fetchone()
        if meta is None:
            return None
        rows = conn.execute(
            """
            SELECT id, title, item_count, privacy, channel_id
            FROM playlists
            ORDER BY rowid
            """
        ).fetchall()
        return CachedPlaylists(
            playlists=tuple(
                Playlist(
                    id=row["id"],
                    title=row["title"],
                    item_count=row["item_count"],
                    privacy=row["privacy"],
                    channel_id=row["channel_id"],
                )
                for row in rows
            ),
            fetched_at=meta["fetched_at"],
            truncated=bool(meta["truncated"]),
        )

    def replace_playlists(
        self,
        playlists: tuple[Playlist, ...],
        *,
        fetched_at: str,
        truncated: bool,
    ) -> None:
        conn = self._require_conn()
        with conn:
            conn.execute("DELETE FROM playlists")
            conn.executemany(
                """
                INSERT INTO playlists (id, title, item_count, privacy, channel_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        playlist.id,
                        playlist.title,
                        playlist.item_count,
                        playlist.privacy,
                        playlist.channel_id,
                    )
                    for playlist in playlists
                ],
            )
            conn.execute(
                """
                INSERT INTO collection_meta (name, fetched_at, truncated)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    truncated = excluded.truncated
                """,
                (PLAYLISTS_COLLECTION, fetched_at, int(truncated)),
            )

    def _init_schema(self) -> None:
        conn = self._require_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collection_meta (
                name TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                truncated INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS playlists (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                privacy TEXT NOT NULL,
                channel_id TEXT NOT NULL
            );
            """
        )

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("cache is not open")
        return self._conn
