from youtube_cli.youtube import (
    InMemoryYouTubeClient,
    LikedVideo,
    Playlist,
    PlaylistItem,
    QuotaExceededError,
    Subscription,
)


def _library_client() -> InMemoryYouTubeClient:
    return InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="Watch later-ish",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        items={
            "PLowned1": (
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=0,
                    video_id="vidAvailable1",
                    title="First video",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            )
        },
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        subscriptions=(
            Subscription(
                channel_id="UCsub1",
                title="Subscribed One",
                subscribed_at="2024-06-01T00:00:00Z",
            ),
        ),
    )


def test_sync_likes_replaces_likes_only(invoke, credentials) -> None:
    youtube = _library_client()
    playlists = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.likes = (
        LikedVideo(
            video_id="likedNew",
            title="Replacement like",
            channel_title="Like Channel",
            available=True,
            position=0,
        ),
    )
    youtube.playlists = (
        Playlist(
            id="PLnew",
            title="Should not be fetched",
            item_count=0,
            privacy="public",
            channel_id="UCmine",
        ),
    )

    synced = invoke(["sync", "likes"], credentials=credentials, youtube=youtube)
    cached_likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    cached_playlists = invoke(
        ["playlists", "list"], credentials=credentials, youtube=youtube
    )

    assert playlists.exit_code == 0
    assert likes.exit_code == 0
    assert synced.exit_code == 0
    body = synced.json()
    assert body["ok"] is True
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]
    assert cached_likes.json()["meta"]["from_cache"] is True
    assert cached_likes.json()["meta"]["fetched_at"] == body["meta"]["fetched_at"]
    assert cached_likes.json()["data"]["likes"][0]["video_id"] == "likedNew"
    assert cached_playlists.json()["meta"]["from_cache"] is True
    assert cached_playlists.json()["data"]["playlists"][0]["id"] == "PLowned1"
    assert cached_playlists.json()["data"]["playlists"][0]["id"] != "PLnew"


def test_sync_subs_replaces_subscriptions_only(invoke, credentials) -> None:
    youtube = _library_client()
    subs = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.subscriptions = (
        Subscription(
            channel_id="UCnew",
            title="Replacement channel",
            subscribed_at="2026-02-01T00:00:00Z",
        ),
    )
    youtube.likes = (
        LikedVideo(
            video_id="likedNew",
            title="Should not be fetched",
            channel_title="Like Channel",
            available=True,
            position=0,
        ),
    )

    synced = invoke(["sync", "subs"], credentials=credentials, youtube=youtube)
    cached_subs = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    cached_likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert subs.exit_code == 0
    assert likes.exit_code == 0
    assert synced.exit_code == 0
    body = synced.json()
    assert body["ok"] is True
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] == 1
    assert cached_subs.json()["meta"]["from_cache"] is True
    assert cached_subs.json()["meta"]["fetched_at"] == body["meta"]["fetched_at"]
    assert cached_subs.json()["data"]["subscriptions"][0]["channel_id"] == "UCnew"
    assert cached_likes.json()["meta"]["from_cache"] is True
    assert cached_likes.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"


def test_sync_playlists_replaces_metadata_not_items(invoke, credentials) -> None:
    youtube = _library_client()
    playlists = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    items = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )
    youtube.playlists = (
        Playlist(
            id="PLowned1",
            title="Renamed playlist",
            item_count=9,
            privacy="public",
            channel_id="UCmine",
        ),
    )
    youtube.items_by_playlist = {
        "PLowned1": (
            PlaylistItem(
                playlist_id="PLowned1",
                position=0,
                video_id="vidNew",
                title="Should not be fetched",
                channel_title="Fixture Channel",
                available=True,
            ),
        )
    }

    synced = invoke(["sync", "playlists"], credentials=credentials, youtube=youtube)
    cached_playlists = invoke(
        ["playlists", "list"], credentials=credentials, youtube=youtube
    )
    cached_items = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )

    assert playlists.exit_code == 0
    assert items.exit_code == 0
    assert synced.exit_code == 0
    body = synced.json()
    assert body["ok"] is True
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] == 1
    assert cached_playlists.json()["meta"]["from_cache"] is True
    assert cached_playlists.json()["meta"]["fetched_at"] == body["meta"]["fetched_at"]
    assert cached_playlists.json()["data"]["playlists"][0]["title"] == "Renamed playlist"
    assert cached_items.json()["meta"]["from_cache"] is True
    assert cached_items.json()["data"]["items"][0]["video_id"] == "vidAvailable1"


