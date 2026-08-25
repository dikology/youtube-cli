from youtube_cli.youtube import (
    InMemoryYouTubeClient,
    LikedVideo,
    Playlist,
    PlaylistItem,
    Subscription,
)

SUBS = [
    {
        "channel_id": "UCsub1",
        "title": "Subscribed One",
        "subscribed_at": "2024-06-01T00:00:00Z",
        "url": "https://www.youtube.com/channel/UCsub1",
    },
    {
        "channel_id": "UCsub2",
        "title": "Subscribed Two",
        "subscribed_at": "2025-01-15T12:30:00Z",
        "url": "https://www.youtube.com/channel/UCsub2",
    },
]


def _library_client(
    *,
    likes: tuple[LikedVideo, ...] | None = None,
    subscriptions: tuple[Subscription, ...] | None = None,
    quota_exceeded: bool = False,
) -> InMemoryYouTubeClient:
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
        likes=likes
        if likes is not None
        else (
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        subscriptions=subscriptions
        if subscriptions is not None
        else (
            Subscription(
                channel_id="UCsub1",
                title="Subscribed One",
                subscribed_at="2024-06-01T00:00:00Z",
            ),
            Subscription(
                channel_id="UCsub2",
                title="Subscribed Two",
                subscribed_at="2025-01-15T12:30:00Z",
            ),
        ),
        quota_exceeded=quota_exceeded,
    )


def test_subs_list_returns_subscription_channels(invoke, credentials) -> None:
    youtube = _library_client()

    result = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["subscriptions"] == SUBS
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_second_subs_list_is_cache_hit(invoke, credentials) -> None:
    youtube = _library_client()
    first = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    second = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"]["subscriptions"] == first.json()["data"]["subscriptions"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]


def test_subs_list_does_not_fetch_uploads(invoke, credentials) -> None:
    youtube = _library_client()
    filled = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    items = invoke(
        ["playlist", "items", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )
    listed = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert filled.exit_code == 0
    assert items.json()["error"]["code"] == "offline_miss"
    assert listed.json()["error"]["code"] == "cache_empty"


def test_likes_list_does_not_fill_subs(invoke, credentials) -> None:
    youtube = _library_client()
    filled = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    subs = invoke(
        ["subs", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert filled.exit_code == 0
    assert filled.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"
    assert subs.json()["error"]["code"] == "cache_empty"


def test_subs_list_does_not_fill_likes(invoke, credentials) -> None:
    youtube = _library_client()
    filled = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    likes = invoke(
        ["likes", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert filled.exit_code == 0
    assert likes.json()["error"]["code"] == "cache_empty"


def test_fresh_snapshot_replaces_cached_subs(invoke, credentials) -> None:
    youtube = _library_client()
    first = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.subscriptions = (
        Subscription(
            channel_id="UCnew",
            title="Replacement channel",
            subscribed_at="2026-02-01T00:00:00Z",
        ),
    )

    fresh = invoke(
        ["subs", "list", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert first.json()["data"]["subscriptions"][0]["channel_id"] == "UCsub1"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["subscriptions"] == [
        {
            "channel_id": "UCnew",
            "title": "Replacement channel",
            "subscribed_at": "2026-02-01T00:00:00Z",
            "url": "https://www.youtube.com/channel/UCnew",
        }
    ]
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["subscriptions"][0]["channel_id"] == "UCnew"


def test_offline_uses_subs_cache_and_never_calls_adapter(invoke, credentials) -> None:
    youtube = _library_client()
    seeded = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    result = invoke(
        ["subs", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in result.json()["meta"]
    assert result.json()["data"]["subscriptions"] == seeded.json()["data"]["subscriptions"]


def test_offline_on_empty_subs_cache_is_cache_empty(invoke, credentials) -> None:
    youtube = _library_client(quota_exceeded=True)

    result = invoke(
        ["subs", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "cache_empty"
    assert body["error"]["message"]


def test_subs_explicit_limit_truncates(invoke, credentials) -> None:
    youtube = _library_client()

    result = invoke(
        ["subs", "list", "--limit", "1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert [item["channel_id"] for item in body["data"]["subscriptions"]] == ["UCsub1"]
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 1


def test_subs_limit_cap_sets_truncated_and_stays_ok(invoke, credentials) -> None:
    youtube = _library_client(
        subscriptions=tuple(
            Subscription(
                channel_id=f"UCsub{i:04d}",
                title=f"Channel {i}",
                subscribed_at="2024-06-01T00:00:00Z",
            )
            for i in range(501)
        )
    )

    result = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert len(body["data"]["subscriptions"]) == 500
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 500

    youtube.quota_exceeded = True
    cached = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    assert cached.exit_code == 0
    cached_body = cached.json()
    assert cached_body["ok"] is True
    assert cached_body["meta"]["from_cache"] is True
    assert cached_body["meta"]["truncated"] is True
    assert len(cached_body["data"]["subscriptions"]) == 500


def test_subs_quota_exceeded_fails_without_partial_list_or_cache(
    invoke, credentials
) -> None:
    youtube = _library_client(quota_exceeded=True)

    result = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    offline = invoke(
        ["subs", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "cache_empty"


def test_subs_table_prints_channel_columns(invoke, credentials) -> None:
    youtube = _library_client()

    result = invoke(
        ["subs", "list", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["channel_id", "title", "subscribed_at"]
    assert "UCsub1" in lines[1]
    assert "Subscribed One" in lines[1]
    assert "2024-06-01T00:00:00Z" in lines[1]


def test_subs_offline_and_fresh_are_usage(invoke) -> None:
    result = invoke(["subs", "list", "--offline", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_subs_list_with_id_is_usage(invoke) -> None:
    result = invoke(["subs", "list", "UCsub1"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_subs_fresh_quota_failure_keeps_existing_cache(invoke, credentials) -> None:
    youtube = _library_client()
    seeded = invoke(["subs", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    fresh = invoke(
        ["subs", "list", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["subs", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert fresh.exit_code == 4
    assert fresh.json()["error"]["code"] == "quota_exceeded"
    assert "data" not in fresh.json()
    assert cached.exit_code == 0
    assert cached.json()["data"]["subscriptions"] == seeded.json()["data"]["subscriptions"]


def test_cache_status_after_subs_list_shows_subscriptions_only(
    invoke, credentials
) -> None:
    youtube = _library_client()
    listed = invoke(["subs", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["cache", "status"], credentials=credentials, youtube=youtube)

    assert listed.exit_code == 0
    assert result.json()["data"]["collections"] == {
        "subscriptions": {
            "fetched_at": listed.json()["meta"]["fetched_at"],
            "count": 2,
        }
    }
