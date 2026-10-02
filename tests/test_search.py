import sqlite3

from youtube_cli.youtube import (
    InMemoryYouTubeClient,
    LikedVideo,
    Playlist,
    PlaylistItem,
    Subscription,
    Video,
)

FIRST = Video(
    id="vidAvailable1",
    title="First video",
    channel_id="UCmine",
    channel_title="Fixture Channel",
    description="Notes about sourdough starters.",
    duration_seconds=60,
    published_at="2019-06-01T00:00:00Z",
    privacy="public",
    available=True,
)

FIRST_ITEM_PAYLOAD = {
    "playlist_id": "PLowned1",
    "position": 0,
    "video_id": "vidAvailable1",
    "title": "First video",
    "channel_title": "Fixture Channel",
    "available": True,
    "url": "https://www.youtube.com/watch?v=vidAvailable1",
}

FIRST_VIDEO_PAYLOAD = {
    "id": "vidAvailable1",
    "title": "First video",
    "channel_id": "UCmine",
    "channel_title": "Fixture Channel",
    "description": "Notes about sourdough starters.",
    "duration_seconds": 60,
    "published_at": "2019-06-01T00:00:00Z",
    "privacy": "public",
    "available": True,
    "url": "https://www.youtube.com/watch?v=vidAvailable1",
}


def _library_client() -> InMemoryYouTubeClient:
    return InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="Baking fixtures",
                item_count=2,
                privacy="private",
                channel_id="UCmine",
            ),
            Playlist(
                id="PLowned2",
                title="Music",
                item_count=0,
                privacy="public",
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
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=1,
                    video_id="vidAvailable2",
                    title="Third video",
                    channel_title="Other Channel",
                    available=True,
                ),
            )
        },
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked clip",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        subscriptions=(
            Subscription(
                channel_id="UCsub1",
                title="Fixture Subscriptions",
                subscribed_at="2020-01-01T00:00:00Z",
            ),
            Subscription(
                channel_id="UCsub2",
                title="Кухня",
                subscribed_at="2021-01-01T00:00:00Z",
            ),
        ),
        videos=(FIRST,),
    )


def _synced(invoke, credentials) -> InMemoryYouTubeClient:
    youtube = _library_client()
    synced = invoke(["sync"], credentials=credentials, youtube=youtube)
    assert synced.exit_code == 0
    youtube.quota_exceeded = True
    return youtube


def test_search_matches_title_case_insensitively_across_types(
    invoke, credentials
) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "FIXTURE"], youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["hits"] == [
        {
            "type": "playlist",
            "id": "PLowned1",
            "title": "Baking fixtures",
            "item_count": 2,
            "privacy": "private",
            "channel_id": "UCmine",
            "url": "https://www.youtube.com/playlist?list=PLowned1",
        },
        {"type": "video", **FIRST_ITEM_PAYLOAD},
        {
            "type": "channel",
            "channel_id": "UCsub1",
            "title": "Fixture Subscriptions",
            "subscribed_at": "2020-01-01T00:00:00Z",
            "url": "https://www.youtube.com/channel/UCsub1",
        },
    ]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]
    assert youtube.video_list_calls == []


def test_search_matches_channel_title_and_liked_videos(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "like channel"], youtube=youtube)

    assert result.exit_code == 0
    assert result.json()["data"]["hits"] == [
        {
            "type": "video",
            "video_id": "likedAvailable1",
            "title": "Liked clip",
            "channel_title": "Like Channel",
            "available": True,
            "position": 0,
            "url": "https://www.youtube.com/watch?v=likedAvailable1",
        }
    ]


def test_search_is_case_insensitive_for_non_ascii_titles(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "кухня"], youtube=youtube)

    assert result.exit_code == 0
    hits = result.json()["data"]["hits"]
    assert [hit["channel_id"] for hit in hits] == ["UCsub2"]