def test_sync_playlist_replaces_that_playlists_items_only(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="One",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
            Playlist(
                id="PLowned2",
                title="Two",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        items={
            "PLowned1": (
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=0,
                    video_id="vidA",
                    title="A",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
            "PLowned2": (
                PlaylistItem(
                    playlist_id="PLowned2",
                    position=0,
                    video_id="vidB",
                    title="B",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
        },
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
    )
    items1 = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )
    items2 = invoke(
        ["playlist", "items", "PLowned2"], credentials=credentials, youtube=youtube
    )
    likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.items_by_playlist = {
        "PLowned1": (
            PlaylistItem(
                playlist_id="PLowned1",
                position=0,
                video_id="vidNew",
                title="Replacement item",
                channel_title="Fixture Channel",
                available=True,
            ),
        ),
        "PLowned2": (
            PlaylistItem(
                playlist_id="PLowned2",
                position=0,
                video_id="vidShouldNotFetch",
                title="Should not be fetched",
                channel_title="Fixture Channel",
                available=True,
            ),
        ),
    }
    youtube.likes = (
        LikedVideo(
            video_id="likedNew",
            title="Should not be fetched",
            channel_title="Like Channel",
            available=True,
            position=0,
        ),
    )

    synced = invoke(
        ["sync", "playlist", "PLowned1"], credentials=credentials, youtube=youtube
    )
    cached1 = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )
    cached2 = invoke(
        ["playlist", "items", "PLowned2"], credentials=credentials, youtube=youtube
    )
    cached_likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert items1.exit_code == 0
    assert items2.exit_code == 0
    assert likes.exit_code == 0
    assert synced.exit_code == 0
    body = synced.json()
    assert body["ok"] is True
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] == 1
    assert cached1.json()["meta"]["from_cache"] is True
    assert cached1.json()["meta"]["fetched_at"] == body["meta"]["fetched_at"]
    assert cached1.json()["data"]["items"][0]["video_id"] == "vidNew"
    assert cached2.json()["meta"]["from_cache"] is True
    assert cached2.json()["data"]["items"][0]["video_id"] == "vidB"
    assert cached_likes.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"


def test_sync_replaces_full_library_snapshot(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="One",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
            Playlist(
                id="PLowned2",
                title="Two",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        items={
            "PLowned1": (
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=0,
                    video_id="vidA",
                    title="A",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
            "PLowned2": (
                PlaylistItem(
                    playlist_id="PLowned2",
                    position=0,
                    video_id="vidB",
                    title="B",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
        },
        likes=(
            LikedVideo(
                video_id="likedOld",
                title="Old like",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        subscriptions=(
            Subscription(
                channel_id="UCold",
                title="Old channel",
                subscribed_at="2024-01-01T00:00:00Z",
            ),
        ),
    )
    invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    invoke(["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube)
    invoke(["playlist", "items", "PLowned2"], credentials=credentials, youtube=youtube)
    invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.playlists = (
        Playlist(
            id="PLowned1",
            title="One refreshed",
            item_count=1,
            privacy="public",
            channel_id="UCmine",
        ),
        Playlist(
            id="PLowned3",
            title="Three",
            item_count=1,
            privacy="private",
            channel_id="UCmine",
        ),
    )
    youtube.items_by_playlist = {
        "PLowned1": (
            PlaylistItem(
                playlist_id="PLowned1",
                position=0,
                video_id="vidAnew",
                title="A new",
                channel_title="Fixture Channel",
                available=True,
            ),
        ),
        "PLowned3": (
            PlaylistItem(
                playlist_id="PLowned3",
                position=0,
                video_id="vidC",
                title="C",
                channel_title="Fixture Channel",
                available=True,
            ),
        ),
    }
    youtube.likes = (
        LikedVideo(
            video_id="likedNew",
            title="New like",
            channel_title="Like Channel",
            available=True,
            position=0,
        ),
    )
    youtube.subscriptions = (
        Subscription(
            channel_id="UCnew",
            title="New channel",
            subscribed_at="2026-02-01T00:00:00Z",
        ),
    )

    synced = invoke(["sync"], credentials=credentials, youtube=youtube)
    playlists = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    items1 = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )
    items3 = invoke(
        ["playlist", "items", "PLowned3"], credentials=credentials, youtube=youtube
    )
    likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    subs = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert synced.exit_code == 0
    body = synced.json()
    assert body["ok"] is True
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] >= 4
    fetched_at = body["meta"]["fetched_at"]
    assert playlists.json()["meta"]["from_cache"] is True
    assert playlists.json()["meta"]["fetched_at"] == fetched_at
    assert [p["id"] for p in playlists.json()["data"]["playlists"]] == [
        "PLowned1",
        "PLowned3",
    ]
    assert playlists.json()["data"]["playlists"][0]["title"] == "One refreshed"
    assert items1.json()["meta"]["from_cache"] is True
    assert items1.json()["meta"]["fetched_at"] == fetched_at
    assert items1.json()["data"]["items"][0]["video_id"] == "vidAnew"
    assert items3.json()["meta"]["from_cache"] is True
    assert items3.json()["data"]["items"][0]["video_id"] == "vidC"
    assert likes.json()["meta"]["from_cache"] is True
    assert likes.json()["meta"]["fetched_at"] == fetched_at
    assert likes.json()["data"]["likes"][0]["video_id"] == "likedNew"
    assert subs.json()["meta"]["from_cache"] is True
    assert subs.json()["meta"]["fetched_at"] == fetched_at
    assert subs.json()["data"]["subscriptions"][0]["channel_id"] == "UCnew"


class _QuotaOnLikes(InMemoryYouTubeClient):
    def list_likes(self, *, limit: int):
        raise QuotaExceededError("quota exceeded")


def test_sync_quota_failure_does_not_leave_half_written_library(
    invoke, credentials
) -> None:
    youtube = _library_client()
    playlists = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    likes = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    subs = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    failing = _QuotaOnLikes(
        playlists=(
            Playlist(
                id="PLnew",
                title="Should not persist",
                item_count=0,
                privacy="public",
                channel_id="UCmine",
            ),
        ),
        likes=youtube.likes,
        subscriptions=(
            Subscription(
                channel_id="UCshouldNotPersist",
                title="Should not persist",
                subscribed_at="2026-02-01T00:00:00Z",
            ),
        ),
    )

    synced = invoke(["sync"], credentials=credentials, youtube=failing)
    cached_playlists = invoke(
        ["playlists", "list", "--offline"], credentials=credentials, youtube=failing
    )
    cached_likes = invoke(
        ["likes", "list", "--offline"], credentials=credentials, youtube=failing
    )
    cached_subs = invoke(
        ["subs", "list", "--offline"], credentials=credentials, youtube=failing
    )

    assert playlists.exit_code == 0
    assert likes.exit_code == 0
    assert subs.exit_code == 0
    assert synced.exit_code == 4
    body = synced.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert cached_playlists.json()["data"]["playlists"][0]["id"] == "PLowned1"
    assert cached_likes.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"
    assert cached_subs.json()["data"]["subscriptions"][0]["channel_id"] == "UCsub1"


def test_sync_offline_is_usage(invoke, credentials) -> None:
    youtube = _library_client()

    result = invoke(
        ["sync", "--offline"], credentials=credentials, youtube=youtube
    )

    assert result.exit_code == 2
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "usage"
    assert body["error"]["message"]


def test_sync_likes_offline_is_usage(invoke, credentials) -> None:
    youtube = _library_client()

    result = invoke(
        ["sync", "likes", "--offline"], credentials=credentials, youtube=youtube
    )

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_sync_playlist_without_id_is_usage(invoke, credentials) -> None:
    result = invoke(["sync", "playlist"], credentials=credentials)

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_sync_unknown_subset_is_usage(invoke, credentials) -> None:
    result = invoke(["sync", "uploads"], credentials=credentials)

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_full_sync_drops_items_for_playlists_no_longer_owned(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="One",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
            Playlist(
                id="PLowned2",
                title="Two",
                item_count=1,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        items={
            "PLowned1": (
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=0,
                    video_id="vidA",
                    title="A",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
            "PLowned2": (
                PlaylistItem(
                    playlist_id="PLowned2",
                    position=0,
                    video_id="vidB",
                    title="B",
                    channel_title="Fixture Channel",
                    available=True,
                ),
            ),
        },
    )
    invoke(["playlist", "items", "PLowned2"], credentials=credentials, youtube=youtube)
    youtube.playlists = (
        Playlist(
            id="PLowned1",
            title="One",
            item_count=1,
            privacy="private",
            channel_id="UCmine",
        ),
    )
    youtube.items_by_playlist = {
        "PLowned1": youtube.items_by_playlist["PLowned1"],
    }

    synced = invoke(["sync"], credentials=credentials, youtube=youtube)
    removed = invoke(
        ["playlist", "items", "PLowned2", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert synced.exit_code == 0
    assert removed.exit_code == 1
    assert removed.json()["error"]["code"] == "offline_miss"


def test_sync_likes_quota_failure_keeps_existing_cache(invoke, credentials) -> None:
    youtube = _library_client()
    seeded = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    synced = invoke(["sync", "likes"], credentials=credentials, youtube=youtube)
    cached = invoke(
        ["likes", "list", "--offline"], credentials=credentials, youtube=youtube
    )

    assert seeded.exit_code == 0
    assert synced.exit_code == 4
    assert synced.json()["error"]["code"] == "quota_exceeded"
    assert "data" not in synced.json()
    assert cached.exit_code == 0
    assert cached.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"


def test_sync_likes_limit_truncates_the_replaced_collection(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
            LikedVideo(
                video_id="likedAvailable2",
                title="Second like",
                channel_title="Like Channel",
                available=True,
                position=1,
            ),
        )
    )

    synced = invoke(
        ["sync", "likes", "--limit", "1"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert synced.exit_code == 0
    body = synced.json()
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 1
    assert cached.json()["meta"]["from_cache"] is True
    assert [item["video_id"] for item in cached.json()["data"]["likes"]] == [
        "likedAvailable1"
    ]
    assert cached.json()["meta"]["truncated"] is True
