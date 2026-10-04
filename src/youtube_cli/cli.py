from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from youtube_cli.cache import CollectionStatus, LibraryCache, SearchHit
from youtube_cli.credentials import CredentialStore, KeychainCredentialStore, Tokens
from youtube_cli.oauth import (
    ClientSecretError,
    LoginError,
    exchange_google_code,
    load_client_credentials,
    login_via_loopback,
    refresh_google_tokens,
)
from youtube_cli.transcripts import (
    DEFAULT_WHISPER_MODEL,
    AudioSource,
    CaptionSource,
    LiveAudioSource,
    LiveCaptionSource,
    LiveSpeechRecognizer,
    NoCaptionsError,
    SpeechRecognizer,
    Transcript,
    TranscriptError,
    TranscriptsExtraMissingError,
    VideoRestrictedError,
    choose_track,
    generate_transcript,
    language_matches,
)
from youtube_cli.youtube import (
    LiveYouTubeClient,
    NetworkError,
    NotFoundError,
    LikedVideo,
    Playlist,
    PlaylistItem,
    QuotaExceededError,
    Subscription,
    UnauthorizedError,
    Video,
    YouTubeApiError,
    YouTubeClient,
    parse_video_id,
)

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000
SEARCH_TYPES = ("playlist", "video", "channel")


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


class OfflineMissError(CliError):
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


@dataclass(frozen=True)
class PlaylistShowRequest:
    playlist_id: str
    table: bool
    fresh: bool
    offline: bool
    limit: int


@dataclass(frozen=True)
class PlaylistItemsRequest:
    playlist_id: str
    table: bool
    fresh: bool
    offline: bool
    limit: int
    hydrate: bool


@dataclass(frozen=True)
class LikesListRequest:
    table: bool
    fresh: bool
    offline: bool
    limit: int
    hydrate: bool


@dataclass(frozen=True)
class SubsListRequest:
    table: bool
    fresh: bool
    offline: bool
    limit: int


@dataclass(frozen=True)
class VideoGetRequest:
    video_id: str
    table: bool
    fresh: bool
    offline: bool
    limit: int


@dataclass(frozen=True)
class VideoTranscriptRequest:
    video_id: str
    language: str | None
    table: bool
    text: bool
    fresh: bool
    offline: bool
    limit: int
    generate: bool = False


@dataclass(frozen=True)
class SyncCollectionRequest:
    collection: str
    limit: int
    playlist_id: str | None = None


@dataclass(frozen=True)
class SearchRequest:
    query: str
    types: frozenset[str]
    table: bool
    limit: int


