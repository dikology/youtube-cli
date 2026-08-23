from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from youtube_cli.cache import LibraryCache
from youtube_cli.credentials import CredentialStore, KeychainCredentialStore, Tokens
from youtube_cli.youtube import (
    LiveYouTubeClient,
    NetworkError,
    Playlist,
    QuotaExceededError,
    YouTubeApiError,
    YouTubeClient,
)

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


class CliError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(CliError):
    pass


class AuthRequiredError(CliError):
    pass


class AuthExpiredError(CliError):
    pass


class CacheEmptyError(CliError):
    pass


@dataclass(frozen=True)
class PlaylistsListRequest:
    table: bool
    fresh: bool
    offline: bool
    limit: int


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(
        run(
            sys.argv[1:] if argv is None else argv,
            credentials=KeychainCredentialStore(),
        )
    )


def run(
    argv: list[str],
    *,
    credentials: CredentialStore | None = None,
    youtube: YouTubeClient | None = None,
    cache_dir: Path | None = None,
    stdout: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    try:
        request = _parse(argv)
        tokens = _require_tokens(credentials)
        client = youtube if youtube is not None else LiveYouTubeClient(tokens.access_token)
        return _playlists_list(
            request,
            youtube=client,
            cache=_open_cache(cache_dir),
            stdout=out,
        )
    except UsageError as exc:
        _write_error(out, code="usage", message=exc.message)
        return 2
    except AuthRequiredError as exc:
        _write_error(out, code="auth_required", message=exc.message)
        return 3
    except AuthExpiredError as exc:
        _write_error(out, code="auth_expired", message=exc.message)
        return 3
    except CacheEmptyError as exc:
        _write_error(out, code="cache_empty", message=exc.message)
        return 1
    except QuotaExceededError as exc:
        _write_error(out, code="quota_exceeded", message=str(exc) or "YouTube API quota exceeded")
        return 4
    except NetworkError as exc:
        _write_error(out, code="network", message=str(exc) or "network failure")
        return 6
    except YouTubeApiError as exc:
        _write_error(out, code="error", message=str(exc))
        return 1


def _parse(argv: list[str]) -> PlaylistsListRequest:
    if not argv:
        raise UsageError("missing command")

    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except UsageError:
        raise
    except SystemExit as exc:
        raise UsageError("invalid arguments") from exc

    if args.noun != "playlists" or args.verb != "list":
        raise UsageError(f"unknown command: {' '.join(argv)}")
    if args.offline and args.fresh:
        raise UsageError("--offline and --fresh cannot be combined")
    if args.limit > MAX_LIMIT or args.limit < 1:
        raise UsageError(f"--limit must be between 1 and {MAX_LIMIT}")

    return PlaylistsListRequest(
        table=args.table,
        fresh=args.fresh,
        offline=args.offline,
        limit=args.limit,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtube", add_help=False)
    parser.add_argument("noun")
    parser.add_argument("verb", nargs="?")
    parser.add_argument("--table", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    def error(message: str) -> None:
        raise UsageError(message)

    parser.error = error  # type: ignore[method-assign]
    return parser


def _require_tokens(credentials: CredentialStore | None) -> Tokens:
    if credentials is None:
        raise AuthRequiredError("not logged in; run youtube auth login")
    tokens = credentials.load()
    if tokens is None:
        raise AuthRequiredError("not logged in; run youtube auth login")
    if tokens.expires_at is not None and tokens.expires_at <= datetime.now(UTC):
        raise AuthExpiredError("access token expired; run youtube auth login")
    return tokens


def _open_cache(cache_dir: Path | None) -> LibraryCache:
    cache = LibraryCache(_resolve_cache_dir(cache_dir))
    cache.open()
    return cache


def _resolve_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env = os.environ.get("YOUTUBE_CACHE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "youtube-cli"


def _playlists_list(
    request: PlaylistsListRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    if not request.fresh:
        cached = cache.load_playlists()
        if cached is not None:
            playlists = cached.playlists[: request.limit]
            _emit_playlists(
                stdout,
                playlists=playlists,
                table=request.table,
                meta={
                    "from_cache": True,
                    "fetched_at": cached.fetched_at,
                    "truncated": cached.truncated or len(cached.playlists) > request.limit,
                    "limit": request.limit,
                },
            )
            return 0
        if request.offline:
            raise CacheEmptyError("playlists cache is empty; run without --offline")

    fetched_at = _now_iso()
    result = youtube.list_playlists(limit=request.limit)
    cache.replace_playlists(
        result.playlists,
        fetched_at=fetched_at,
        truncated=result.truncated,
    )
    _emit_playlists(
        stdout,
        playlists=result.playlists,
        table=request.table,
        meta={
            "from_cache": False,
            "fetched_at": fetched_at,
            "truncated": result.truncated,
            "limit": request.limit,
            "quota_cost": result.quota_cost,
        },
    )
    return 0


def _playlist_payload(playlist: Playlist) -> dict[str, str | int]:
    return {
        "id": playlist.id,
        "title": playlist.title,
        "item_count": playlist.item_count,
        "privacy": playlist.privacy,
        "channel_id": playlist.channel_id,
        "url": playlist.url,
    }


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit_playlists(
    out: TextIO,
    *,
    playlists: tuple[Playlist, ...],
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_table(out, playlists)
        return
    json.dump(
        {
            "ok": True,
            "data": {"playlists": [_playlist_payload(playlist) for playlist in playlists]},
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _write_table(out: TextIO, playlists: tuple[Playlist, ...]) -> None:
    out.write("id\ttitle\titem_count\tprivacy\n")
    for playlist in playlists:
        out.write(
            f"{playlist.id}\t{playlist.title}\t{playlist.item_count}\t{playlist.privacy}\n"
        )


def _write_error(out: TextIO, *, code: str, message: str) -> None:
    json.dump({"ok": False, "error": {"code": code, "message": message}}, out)
    out.write("\n")