def test_search_type_narrows_hits(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    playlists = invoke(["search", "fixture", "--type", "playlist"], youtube=youtube)
    videos = invoke(["search", "fixture", "--type", "video"], youtube=youtube)
    channels = invoke(["search", "fixture", "--type", "channel"], youtube=youtube)

    assert [hit["type"] for hit in playlists.json()["data"]["hits"]] == ["playlist"]
    assert [hit["type"] for hit in videos.json()["data"]["hits"]] == ["video"]
    assert [hit["type"] for hit in channels.json()["data"]["hits"]] == ["channel"]
    assert playlists.json()["data"]["hits"][0]["id"] == "PLowned1"
    assert videos.json()["data"]["hits"][0]["video_id"] == "vidAvailable1"
    assert channels.json()["data"]["hits"][0]["channel_id"] == "UCsub1"


def test_search_unknown_type_is_usage(invoke) -> None:
    result = invoke(["search", "fixture", "--type", "comment"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_search_matches_description_only_after_hydrate(invoke, credentials) -> None:
    youtube = _library_client()
    listed = invoke(
        ["playlist", "items", "PLowned1"], credentials=credentials, youtube=youtube
    )

    before = invoke(["search", "sourdough"], youtube=youtube)
    hydrated = invoke(
        ["playlist", "items", "PLowned1", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True
    after = invoke(["search", "SOURDOUGH"], youtube=youtube)

    assert listed.exit_code == 0
    assert before.exit_code == 0
    assert before.json()["data"]["hits"] == []
    assert hydrated.exit_code == 0
    assert after.exit_code == 0
    assert after.json()["data"]["hits"] == [{"type": "video", **FIRST_VIDEO_PAYLOAD}]


def test_search_returns_one_hit_per_video(invoke, credentials) -> None:
    youtube = _library_client()
    youtube.likes = (
        LikedVideo(
            video_id="vidAvailable1",
            title="First video",
            channel_title="Fixture Channel",
            available=True,
            position=0,
        ),
    )
    synced = invoke(["sync"], credentials=credentials, youtube=youtube)

    result = invoke(["search", "first video"], youtube=youtube)

    assert synced.exit_code == 0
    assert result.json()["data"]["hits"] == [{"type": "video", **FIRST_ITEM_PAYLOAD}]


def test_search_finds_video_cached_by_video_get(invoke, credentials) -> None:
    youtube = _library_client()
    got = invoke(
        ["video", "get", "vidAvailable1"], credentials=credentials, youtube=youtube
    )
    youtube.quota_exceeded = True

    result = invoke(["search", "starters"], youtube=youtube)

    assert got.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["data"]["hits"] == [{"type": "video", **FIRST_VIDEO_PAYLOAD}]


def test_search_on_empty_cache_is_cache_empty_without_calling_adapter(
    invoke, credentials, cache_dir
) -> None:
    youtube = _library_client()

    result = invoke(["search", "fixture"], credentials=credentials, youtube=youtube)
    created_cache_file = (cache_dir / "library.sqlite").exists()
    listed = invoke(
        ["playlists", "list", "--offline"], credentials=credentials, youtube=youtube
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "cache_empty"
    assert body["error"]["message"]
    assert not created_cache_file
    assert listed.json()["error"]["code"] == "cache_empty"
    assert youtube.video_list_calls == []


def test_search_after_cache_clear_is_cache_empty(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)
    cleared = invoke(["cache", "clear"])
    # A failed lazy-fill creates the SQLite file but caches nothing.
    failed = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["search", "fixture"], youtube=youtube)

    assert cleared.exit_code == 0
    assert failed.exit_code == 4
    assert result.exit_code == 1
    assert result.json()["error"]["code"] == "cache_empty"


def test_search_with_no_matches_is_ok_with_empty_hits(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "nothing-matches-this"], youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["hits"] == []
    assert body["meta"]["truncated"] is False


def test_search_does_not_need_credentials_or_write_the_cache(
    invoke, credentials, cache_dir
) -> None:
    youtube = _synced(invoke, credentials)
    before = _dump(cache_dir)

    result = invoke(["search", "fixture", "--offline"])

    assert result.exit_code == 0
    assert len(result.json()["data"]["hits"]) == 3
    assert _dump(cache_dir) == before
    assert youtube.video_list_calls == []


def test_search_limit_truncates_hits(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "fixture", "--limit", "2"], youtube=youtube)
    exact = invoke(["search", "fixture", "--limit", "3"], youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert [hit["type"] for hit in body["data"]["hits"]] == ["playlist", "video"]
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 2
    assert len(exact.json()["data"]["hits"]) == 3
    assert exact.json()["meta"]["truncated"] is False


def test_search_reports_truncated_when_a_searched_collection_was_truncated(
    invoke, credentials
) -> None:
    youtube = _library_client()
    listed = invoke(
        ["subs", "list", "--limit", "1"], credentials=credentials, youtube=youtube
    )
    synced = invoke(["sync", "playlists"], credentials=credentials, youtube=youtube)

    channels = invoke(["search", "fixture", "--type", "channel"], youtube=youtube)
    playlists = invoke(["search", "fixture", "--type", "playlist"], youtube=youtube)

    assert listed.json()["meta"]["truncated"] is True
    assert synced.exit_code == 0
    assert len(channels.json()["data"]["hits"]) == 1
    assert channels.json()["meta"]["truncated"] is True
    assert playlists.json()["meta"]["truncated"] is False


def test_search_table_prints_type_id_title(invoke, credentials) -> None:
    youtube = _synced(invoke, credentials)

    result = invoke(["search", "fixture", "--table"], youtube=youtube)

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines == [
        "type\tid\ttitle",
        "playlist\tPLowned1\tBaking fixtures",
        "video\tvidAvailable1\tFirst video",
        "channel\tUCsub1\tFixture Subscriptions",
    ]


def test_search_without_query_is_usage(invoke) -> None:
    result = invoke(["search"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_search_with_unquoted_multi_word_query_is_usage(invoke) -> None:
    result = invoke(["search", "first", "video"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_search_fresh_is_usage(invoke) -> None:
    result = invoke(["search", "fixture", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_type_on_other_commands_is_usage(invoke) -> None:
    result = invoke(["playlists", "list", "--type", "playlist"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def _dump(cache_dir) -> list[str]:
    conn = sqlite3.connect(cache_dir / "library.sqlite")
    try:
        return list(conn.iterdump())
    finally:
        conn.close()
