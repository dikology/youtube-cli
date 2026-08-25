from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

import httpx

YOUTUBE_PLAYLISTS_URL = "https://www.googleapis.com/youtube/v3/playlists"
YOUTUBE_PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PAGE_SIZE = 50
UNAVAILABLE_TITLES = frozenset({"Deleted video", "Private video"})


@dataclass(frozen=True)
class Channel:
    id: str
    title: str


@dataclass(frozen=True)
class Playlist:
    id: str
    title: str
    item_count: int
    privacy: str
    channel_id: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.id}"


@dataclass(frozen=True)
class PlaylistItem:
    playlist_id: str
    position: int
    video_id: str
    title: str
    channel_title: str
    available: bool

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class PlaylistListResult:
    playlists: tuple[Playlist, ...]
    quota_cost: int
    truncated: bool


@dataclass(frozen=True)
class PlaylistGetResult:
    playlist: Playlist
    quota_cost: int


@dataclass(frozen=True)
class PlaylistItemListResult:
    items: tuple[PlaylistItem, ...]
    quota_cost: int
    truncated: bool


class YouTubeClient(Protocol):
    def list_playlists(self, *, limit: int) -> PlaylistListResult: ...

    def get_playlist(self, playlist_id: str) -> PlaylistGetResult: ...

    def list_playlist_items(
        self, playlist_id: str, *, limit: int
    ) -> PlaylistItemListResult: ...

    def get_mine_channel(self) -> Channel: ...


class QuotaExceededError(Exception):
    pass


class NetworkError(Exception):
    pass


class YouTubeApiError(Exception):
    pass


class UnauthorizedError(YouTubeApiError):
    pass


class NotFoundError(Exception):
    pass


class InMemoryYouTubeClient:
    def __init__(
        self,
        playlists: tuple[Playlist, ...] = (),
        *,
        items: dict[str, tuple[PlaylistItem, ...]] | None = None,
        channel: Channel | None = None,
        quota_exceeded: bool = False,
        network_error: bool = False,
        unauthorized: bool = False,
    ) -> None:
        self.playlists = playlists
        self.items_by_playlist = items or {}
        self.channel = channel or Channel(id="UCmine", title="Fixture Channel")
        self.quota_exceeded = quota_exceeded
        self.network_error = network_error
        self.unauthorized = unauthorized

    def get_mine_channel(self) -> Channel:
        if self.network_error:
            raise NetworkError("network failure")
        if self.quota_exceeded:
            raise QuotaExceededError("quota exceeded")
        if self.unauthorized:
            raise UnauthorizedError("access token rejected")
        return self.channel

    def get_playlist(self, playlist_id: str) -> PlaylistGetResult:
        if self.network_error:
            raise NetworkError("network failure")
        if self.quota_exceeded:
            raise QuotaExceededError("quota exceeded")
        for playlist in self.playlists:
            if playlist.id == playlist_id:
                return PlaylistGetResult(playlist=playlist, quota_cost=1)
        raise NotFoundError(f"playlist {playlist_id} not found")

    def list_playlist_items(
        self, playlist_id: str, *, limit: int
    ) -> PlaylistItemListResult:
        if self.network_error:
            raise NetworkError("network failure")
        if self.quota_exceeded:
            raise QuotaExceededError("quota exceeded")
        if playlist_id in self.items_by_playlist:
            items = self.items_by_playlist[playlist_id]
        elif any(playlist.id == playlist_id for playlist in self.playlists):
            items = ()
        else:
            raise NotFoundError(f"playlist {playlist_id} not found")
        sliced = items[:limit]
        return PlaylistItemListResult(
            items=sliced,
            quota_cost=_page_cost(len(sliced)),
            truncated=len(items) > limit,
        )

    def list_playlists(self, *, limit: int) -> PlaylistListResult:
        if self.network_error:
            raise NetworkError("network failure")
        if self.quota_exceeded:
            raise QuotaExceededError("quota exceeded")
        items = self.playlists[:limit]
        return PlaylistListResult(
            playlists=items,
            quota_cost=_page_cost(len(items)),
            truncated=len(self.playlists) > limit,
        )


