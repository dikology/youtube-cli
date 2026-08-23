from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from youtube_cli.cache import CollectionStatus, LibraryCache
from youtube_cli.credentials import CredentialStore, KeychainCredentialStore, Tokens
from youtube_cli.oauth import (
    ClientSecretError,
    LoginError,
    exchange_google_code,
    load_client_credentials,
    login_via_loopback,
    refresh_google_tokens,
)
from youtube_cli.youtube import (
    LiveYouTubeClient,
    NetworkError,
    Playlist,
    QuotaExceededError,
    UnauthorizedError,
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
class AuthLoginRequest:
    pass


@dataclass(frozen=True)
class AuthLogoutRequest:
    wipe: bool


@dataclass(frozen=True)
class AuthStatusRequest:
    table: bool


@dataclass(frozen=True)
class CacheClearRequest:
    pass


@dataclass(frozen=True)
class CacheStatusRequest:
    table: bool


@dataclass(frozen=True)
class PlaylistsListRequest:
    table: bool
    fresh: bool
    offline: bool
    limit: int


Request = (
    AuthLoginRequest
    | AuthLogoutRequest
    | AuthStatusRequest
    | CacheClearRequest
    | CacheStatusRequest
    | PlaylistsListRequest
)


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
    config_dir: Path | None = None,
    stdout: TextIO | None = None,
    open_browser: Callable[[str], object] | None = None,
    exchange_code: Callable[..., Tokens] | None = None,
    refresh_tokens: Callable[[Tokens], Tokens] | None = None,
) -> int:
    out = stdout or sys.stdout
    try:
        request = _parse(argv)
        if isinstance(request, AuthLoginRequest):
            return _auth_login(
                credentials=credentials,
                config_dir=config_dir,
                stdout=out,
                open_browser=open_browser,
                exchange_code=exchange_code,
            )
        if isinstance(request, AuthLogoutRequest):
            return _auth_logout(
                request,
                credentials=credentials,
                cache_dir=cache_dir,
                stdout=out,
            )
        if isinstance(request, AuthStatusRequest):
            return _auth_status(
                request,
                credentials=credentials,
                youtube=youtube,
                config_dir=config_dir,
                refresh_tokens=refresh_tokens,
                stdout=out,
            )
        if isinstance(request, CacheStatusRequest):
            return _cache_status(request, cache_dir=cache_dir, stdout=out)
        if isinstance(request, CacheClearRequest):
            return _cache_clear(cache_dir=cache_dir, stdout=out)
        tokens = _require_tokens(
            credentials,
            config_dir=config_dir,
            refresh_tokens=refresh_tokens,
        )
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
    except (ClientSecretError, LoginError, CliError) as exc:
        _write_error(out, code="error", message=exc.message)
        return 1