Request = (
    AuthLoginRequest
    | AuthLogoutRequest
    | AuthStatusRequest
    | CacheClearRequest
    | CacheStatusRequest
    | PlaylistsListRequest
    | PlaylistShowRequest
    | PlaylistItemsRequest
    | LikesListRequest
    | SubsListRequest
    | VideoGetRequest
    | VideoTranscriptRequest
    | SyncCollectionRequest
    | SearchRequest
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
    captions: CaptionSource | None = None,
    audio: AudioSource | None = None,
    recognizer: SpeechRecognizer | None = None,
    cache_dir: Path | None = None,
    config_dir: Path | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
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
        if isinstance(request, SearchRequest):
            return _search(request, cache_dir=cache_dir, stdout=out)
        if isinstance(request, VideoTranscriptRequest):
            return _video_transcript(
                request,
                captions=captions,
                audio=audio,
                recognizer=recognizer,
                cache=_open_cache(cache_dir),
                stdout=out,
                stderr=stderr or sys.stderr,
            )
        tokens = _require_tokens(
            credentials,
            config_dir=config_dir,
            refresh_tokens=refresh_tokens,
        )
        client = youtube if youtube is not None else LiveYouTubeClient(tokens.access_token)
        cache = _open_cache(cache_dir)
        if isinstance(request, PlaylistShowRequest):
            return _playlist_show(request, youtube=client, cache=cache, stdout=out)
        if isinstance(request, PlaylistItemsRequest):
            return _playlist_items(request, youtube=client, cache=cache, stdout=out)
        if isinstance(request, LikesListRequest):
            return _likes_list(request, youtube=client, cache=cache, stdout=out)
        if isinstance(request, SubsListRequest):
            return _subs_list(request, youtube=client, cache=cache, stdout=out)
        if isinstance(request, VideoGetRequest):
            return _video_get(request, youtube=client, cache=cache, stdout=out)
        if isinstance(request, SyncCollectionRequest):
            return _sync_collection(request, youtube=client, cache=cache, stdout=out)
        return _playlists_list(
            request,
            youtube=client,
            cache=cache,
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
    except OfflineMissError as exc:
        _write_error(out, code="offline_miss", message=exc.message)
        return 1
    except NotFoundError as exc:
        _write_error(out, code="not_found", message=str(exc) or "not found")
        return 5
    except QuotaExceededError as exc:
        _write_error(out, code="quota_exceeded", message=str(exc) or "YouTube API quota exceeded")
        return 4
    except NetworkError as exc:
        _write_error(out, code="network", message=str(exc) or "network failure")
        return 6
    except NoCaptionsError as exc:
        _write_error(out, code="no_captions", message=str(exc))
        return 7
    except TranscriptsExtraMissingError as exc:
        _write_error(out, code="transcripts_extra_missing", message=str(exc))
        return 8
    except VideoRestrictedError as exc:
        _write_error(out, code="video_restricted", message=str(exc))
        return 9
    except (YouTubeApiError, TranscriptError) as exc:
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
    if args.type is not None and args.noun != "search":
        raise UsageError("--type is only valid with search")
    transcript = args.noun == "video" and args.verb == "transcript"
    if args.text and not transcript:
        raise UsageError("--text is only valid with video transcript")
    if args.lang is not None and not transcript:
        raise UsageError("--lang is only valid with video transcript")
    if args.generate and not transcript:
        raise UsageError("--generate is only valid with video transcript")
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
    if args.offline and args.fresh:
        raise UsageError("--offline and --fresh cannot be combined")
    if args.limit > MAX_LIMIT or args.limit < 1:
        raise UsageError(f"--limit must be between 1 and {MAX_LIMIT}")
    if args.noun == "search":
        if not args.verb:
            raise UsageError("search requires a query")
        if args.target:
            raise UsageError("search takes one query; quote multi-word queries")
        if args.fresh:
            raise UsageError("search is cache-only and cannot be used with --fresh")
        return SearchRequest(
            query=args.verb,
            types=frozenset(SEARCH_TYPES if args.type is None else (args.type,)),
            table=args.table,
            limit=args.limit,
        )
    if args.noun == "playlists" and args.verb == "list":
        if args.target:
            raise UsageError("playlists list does not take an id")
        return PlaylistsListRequest(
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
        )
    if args.noun == "playlist" and args.verb == "show":
        if not args.target:
            raise UsageError("playlist show requires a playlist id")
        return PlaylistShowRequest(
            playlist_id=args.target,
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
        )
    if args.noun == "playlist" and args.verb == "items":
        if not args.target:
            raise UsageError("playlist items requires a playlist id")
        return PlaylistItemsRequest(
            playlist_id=args.target,
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
            hydrate=args.hydrate,
        )
    if args.noun == "likes" and args.verb == "list":
        if args.target:
            raise UsageError("likes list does not take an id")
        return LikesListRequest(
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
            hydrate=args.hydrate,
        )
    if args.noun == "subs" and args.verb == "list":
        if args.target:
            raise UsageError("subs list does not take an id")
        return SubsListRequest(
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
        )
    if args.noun == "video" and args.verb == "get":
        if not args.target:
            raise UsageError("video get requires a video id")
        return VideoGetRequest(
            video_id=_video_id(args.target),
            table=args.table,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
        )
    if transcript:
        if not args.target:
            raise UsageError("video transcript requires a video id or url")
        if args.table and args.text:
            raise UsageError("--table and --text cannot be combined")
        return VideoTranscriptRequest(
            video_id=_video_id(args.target),
            language=args.lang,
            table=args.table,
            text=args.text,
            fresh=args.fresh,
            offline=args.offline,
            limit=args.limit,
            generate=args.generate,
        )
    if args.noun == "sync" and args.offline:
        raise UsageError("sync cannot be used with --offline")
    if args.noun == "sync" and args.verb is None:
        return SyncCollectionRequest(
            collection="library",
            limit=args.limit,
        )
    if args.noun == "sync" and args.verb == "playlist":
        if not args.target:
            raise UsageError("sync playlist requires a playlist id")
        return SyncCollectionRequest(
            collection="playlist",
            limit=args.limit,
            playlist_id=args.target,
        )
    if args.noun == "sync" and args.verb in {"likes", "subs", "playlists"}:
        if args.target:
            raise UsageError(f"sync {args.verb} does not take an id")
        return SyncCollectionRequest(
            collection=args.verb,
            limit=args.limit,
        )
    raise UsageError(f"unknown command: {' '.join(argv)}")


def _video_id(target: str) -> str:
    video_id = parse_video_id(target)
    if video_id is None:
        raise UsageError(f"not a video id or YouTube video url: {target}")
    return video_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtube", add_help=False)
    parser.add_argument("noun")
    parser.add_argument("verb", nargs="?")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--table", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--wipe", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--hydrate", action="store_true")
    parser.add_argument("--type", choices=SEARCH_TYPES)
    parser.add_argument("--lang")
    parser.add_argument("--text", action="store_true")
    parser.add_argument("--generate", action="store_true")

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


def _search(
    request: SearchRequest,
    *,
    cache_dir: Path | None,
    stdout: TextIO,
) -> int:
    cache = LibraryCache(_resolve_cache_dir(cache_dir))
    found = None
    if cache.db_path.exists():
        cache.open()
        try:
            found = cache.search(request.query, types=request.types)
        finally:
            cache.close()
    if found is None:
        raise CacheEmptyError("library cache is empty; run a list command or youtube sync")
    hits = found.hits[: request.limit]
    if request.table:
        _write_search_table(stdout, hits)
        return 0
    json.dump(
        {
            "ok": True,
            "data": {"hits": [_search_hit_payload(hit) for hit in hits]},
            "meta": {
                "from_cache": True,
                "fetched_at": found.fetched_at,
                "truncated": found.truncated or len(found.hits) > request.limit,
                "limit": request.limit,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


def _search_hit_payload(hit: SearchHit) -> dict[str, object]:
    resource = hit.resource
    if isinstance(resource, Playlist):
        payload: dict[str, object] = dict(_playlist_payload(resource))
    elif isinstance(resource, Video):
        payload = dict(_video_payload(resource))
    elif isinstance(resource, PlaylistItem):
        payload = dict(_playlist_item_payload(resource))
    elif isinstance(resource, LikedVideo):
        payload = dict(_liked_payload(resource))
    else:
        payload = dict(_subscription_payload(resource))
    return {"type": hit.type, **payload}


def _search_hit_id(hit: SearchHit) -> str:
    resource = hit.resource
    if isinstance(resource, (Playlist, Video)):
        return resource.id
    if isinstance(resource, Subscription):
        return resource.channel_id
    return resource.video_id


def _write_search_table(out: TextIO, hits: tuple[SearchHit, ...]) -> None:
    out.write("type\tid\ttitle\n")
    for hit in hits:
        out.write(f"{hit.type}\t{_search_hit_id(hit)}\t{hit.resource.title}\n")


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


def _playlist_show(
    request: PlaylistShowRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    if not request.fresh:
        cached = cache.load_playlist(request.playlist_id)
        if cached is not None:
            _emit_playlist(
                stdout,
                playlist=cached.playlist,
                table=request.table,
                meta={
                    "from_cache": True,
                    "fetched_at": cached.fetched_at,
                    "truncated": False,
                    "limit": request.limit,
                },
            )
            return 0
        if request.offline:
            raise OfflineMissError("playlist is not in the cache; run without --offline")

    fetched_at = _now_iso()
    result = youtube.get_playlist(request.playlist_id)
    cache.upsert_playlist(result.playlist, fetched_at=fetched_at)
    _emit_playlist(
        stdout,
        playlist=result.playlist,
        table=request.table,
        meta={
            "from_cache": False,
            "fetched_at": fetched_at,
            "truncated": False,
            "limit": request.limit,
            "quota_cost": result.quota_cost,
        },
    )
    return 0


def _playlist_items(
    request: PlaylistItemsRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    cached = None if request.fresh else cache.load_playlist_items(request.playlist_id)
    if cached is not None:
        items = cached.items[: request.limit]
        fetched_at = cached.fetched_at
        truncated = cached.truncated or len(cached.items) > request.limit
        from_cache = True
        quota_cost = 0
    elif request.offline:
        raise OfflineMissError(
            "playlist items are not in the cache; run without --offline"
        )
    else:
        fetched_at = _now_iso()
        result = youtube.list_playlist_items(
            request.playlist_id, limit=request.limit
        )
        cache.replace_playlist_items(
            request.playlist_id,
            result.items,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        items = result.items
        truncated = result.truncated
        from_cache = False
        quota_cost = result.quota_cost

    if request.hydrate:
        video_quota = _hydrate_videos(
            tuple(item.video_id for item in items if item.available and item.video_id),
            youtube=youtube,
            cache=cache,
            fresh=request.fresh,
            offline=request.offline,
        )
        if video_quota:
            quota_cost += video_quota
            from_cache = False

    meta: dict[str, object] = {
        "from_cache": from_cache,
        "fetched_at": fetched_at,
        "truncated": truncated,
        "limit": request.limit,
    }
    if quota_cost:
        meta["quota_cost"] = quota_cost
    _emit_playlist_items(
        stdout,
        items=items,
        table=request.table,
        meta=meta,
    )
    return 0


def _sync_collection(
    request: SyncCollectionRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    fetched_at = _now_iso()
    if request.collection == "likes":
        result = youtube.list_likes(limit=request.limit)
        cache.replace_likes(
            result.likes,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        quota_cost = result.quota_cost
        truncated = result.truncated
        collections = ["likes"]
    elif request.collection == "subs":
        result = youtube.list_subscriptions(limit=request.limit)
        cache.replace_subscriptions(
            result.subscriptions,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        quota_cost = result.quota_cost
        truncated = result.truncated
        collections = ["subscriptions"]
    elif request.collection == "playlist":
        playlist_id = request.playlist_id
        if playlist_id is None:
            raise UsageError("sync playlist requires a playlist id")
        result = youtube.list_playlist_items(playlist_id, limit=request.limit)
        cache.replace_playlist_items(
            playlist_id,
            result.items,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        quota_cost = result.quota_cost
        truncated = result.truncated
        collections = [f"playlist_items:{playlist_id}"]
    elif request.collection == "library":
        playlists_result = youtube.list_playlists(limit=request.limit)
        quota_cost = playlists_result.quota_cost
        truncated = playlists_result.truncated
        items_by_playlist: dict[str, tuple[PlaylistItem, ...]] = {}
        items_truncated: dict[str, bool] = {}
        for playlist in playlists_result.playlists:
            items_result = youtube.list_playlist_items(
                playlist.id, limit=request.limit
            )
            items_by_playlist[playlist.id] = items_result.items
            items_truncated[playlist.id] = items_result.truncated
            quota_cost += items_result.quota_cost
            truncated = truncated or items_result.truncated
        likes_result = youtube.list_likes(limit=request.limit)
        quota_cost += likes_result.quota_cost
        truncated = truncated or likes_result.truncated
        subs_result = youtube.list_subscriptions(limit=request.limit)
        quota_cost += subs_result.quota_cost
        truncated = truncated or subs_result.truncated
        cache.replace_library(
            playlists=playlists_result.playlists,
            items_by_playlist=items_by_playlist,
            likes=likes_result.likes,
            subscriptions=subs_result.subscriptions,
            fetched_at=fetched_at,
            playlists_truncated=playlists_result.truncated,
            items_truncated=items_truncated,
            likes_truncated=likes_result.truncated,
            subscriptions_truncated=subs_result.truncated,
        )
        collections = [
            "playlists",
            *[f"playlist_items:{playlist_id}" for playlist_id in items_by_playlist],
            "likes",
            "subscriptions",
        ]
    elif request.collection == "playlists":
        result = youtube.list_playlists(limit=request.limit)
        cache.replace_playlists(
            result.playlists,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        quota_cost = result.quota_cost
        truncated = result.truncated
        collections = ["playlists"]
    else:
        raise UsageError(f"unknown command: sync {request.collection}")
    json.dump(
        {
            "ok": True,
            "data": {"collections": collections},
            "meta": {
                "from_cache": False,
                "fetched_at": fetched_at,
                "truncated": truncated,
                "limit": request.limit,
                "quota_cost": quota_cost,
            },
        },
        stdout,
    )
    stdout.write("\n")
    return 0


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


def _likes_list(
    request: LikesListRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    cached = None if request.fresh else cache.load_likes()
    if cached is not None:
        likes = cached.likes[: request.limit]
        fetched_at = cached.fetched_at
        truncated = cached.truncated or len(cached.likes) > request.limit
        from_cache = True
        quota_cost = 0
    elif request.offline:
        raise CacheEmptyError("likes cache is empty; run without --offline")
    else:
        fetched_at = _now_iso()
        result = youtube.list_likes(limit=request.limit)
        cache.replace_likes(
            result.likes,
            fetched_at=fetched_at,
            truncated=result.truncated,
        )
        likes = result.likes
        truncated = result.truncated
        from_cache = False
        quota_cost = result.quota_cost

    if request.hydrate:
        video_quota = _hydrate_videos(
            tuple(item.video_id for item in likes if item.available and item.video_id),
            youtube=youtube,
            cache=cache,
            fresh=request.fresh,
            offline=request.offline,
        )
        if video_quota:
            quota_cost += video_quota
            from_cache = False

    meta: dict[str, object] = {
        "from_cache": from_cache,
        "fetched_at": fetched_at,
        "truncated": truncated,
        "limit": request.limit,
    }
    if quota_cost:
        meta["quota_cost"] = quota_cost
    _emit_likes(
        stdout,
        likes=likes,
        table=request.table,
        meta=meta,
    )
    return 0


def _hydrate_videos(
    video_ids: tuple[str, ...],
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    fresh: bool,
    offline: bool,
) -> int:
    unique_ids = tuple(dict.fromkeys(video_id for video_id in video_ids if video_id))
    if not unique_ids:
        return 0
    if fresh and not offline:
        to_fetch = unique_ids
    else:
        to_fetch = cache.missing_video_ids(unique_ids)
    if not to_fetch:
        return 0
    if offline:
        raise OfflineMissError("videos are not in the cache; run without --offline")
    fetched_at = _now_iso()
    result = youtube.list_videos(to_fetch)
    cache.upsert_videos(result.videos, fetched_at=fetched_at)
    return result.quota_cost


def _video_get(
    request: VideoGetRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    if not request.fresh:
        cached = cache.load_video(request.video_id)
        if cached is not None:
            _emit_video(
                stdout,
                video=cached.video,
                table=request.table,
                meta={
                    "from_cache": True,
                    "fetched_at": cached.fetched_at,
                    "truncated": False,
                    "limit": request.limit,
                },
            )
            return 0
        if request.offline:
            raise OfflineMissError("video is not in the cache; run without --offline")

    fetched_at = _now_iso()
    result = youtube.list_videos((request.video_id,))
    if not result.videos:
        raise NotFoundError(f"video {request.video_id} not found")
    video = result.videos[0]
    cache.upsert_video(video, fetched_at=fetched_at)
    _emit_video(
        stdout,
        video=video,
        table=request.table,
        meta={
            "from_cache": False,
            "fetched_at": fetched_at,
            "truncated": False,
            "limit": request.limit,
            "quota_cost": result.quota_cost,
        },
    )
    return 0


def _video_transcript(
    request: VideoTranscriptRequest,
    *,
    captions: CaptionSource | None,
    audio: AudioSource | None,
    recognizer: SpeechRecognizer | None,
    cache: LibraryCache,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    cached = (
        None
        if request.fresh
        else cache.load_transcript(request.video_id, language=request.language)
    )
    if request.generate and cached is not None and cached.transcript.source != "generated":
        cached = None
    if cached is not None:
        transcript = cached.transcript
        fetched_at = cached.fetched_at
    elif request.offline:
        raise OfflineMissError("transcript is not in the cache; run without --offline")
    else:
        fetched_at = _now_iso()
        transcript, spoken = None, None
        if not request.generate:
            transcript, spoken = _captions_transcript(request, captions=captions)
        original = request.language is None or (
            spoken is not None and language_matches(spoken, request.language)
        )
        if transcript is None:
            transcript = _generated_transcript(
                request, audio=audio, recognizer=recognizer, cache=cache, stderr=stderr
            )
            # An explicit language of unknown standing never displaces the original.
            original = original or (
                spoken is None
                and cache.load_transcript(request.video_id, language=None) is None
            )
        cache.upsert_transcript(transcript, original=original, fetched_at=fetched_at)
    _emit_transcript(
        stdout,
        transcript=transcript,
        table=request.table,
        text=request.text,
        meta={
            "from_cache": cached is not None,
            "fetched_at": fetched_at,
            "truncated": False,
            "limit": request.limit,
        },
    )
    return 0


def _captions_transcript(
    request: VideoTranscriptRequest, *, captions: CaptionSource | None
) -> tuple[Transcript | None, str | None]:
    """The Transcript taken from Captions, and the video's original language.

    No Transcript means Speech Recognition should produce it instead.
    """
    source = captions if captions is not None else LiveCaptionSource()
    listing = source.list_captions(request.video_id)
    spoken = listing.original_language
    try:
        track = choose_track(listing, language=request.language)
    except NoCaptionsError:
        # Speech Recognition only yields the language that is spoken.
        if (
            request.language is not None
            and spoken is not None
            and not language_matches(spoken, request.language)
        ):
            raise
        return None, spoken
    return (
        Transcript(
            video_id=request.video_id,
            language=track.language,
            source=track.source,
            segments=source.fetch_segments(request.video_id, track),
        ),
        spoken,
    )


def _generated_transcript(
    request: VideoTranscriptRequest,
    *,
    audio: AudioSource | None,
    recognizer: SpeechRecognizer | None,
    cache: LibraryCache,
    stderr: TextIO,
) -> Transcript:
    transcript = generate_transcript(
        request.video_id,
        language=request.language,
        model=os.environ.get("YOUTUBE_WHISPER_MODEL") or DEFAULT_WHISPER_MODEL,
        audio=audio if audio is not None else LiveAudioSource(),
        recognizer=recognizer
        if recognizer is not None
        else LiveSpeechRecognizer(stderr),
        progress=lambda message: print(message, file=stderr, flush=True),
    )
    replaced = cache.load_transcript(request.video_id, language=transcript.language)
    if replaced is None:
        return transcript
    # One Transcript per language: take the place of the cached one.
    return replace(transcript, language=replaced.transcript.language)


def _emit_transcript(
    out: TextIO,
    *,
    transcript: Transcript,
    table: bool,
    text: bool,
    meta: dict[str, object],
) -> None:
    if table:
        out.write("start\ttext\n")
        for segment in transcript.segments:
            out.write(f"{_timestamp(segment.start)}\t{segment.text}\n")
        return
    if text:
        for segment in transcript.segments:
            out.write(f"{segment.text}\n")
        return
    json.dump(
        {
            "ok": True,
            "data": {
                "video_id": transcript.video_id,
                "language": transcript.language,
                "source": transcript.source,
                "segments": [
                    {"start": segment.start, "end": segment.end, "text": segment.text}
                    for segment in transcript.segments
                ],
            },
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _subs_list(
    request: SubsListRequest,
    *,
    youtube: YouTubeClient,
    cache: LibraryCache,
    stdout: TextIO,
) -> int:
    if not request.fresh:
        cached = cache.load_subscriptions()
        if cached is not None:
            subscriptions = cached.subscriptions[: request.limit]
            _emit_subscriptions(
                stdout,
                subscriptions=subscriptions,
                table=request.table,
                meta={
                    "from_cache": True,
                    "fetched_at": cached.fetched_at,
                    "truncated": cached.truncated
                    or len(cached.subscriptions) > request.limit,
                    "limit": request.limit,
                },
            )
            return 0
        if request.offline:
            raise CacheEmptyError("subscriptions cache is empty; run without --offline")

    fetched_at = _now_iso()
    result = youtube.list_subscriptions(limit=request.limit)
    cache.replace_subscriptions(
        result.subscriptions,
        fetched_at=fetched_at,
        truncated=result.truncated,
    )
    _emit_subscriptions(
        stdout,
        subscriptions=result.subscriptions,
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


def _emit_playlist(
    out: TextIO,
    *,
    playlist: Playlist,
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_table(out, (playlist,))
        return
    json.dump(
        {
            "ok": True,
            "data": _playlist_payload(playlist),
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _playlist_item_payload(item: PlaylistItem) -> dict[str, str | int | bool]:
    return {
        "playlist_id": item.playlist_id,
        "position": item.position,
        "video_id": item.video_id,
        "title": item.title,
        "channel_title": item.channel_title,
        "available": item.available,
        "url": item.url,
    }


def _emit_playlist_items(
    out: TextIO,
    *,
    items: tuple[PlaylistItem, ...],
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_items_table(out, items)
        return
    json.dump(
        {
            "ok": True,
            "data": {"items": [_playlist_item_payload(item) for item in items]},
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _liked_payload(item: LikedVideo) -> dict[str, str | int | bool | None]:
    return {
        "video_id": item.video_id,
        "title": item.title,
        "channel_title": item.channel_title,
        "available": item.available,
        "position": item.position,
        "url": item.url,
    }


def _emit_likes(
    out: TextIO,
    *,
    likes: tuple[LikedVideo, ...],
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_items_table(out, likes)
        return
    json.dump(
        {
            "ok": True,
            "data": {"likes": [_liked_payload(item) for item in likes]},
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _write_items_table(
    out: TextIO, items: tuple[PlaylistItem, ...] | tuple[LikedVideo, ...]
) -> None:
    out.write("video_id\ttitle\tchannel_title\tavailable\n")
    for item in items:
        out.write(
            f"{item.video_id}\t{item.title}\t{item.channel_title}\t"
            f"{_table_cell(item.available)}\n"
        )


def _subscription_payload(item: Subscription) -> dict[str, str]:
    return {
        "channel_id": item.channel_id,
        "title": item.title,
        "subscribed_at": item.subscribed_at,
        "url": item.url,
    }


def _emit_subscriptions(
    out: TextIO,
    *,
    subscriptions: tuple[Subscription, ...],
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_subscriptions_table(out, subscriptions)
        return
    json.dump(
        {
            "ok": True,
            "data": {
                "subscriptions": [
                    _subscription_payload(item) for item in subscriptions
                ]
            },
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _write_subscriptions_table(
    out: TextIO, subscriptions: tuple[Subscription, ...]
) -> None:
    out.write("channel_id\ttitle\tsubscribed_at\n")
    for item in subscriptions:
        out.write(f"{item.channel_id}\t{item.title}\t{item.subscribed_at}\n")


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


def _video_payload(video: Video) -> dict[str, str | int | bool]:
    return {
        "id": video.id,
        "title": video.title,
        "channel_id": video.channel_id,
        "channel_title": video.channel_title,
        "description": video.description,
        "duration_seconds": video.duration_seconds,
        "published_at": video.published_at,
        "privacy": video.privacy,
        "available": video.available,
        "url": video.url,
    }


def _emit_video(
    out: TextIO,
    *,
    video: Video,
    table: bool,
    meta: dict[str, object],
) -> None:
    if table:
        _write_video_table(out, video)
        return
    json.dump(
        {
            "ok": True,
            "data": _video_payload(video),
            "meta": meta,
        },
        out,
    )
    out.write("\n")


def _write_video_table(out: TextIO, video: Video) -> None:
    out.write("id\ttitle\tchannel_title\tduration_seconds\tpublished_at\n")
    out.write(
        f"{video.id}\t{video.title}\t{video.channel_title}\t"
        f"{video.duration_seconds}\t{video.published_at}\n"
    )


def _write_error(out: TextIO, *, code: str, message: str) -> None:
    json.dump({"ok": False, "error": {"code": code, "message": message}}, out)
    out.write("\n")