class LiveYouTubeClient:
    def __init__(
        self,
        access_token: str,
        *,
        http: httpx.Client | None = None,
    ) -> None:
        self._access_token = access_token
        self._http = http or httpx.Client(timeout=30.0)

    def get_mine_channel(self) -> Channel:
        try:
            response = self._http.get(
                YOUTUBE_CHANNELS_URL,
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.RequestError as exc:
            raise NetworkError("network failure") from exc
        _raise_for_youtube(response)
        payload = _object_map(response.json())
        items = _object_list(payload.get("items"))
        if not items:
            raise YouTubeApiError("YouTube API returned no channel")
        item = _object_map(items[0])
        snippet = _object_map(item.get("snippet"))
        channel_id = item.get("id")
        if not isinstance(channel_id, str):
            raise YouTubeApiError("YouTube API returned no channel")
        return Channel(id=channel_id, title=_as_str(snippet.get("title")))

    def get_playlist(self, playlist_id: str) -> PlaylistGetResult:
        try:
            response = self._http.get(
                YOUTUBE_PLAYLISTS_URL,
                params={
                    "part": "snippet,contentDetails,status",
                    "id": playlist_id,
                    "maxResults": 1,
                },
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.RequestError as exc:
            raise NetworkError("network failure") from exc
        _raise_for_youtube(response, forbidden_is_not_found=True)
        payload = _object_map(response.json())
        playlists = _playlists_from_items(payload.get("items"))
        if not playlists:
            raise NotFoundError(f"playlist {playlist_id} not found")
        return PlaylistGetResult(playlist=playlists[0], quota_cost=1)

    def list_playlist_items(
        self, playlist_id: str, *, limit: int
    ) -> PlaylistItemListResult:
        items: list[PlaylistItem] = []
        quota_cost = 0
        page_token: str | None = None
        truncated = False
        while len(items) < limit:
            try:
                response = self._http.get(
                    YOUTUBE_PLAYLIST_ITEMS_URL,
                    params=_playlist_items_params(
                        playlist_id=playlist_id,
                        limit=limit,
                        already_fetched=len(items),
                        page_token=page_token,
                    ),
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
            except httpx.RequestError as exc:
                raise NetworkError("network failure") from exc
            quota_cost += 1
            _raise_for_youtube(response, forbidden_is_not_found=True)
            payload = _object_map(response.json())
            items.extend(_playlist_items_from_payload(payload, playlist_id=playlist_id))
            next_page = payload.get("nextPageToken")
            next_token = next_page if isinstance(next_page, str) else None
            if len(items) >= limit:
                truncated = len(items) > limit or bool(next_token)
                items = items[:limit]
                break
            if not next_token:
                break
            page_token = next_token
        return PlaylistItemListResult(
            items=tuple(items),
            quota_cost=quota_cost,
            truncated=truncated,
        )

    def list_playlists(self, *, limit: int) -> PlaylistListResult:
        playlists: list[Playlist] = []
        quota_cost = 0
        page_token: str | None = None
        truncated = False
        while len(playlists) < limit:
            try:
                response = self._http.get(
                    YOUTUBE_PLAYLISTS_URL,
                    params=_playlists_params(
                        limit=limit,
                        already_fetched=len(playlists),
                        page_token=page_token,
                    ),
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
            except httpx.RequestError as exc:
                raise NetworkError("network failure") from exc
            quota_cost += 1
            _raise_for_youtube(response)
            payload = _object_map(response.json())
            playlists.extend(_playlists_from_items(payload.get("items")))
            next_page = payload.get("nextPageToken")
            next_token = next_page if isinstance(next_page, str) else None
            if len(playlists) >= limit:
                truncated = len(playlists) > limit or bool(next_token)
                playlists = playlists[:limit]
                break
            if not next_token:
                break
            page_token = next_token
        return PlaylistListResult(
            playlists=tuple(playlists),
            quota_cost=quota_cost,
            truncated=truncated,
        )


def _playlists_params(
    *,
    limit: int,
    already_fetched: int,
    page_token: str | None,
) -> dict[str, str | int]:
    remaining = max(1, min(PAGE_SIZE, limit - already_fetched))
    params: dict[str, str | int] = {
        "part": "snippet,contentDetails,status",
        "mine": "true",
        "maxResults": remaining,
    }
    if page_token:
        params["pageToken"] = page_token
    return params


def _playlist_items_params(
    *,
    playlist_id: str,
    limit: int,
    already_fetched: int,
    page_token: str | None,
) -> dict[str, str | int]:
    remaining = max(1, min(PAGE_SIZE, limit - already_fetched))
    params: dict[str, str | int] = {
        "part": "snippet,contentDetails,status",
        "playlistId": playlist_id,
        "maxResults": remaining,
    }
    if page_token:
        params["pageToken"] = page_token
    return params


def _playlists_from_items(items: object) -> list[Playlist]:
    playlists: list[Playlist] = []
    for item in _object_list(items):
        typed_item = _object_map(item)
        if not typed_item:
            continue
        snippet = _object_map(typed_item.get("snippet"))
        content = _object_map(typed_item.get("contentDetails"))
        status = _object_map(typed_item.get("status"))
        playlist_id = typed_item.get("id")
        if not isinstance(playlist_id, str):
            continue
        playlists.append(
            Playlist(
                id=playlist_id,
                title=_as_str(snippet.get("title")),
                item_count=_as_int(content.get("itemCount")),
                privacy=_as_str(status.get("privacyStatus"), "private"),
                channel_id=_as_str(snippet.get("channelId")),
            )
        )
    return playlists


def _playlist_items_from_payload(
    payload: dict[str, object], *, playlist_id: str
) -> list[PlaylistItem]:
    items: list[PlaylistItem] = []
    for item in _object_list(payload.get("items")):
        typed_item = _object_map(item)
        if not typed_item:
            continue
        snippet = _object_map(typed_item.get("snippet"))
        content = _object_map(typed_item.get("contentDetails"))
        resource = _object_map(snippet.get("resourceId"))
        video_id = _as_str(content.get("videoId")) or _as_str(resource.get("videoId"))
        title = _as_str(snippet.get("title"))
        channel_title = _as_str(snippet.get("videoOwnerChannelTitle"))
        items.append(
            PlaylistItem(
                playlist_id=_as_str(snippet.get("playlistId"), playlist_id),
                position=_as_int(snippet.get("position")),
                video_id=video_id,
                title=title,
                channel_title=channel_title,
                available=bool(video_id) and title not in UNAVAILABLE_TITLES,
            )
        )
    return items


def _raise_for_youtube(
    response: httpx.Response, *, forbidden_is_not_found: bool = False
) -> None:
    if response.status_code == 401:
        raise UnauthorizedError("access token rejected")
    if response.status_code == 404:
        raise NotFoundError("not found")
    if response.status_code == 403 and _is_quota_error(response):
        raise QuotaExceededError("YouTube API quota exceeded")
    if (
        forbidden_is_not_found
        and response.status_code == 403
        and _is_not_found_error(response)
    ):
        raise NotFoundError("not found")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise YouTubeApiError(f"YouTube API returned HTTP {response.status_code}") from exc


def _is_quota_error(response: httpx.Response) -> bool:
    reasons = _youtube_error_reasons(response)
    return "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons


def _is_not_found_error(response: httpx.Response) -> bool:
    reasons = _youtube_error_reasons(response)
    return any(
        reason in {"playlistNotFound", "playlistItemsNotAccessible", "notFound"}
        for reason in reasons
    )


def _youtube_error_reasons(response: httpx.Response) -> list[str]:
    try:
        payload = response.json()
    except ValueError:
        return []
    payload_map = _object_map(payload)
    error = _object_map(payload_map.get("error"))
    reasons: list[str] = []
    for item in _object_list(error.get("errors")):
        reason = _object_map(item).get("reason")
        if isinstance(reason, str):
            reasons.append(reason)
    return reasons


def _object_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    typed = cast(dict[object, object], value)
    return {str(key): item for key, item in typed.items()}


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) and value else default


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _page_cost(item_count: int) -> int:
    if item_count == 0:
        return 1
    return (item_count + 49) // 50
