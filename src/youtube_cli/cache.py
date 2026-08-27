from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from youtube_cli.youtube import LikedVideo, Playlist, PlaylistItem, Subscription, Video

PLAYLISTS_COLLECTION = "playlists"
LIKES_COLLECTION = "likes"
SUBSCRIPTIONS_COLLECTION = "subscriptions"


def _items_collection(playlist_id: str) -> str:
    return f"playlist_items:{playlist_id}"


@dataclass(frozen=True)
class CollectionStatus:
    name: str
    fetched_at: str
    count: int


@dataclass(frozen=True)
class CachedPlaylists:
    playlists: tuple[Playlist, ...]
    fetched_at: str
    truncated: bool


@dataclass(frozen=True)
class CachedPlaylist:
    playlist: Playlist
    fetched_at: str


@dataclass(frozen=True)
class CachedPlaylistItems:
    items: tuple[PlaylistItem, ...]
    fetched_at: str
    truncated: bool


@dataclass(frozen=True)
class CachedLikes:
    likes: tuple[LikedVideo, ...]
    fetched_at: str
    truncated: bool


@dataclass(frozen=True)
class CachedSubscriptions:
    subscriptions: tuple[Subscription, ...]
    fetched_at: str
    truncated: bool


@dataclass(frozen=True)
class CachedVideo:
    video: Video
    fetched_at: str


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

    def clear(self) -> None:
        self.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def status(self) -> tuple[CollectionStatus, ...]:
        if not self.db_path.exists():
            return ()
        opened_here = self._conn is None
        if opened_here:
            self.open()
        try:
            conn = self._require_conn()
            rows = conn.execute(
                "SELECT name, fetched_at FROM collection_meta ORDER BY name"
            ).fetchall()
            collections: list[CollectionStatus] = []
            for row in rows:
                name = row["name"]
                count = _collection_count(conn, name)
                if count is None:
                    continue
                collections.append(
                    CollectionStatus(
                        name=name,
                        fetched_at=row["fetched_at"],
                        count=count,
                    )
                )
            return tuple(collections)
        finally:
            if opened_here:
                self.close()

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

    def load_playlist(self, playlist_id: str) -> CachedPlaylist | None:
        conn = self._require_conn()
        row = conn.execute(
            """
            SELECT id, title, item_count, privacy, channel_id, fetched_at
            FROM playlists
            WHERE id = ?
            """,
            (playlist_id,),
        ).fetchone()
        if row is None or not row["fetched_at"]:
            return None
        return CachedPlaylist(
            playlist=Playlist(
                id=row["id"],
                title=row["title"],
                item_count=row["item_count"],
                privacy=row["privacy"],
                channel_id=row["channel_id"],
            ),
            fetched_at=row["fetched_at"],
        )

    def upsert_playlist(self, playlist: Playlist, *, fetched_at: str) -> None:
        conn = self._require_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO playlists (id, title, item_count, privacy, channel_id, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    item_count = excluded.item_count,
                    privacy = excluded.privacy,
                    channel_id = excluded.channel_id,
                    fetched_at = excluded.fetched_at
                """,
                (
                    playlist.id,
                    playlist.title,
                    playlist.item_count,
                    playlist.privacy,
                    playlist.channel_id,
                    fetched_at,
                ),
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
            _write_playlists(conn, playlists, fetched_at=fetched_at, truncated=truncated)

    def replace_library(
        self,
        *,
        playlists: tuple[Playlist, ...],
        items_by_playlist: dict[str, tuple[PlaylistItem, ...]],
        likes: tuple[LikedVideo, ...],
        subscriptions: tuple[Subscription, ...],
        fetched_at: str,
        playlists_truncated: bool,
        items_truncated: dict[str, bool],
        likes_truncated: bool,
        subscriptions_truncated: bool,
    ) -> None:
        conn = self._require_conn()
        with conn:
            _write_playlists(
                conn,
                playlists,
                fetched_at=fetched_at,
                truncated=playlists_truncated,
            )
            conn.execute("DELETE FROM playlist_items")
            conn.execute(
                "DELETE FROM collection_meta WHERE name LIKE 'playlist_items:%'"
            )
            for playlist_id, items in items_by_playlist.items():
                _insert_playlist_items(
                    conn,
                    playlist_id,
                    items,
                    fetched_at=fetched_at,
                    truncated=items_truncated[playlist_id],
                )
            _write_likes(conn, likes, fetched_at=fetched_at, truncated=likes_truncated)
            _write_subscriptions(
                conn,
                subscriptions,
                fetched_at=fetched_at,
                truncated=subscriptions_truncated,
            )

    def load_playlist_items(self, playlist_id: str) -> CachedPlaylistItems | None:
        conn = self._require_conn()
        meta = conn.execute(
            "SELECT fetched_at, truncated FROM collection_meta WHERE name = ?",
            (_items_collection(playlist_id),),
        ).fetchone()
        if meta is None:
            return None
        rows = conn.execute(
            """
            SELECT playlist_id, position, video_id, title, channel_title, available
            FROM playlist_items
            WHERE playlist_id = ?
            ORDER BY position
            """,
            (playlist_id,),
        ).fetchall()
        return CachedPlaylistItems(
            items=tuple(
                PlaylistItem(
                    playlist_id=row["playlist_id"],
                    position=row["position"],
                    video_id=row["video_id"],
                    title=row["title"],
                    channel_title=row["channel_title"],
                    available=bool(row["available"]),
                )
                for row in rows
            ),
            fetched_at=meta["fetched_at"],
            truncated=bool(meta["truncated"]),
        )

    def replace_playlist_items(
        self,
        playlist_id: str,
        items: tuple[PlaylistItem, ...],
        *,
        fetched_at: str,
        truncated: bool,
    ) -> None:
        conn = self._require_conn()
        with conn:
            conn.execute(
                "DELETE FROM playlist_items WHERE playlist_id = ?",
                (playlist_id,),
            )
            _insert_playlist_items(
                conn,
                playlist_id,
                items,
                fetched_at=fetched_at,
                truncated=truncated,
            )

    def load_likes(self) -> CachedLikes | None:
        conn = self._require_conn()
        meta = conn.execute(
            "SELECT fetched_at, truncated FROM collection_meta WHERE name = ?",
            (LIKES_COLLECTION,),
        ).fetchone()
        if meta is None:
            return None
        rows = conn.execute(
            """
            SELECT position, video_id, title, channel_title, available
            FROM likes
            ORDER BY CASE WHEN position IS NULL THEN 1 ELSE 0 END, position, rowid
            """
        ).fetchall()
        return CachedLikes(
            likes=tuple(
                LikedVideo(
                    video_id=row["video_id"],
                    title=row["title"],
                    channel_title=row["channel_title"],
                    available=bool(row["available"]),
                    position=row["position"],
                )
                for row in rows
            ),
            fetched_at=meta["fetched_at"],
            truncated=bool(meta["truncated"]),
        )

    def replace_likes(
        self,
        likes: tuple[LikedVideo, ...],
        *,
        fetched_at: str,
        truncated: bool,
    ) -> None:
        conn = self._require_conn()
        with conn:
            _write_likes(conn, likes, fetched_at=fetched_at, truncated=truncated)

    def load_subscriptions(self) -> CachedSubscriptions | None:
        conn = self._require_conn()
        meta = conn.execute(
            "SELECT fetched_at, truncated FROM collection_meta WHERE name = ?",
            (SUBSCRIPTIONS_COLLECTION,),
        ).fetchone()
        if meta is None:
            return None
        rows = conn.execute(
            """
            SELECT channel_id, title, subscribed_at
            FROM subscriptions
            ORDER BY rowid
            """
        ).fetchall()
        return CachedSubscriptions(
            subscriptions=tuple(
                Subscription(
                    channel_id=row["channel_id"],
                    title=row["title"],
                    subscribed_at=row["subscribed_at"],
                )
                for row in rows
            ),
            fetched_at=meta["fetched_at"],
            truncated=bool(meta["truncated"]),
        )

    def replace_subscriptions(
        self,
        subscriptions: tuple[Subscription, ...],
        *,
        fetched_at: str,
        truncated: bool,
    ) -> None:
        conn = self._require_conn()
        with conn:
            _write_subscriptions(
                conn,
                subscriptions,
                fetched_at=fetched_at,
                truncated=truncated,
            )

    def load_video(self, video_id: str) -> CachedVideo | None:
        conn = self._require_conn()
        row = conn.execute(
            """
            SELECT id, title, channel_id, channel_title, description,
                   duration_seconds, published_at, privacy, available, fetched_at
            FROM videos
            WHERE id = ?
            """,
            (video_id,),
        ).fetchone()
        if row is None:
            return None
        return CachedVideo(
            video=Video(
                id=row["id"],
                title=row["title"],
                channel_id=row["channel_id"],
                channel_title=row["channel_title"],
                description=row["description"],
                duration_seconds=row["duration_seconds"],
                published_at=row["published_at"],
                privacy=row["privacy"],
                available=bool(row["available"]),
            ),
            fetched_at=row["fetched_at"],
        )

    def missing_video_ids(self, video_ids: tuple[str, ...]) -> tuple[str, ...]:
        if not video_ids:
            return ()
        conn = self._require_conn()
        placeholders = ",".join("?" * len(video_ids))
        rows = conn.execute(
            f"SELECT id FROM videos WHERE id IN ({placeholders})",
            video_ids,
        ).fetchall()
        present = {row["id"] for row in rows}
        return tuple(video_id for video_id in video_ids if video_id not in present)

    def upsert_video(self, video: Video, *, fetched_at: str) -> None:
        self.upsert_videos((video,), fetched_at=fetched_at)

    def upsert_videos(self, videos: tuple[Video, ...], *, fetched_at: str) -> None:
        conn = self._require_conn()
        with conn:
            conn.executemany(
                """
                INSERT INTO videos (
                    id, title, channel_id, channel_title, description,
                    duration_seconds, published_at, privacy, available, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    channel_id = excluded.channel_id,
                    channel_title = excluded.channel_title,
                    description = excluded.description,
                    duration_seconds = excluded.duration_seconds,
                    published_at = excluded.published_at,
                    privacy = excluded.privacy,
                    available = excluded.available,
                    fetched_at = excluded.fetched_at
                """,
                [
                    (
                        video.id,
                        video.title,
                        video.channel_id,
                        video.channel_title,
                        video.description,
                        video.duration_seconds,
                        video.published_at,
                        video.privacy,
                        int(video.available),
                        fetched_at,
                    )
                    for video in videos
                ],
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
                channel_id TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                available INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, position)
            );
            CREATE TABLE IF NOT EXISTS likes (
                position INTEGER,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                available INTEGER NOT NULL,
                PRIMARY KEY (video_id)
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                channel_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                subscribed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                description TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                published_at TEXT NOT NULL,
                privacy TEXT NOT NULL,
                available INTEGER NOT NULL,
                fetched_at TEXT NOT NULL
            );
            """
        )
        self._ensure_column("playlists", "fetched_at", "TEXT NOT NULL DEFAULT ''")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        conn = self._require_conn()
        columns = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("cache is not open")
        return self._conn


def _upsert_collection_meta(
    conn: sqlite3.Connection, name: str, *, fetched_at: str, truncated: bool
) -> None:
    conn.execute(
        """
        INSERT INTO collection_meta (name, fetched_at, truncated)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            fetched_at = excluded.fetched_at,
            truncated = excluded.truncated
        """,
        (name, fetched_at, int(truncated)),
    )


def _write_playlists(
    conn: sqlite3.Connection,
    playlists: tuple[Playlist, ...],
    *,
    fetched_at: str,
    truncated: bool,
) -> None:
    conn.execute("DELETE FROM playlists")
    conn.executemany(
        """
        INSERT INTO playlists (id, title, item_count, privacy, channel_id, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                playlist.id,
                playlist.title,
                playlist.item_count,
                playlist.privacy,
                playlist.channel_id,
                fetched_at,
            )
            for playlist in playlists
        ],
    )
    _upsert_collection_meta(
        conn, PLAYLISTS_COLLECTION, fetched_at=fetched_at, truncated=truncated
    )


def _insert_playlist_items(
    conn: sqlite3.Connection,
    playlist_id: str,
    items: tuple[PlaylistItem, ...],
    *,
    fetched_at: str,
    truncated: bool,
) -> None:
    conn.executemany(
        """
        INSERT INTO playlist_items (
            playlist_id, position, video_id, title, channel_title, available
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item.playlist_id,
                item.position,
                item.video_id,
                item.title,
                item.channel_title,
                int(item.available),
            )
            for item in items
        ],
    )
    _upsert_collection_meta(
        conn,
        _items_collection(playlist_id),
        fetched_at=fetched_at,
        truncated=truncated,
    )