def _parse(argv: list[str]) -> Request:
    if not argv:
        raise UsageError("missing command")

    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except UsageError:
        raise
    except SystemExit as exc:
        raise UsageError("invalid arguments") from exc

    if args.wipe and not (args.noun == "auth" and args.verb == "logout"):
        raise UsageError("--wipe is only valid with auth logout")
    if args.noun == "auth" and args.verb == "status":
        return AuthStatusRequest(table=args.table)
    if args.noun == "auth" and args.verb == "logout":
        return AuthLogoutRequest(wipe=args.wipe)
    if args.noun == "auth" and args.verb == "login":
        return AuthLoginRequest()
    if args.noun == "cache" and args.verb == "status":
        return CacheStatusRequest(table=args.table)
    if args.noun == "cache" and args.verb == "clear":
        return CacheClearRequest()
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
    parser.add_argument("--wipe", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    def error(message: str) -> None:
        raise UsageError(message)

    parser.error = error  # type: ignore[method-assign]
    return parser


def _require_tokens(
    credentials: CredentialStore | None,
    *,
    config_dir: Path | None,
    refresh_tokens: Callable[[Tokens], Tokens] | None,
) -> Tokens:
    if credentials is None:
        raise AuthRequiredError("not logged in; run youtube auth login")
    tokens = credentials.load()
    if tokens is None:
        raise AuthRequiredError("not logged in; run youtube auth login")
    tokens = _refresh_if_needed(
        tokens,
        credentials=credentials,
        config_dir=config_dir,
        refresh_tokens=refresh_tokens,
    )
    if _expired(tokens):
        raise AuthExpiredError("access token expired; run youtube auth login")
    return tokens


def _expired(tokens: Tokens) -> bool:
    return tokens.expires_at is not None and tokens.expires_at <= datetime.now(UTC)


def _refresh_if_needed(
    tokens: Tokens,
    *,
    credentials: CredentialStore,
    config_dir: Path | None,
    refresh_tokens: Callable[[Tokens], Tokens] | None,
) -> Tokens:
    if not _expired(tokens) or not tokens.refresh_token:
        return tokens
    try:
        if refresh_tokens is not None:
            refreshed = refresh_tokens(tokens)
        else:
            client = load_client_credentials(config_dir=_resolve_config_dir(config_dir))
            refreshed = refresh_google_tokens(tokens, client)
    except (ClientSecretError, LoginError):
        return tokens
    credentials.save(refreshed)
    return refreshed


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


def _auth_login(
    *,
    credentials: CredentialStore | None,
    config_dir: Path | None,
    stdout: TextIO,
    open_browser: Callable[[str], object] | None,
    exchange_code: Callable[..., Tokens] | None,
) -> int:
    if credentials is None:
        raise CliError("credential store is required for login")
    client = load_client_credentials(config_dir=_resolve_config_dir(config_dir))
    exchanger = exchange_code if exchange_code is not None else exchange_google_code
    tokens = login_via_loopback(
        client,
        open_browser=open_browser or webbrowser.open,
        exchange_code=exchanger,
    )
    credentials.save(tokens)
    json.dump(
        {
            "ok": True,
            "data": {"logged_in": True},
            "meta": {
                "from_cache": False,
                "fetched_at": _now_iso(),
                "truncated": False,
                "limit": DEFAULT_LIMIT,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


def _resolve_config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return config_dir
    return Path.home() / ".config" / "youtube-cli"


def _auth_logout(
    request: AuthLogoutRequest,
    *,
    credentials: CredentialStore | None,
    cache_dir: Path | None,
    stdout: TextIO,
) -> int:
    if credentials is not None:
        credentials.delete()
    if request.wipe:
        LibraryCache(_resolve_cache_dir(cache_dir)).clear()
    json.dump(
        {
            "ok": True,
            "data": {"logged_out": True, "wiped": request.wipe},
            "meta": {
                "from_cache": False,
                "fetched_at": _now_iso(),
                "truncated": False,
                "limit": DEFAULT_LIMIT,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


def _auth_status(
    request: AuthStatusRequest,
    *,
    credentials: CredentialStore | None,
    youtube: YouTubeClient | None,
    config_dir: Path | None,
    refresh_tokens: Callable[[Tokens], Tokens] | None,
    stdout: TextIO,
) -> int:
    tokens = credentials.load() if credentials is not None else None
    if tokens is not None and credentials is not None:
        tokens = _refresh_if_needed(
            tokens,
            credentials=credentials,
            config_dir=config_dir,
            refresh_tokens=refresh_tokens,
        )
    token_ok = tokens is not None and not _expired(tokens)
    channel_title: str | None = None
    quota_cost: int | None = None
    if token_ok:
        assert tokens is not None
        client = youtube if youtube is not None else LiveYouTubeClient(tokens.access_token)
        try:
            channel_title = client.get_mine_channel().title
            quota_cost = 1
        except UnauthorizedError:
            token_ok = False
            quota_cost = 1
    data: dict[str, object] = {
        "channel_title": channel_title,
        "token_ok": token_ok,
        "expires_at": _iso(tokens.expires_at) if tokens is not None and tokens.expires_at else None,
    }
    meta: dict[str, object] = {
        "from_cache": False,
        "fetched_at": _now_iso(),
        "truncated": False,
        "limit": DEFAULT_LIMIT,
    }
    if quota_cost is not None:
        meta["quota_cost"] = quota_cost
    if request.table:
        _write_auth_status_table(stdout, data)
        return 0
    json.dump({"ok": True, "data": data, "meta": meta}, stdout)
    stdout.write("\n")
    return 0


def _cache_status(
    request: CacheStatusRequest,
    *,
    cache_dir: Path | None,
    stdout: TextIO,
) -> int:
    cache = LibraryCache(_resolve_cache_dir(cache_dir))
    collections = cache.status()
    data = {
        "path": str(cache.db_path),
        "collections": {
            item.name: {"fetched_at": item.fetched_at, "count": item.count}
            for item in collections
        },
    }
    if request.table:
        _write_cache_status_table(stdout, cache.db_path, collections)
        return 0
    json.dump(
        {
            "ok": True,
            "data": data,
            "meta": {
                "from_cache": True,
                "fetched_at": collections[0].fetched_at if collections else _now_iso(),
                "truncated": False,
                "limit": DEFAULT_LIMIT,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


def _cache_clear(*, cache_dir: Path | None, stdout: TextIO) -> int:
    cache = LibraryCache(_resolve_cache_dir(cache_dir))
    cache.clear()
    json.dump(
        {
            "ok": True,
            "data": {"cleared": True},
            "meta": {
                "from_cache": True,
                "fetched_at": _now_iso(),
                "truncated": False,
                "limit": DEFAULT_LIMIT,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


def _write_cache_status_table(
    out: TextIO, path: Path, collections: tuple[CollectionStatus, ...]
) -> None:
    out.write(f"path\t{path}\n")
    out.write("collection\tfetched_at\tcount\n")
    for item in collections:
        out.write(f"{item.name}\t{item.fetched_at}\t{item.count}\n")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_auth_status_table(out: TextIO, data: dict[str, object]) -> None:
    out.write("channel_title\ttoken_ok\texpires_at\n")
    out.write(
        f"{_table_cell(data['channel_title'])}\t"
        f"{_table_cell(data['token_ok'])}\t"
        f"{_table_cell(data['expires_at'])}\n"
    )


def _table_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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