def _write_likes(
    conn: sqlite3.Connection,
    likes: tuple[LikedVideo, ...],
    *,
    fetched_at: str,
    truncated: bool,
) -> None:
    conn.execute("DELETE FROM likes")
    conn.executemany(
        """
        INSERT INTO likes (position, video_id, title, channel_title, available)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                item.position,
                item.video_id,
                item.title,
                item.channel_title,
                int(item.available),
            )
            for item in likes
        ],
    )
    _upsert_collection_meta(
        conn, LIKES_COLLECTION, fetched_at=fetched_at, truncated=truncated
    )


def _write_subscriptions(
    conn: sqlite3.Connection,
    subscriptions: tuple[Subscription, ...],
    *,
    fetched_at: str,
    truncated: bool,
) -> None:
    conn.execute("DELETE FROM subscriptions")
    conn.executemany(
        """
        INSERT INTO subscriptions (channel_id, title, subscribed_at)
        VALUES (?, ?, ?)
        """,
        [
            (item.channel_id, item.title, item.subscribed_at)
            for item in subscriptions
        ],
    )
    _upsert_collection_meta(
        conn, SUBSCRIPTIONS_COLLECTION, fetched_at=fetched_at, truncated=truncated
    )


def _collection_count(conn: sqlite3.Connection, name: str) -> int | None:
    table = {
        PLAYLISTS_COLLECTION: "playlists",
        LIKES_COLLECTION: "likes",
        SUBSCRIPTIONS_COLLECTION: "subscriptions",
    }.get(name)
    if table is None:
        return None
    count_row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(count_row["n"]) if count_row is not None else 0
