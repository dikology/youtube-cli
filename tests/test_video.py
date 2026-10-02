from youtube_cli.youtube import (
    InMemoryYouTubeClient,
    LikedVideo,
    Playlist,
    PlaylistItem,
    Video,
)

OUTSIDE = Video(
    id="vidOutside1",
    title="Not in any playlist",
    channel_id="UCother",
    channel_title="Other Channel",
    description="A long description for search later.",
    duration_seconds=125,
    published_at="2020-01-15T12:00:00Z",
    privacy="public",
    available=True,
)

OUTSIDE_PAYLOAD = {
    "id": "vidOutside1",
    "title": "Not in any playlist",
    "channel_id": "UCother",
    "channel_title": "Other Channel",
    "description": "A long description for search later.",
    "duration_seconds": 125,
    "published_at": "2020-01-15T12:00:00Z",
    "privacy": "public",
    "available": True,
    "url": "https://www.youtube.com/watch?v=vidOutside1",
}


def _video_client(
    *videos: Video,
    quota_exceeded: bool = False,
    network_error: bool = False,
) -> InMemoryYouTubeClient:
    return InMemoryYouTubeClient(
        videos=videos,
        quota_exceeded=quota_exceeded,
        network_error=network_error,
    )


def test_video_get_returns_hydrated_fields_for_any_visible_video(
    invoke, credentials
) -> None:
    youtube = _video_client(OUTSIDE)

    result = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == OUTSIDE_PAYLOAD
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]
    assert youtube.video_list_calls == [("vidOutside1",)]


def test_video_get_unknown_id_is_not_found(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE)

    result = invoke(
        ["video", "get", "vidMissing"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 5
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert youtube.video_list_calls == [("vidMissing",)]


def test_second_video_get_is_cache_hit(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE)
    first = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    second = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"] == first.json()["data"]
    assert body["data"]["description"] == "A long description for search later."
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]
    assert youtube.video_list_calls == [("vidOutside1",)]


def test_video_get_offline_uses_persisted_description_without_calling_adapter(
    invoke, credentials
) -> None:
    youtube = _video_client(OUTSIDE)
    seeded = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    result = invoke(
        ["video", "get", "vidOutside1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    body = result.json()
    assert body["meta"]["from_cache"] is True
    assert "quota_cost" not in body["meta"]
    assert body["data"]["description"] == "A long description for search later."
    assert body["data"] == seeded.json()["data"]
    assert youtube.video_list_calls == [("vidOutside1",)]


def test_video_get_offline_on_miss_is_offline_miss(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE, quota_exceeded=True)

    result = invoke(
        ["video", "get", "vidOutside1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "offline_miss"
    assert body["error"]["message"]
    assert youtube.video_list_calls == []


def test_video_get_fresh_replaces_cached_video(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE)
    first = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.videos["vidOutside1"] = Video(
        id="vidOutside1",
        title="Renamed outside video",
        channel_id="UCother",
        channel_title="Other Channel",
        description="Updated description.",
        duration_seconds=200,
        published_at="2021-02-16T12:00:00Z",
        privacy="unlisted",
        available=True,
    )

    fresh = invoke(
        ["video", "get", "vidOutside1", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.json()["data"]["title"] == "Not in any playlist"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["title"] == "Renamed outside video"
    assert fresh.json()["data"]["description"] == "Updated description."
    assert fresh.json()["data"]["duration_seconds"] == 200
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["description"] == "Updated description."
    assert youtube.video_list_calls == [("vidOutside1",), ("vidOutside1",)]


def test_video_get_quota_exceeded_fails_without_partial_or_cache(
    invoke, credentials
) -> None:
    youtube = _video_client(OUTSIDE, quota_exceeded=True)

    result = invoke(
        ["video", "get", "vidOutside1"],
        credentials=credentials,
        youtube=youtube,
    )
    offline = invoke(
        ["video", "get", "vidOutside1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "offline_miss"


def test_video_get_table_prints_video_columns(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE)

    result = invoke(
        ["video", "get", "vidOutside1", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == [
        "id",
        "title",
        "channel_title",
        "duration_seconds",
        "published_at",
    ]
    assert "vidOutside1" in lines[1]
    assert "Not in any playlist" in lines[1]
    assert "Other Channel" in lines[1]
    assert "125" in lines[1]
    assert "2020-01-15T12:00:00Z" in lines[1]


def test_video_get_without_id_is_usage(invoke) -> None:
    result = invoke(["video", "get"])

    assert result.exit_code == 2
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "usage"


def test_video_get_offline_and_fresh_are_usage(invoke) -> None:
    result = invoke(["video", "get", "vidOutside1", "--offline", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


FIRST = Video(
    id="vidAvailable1",
    title="First video",
    channel_id="UCmine",
    channel_title="Fixture Channel",
    description="First description.",
    duration_seconds=60,
    published_at="2019-06-01T00:00:00Z",
    privacy="public",
    available=True,
)
THIRD = Video(
    id="vidAvailable2",
    title="Third video",
    channel_id="UCother",
    channel_title="Other Channel",
    description="Third description.",
    duration_seconds=180,
    published_at="2019-07-01T00:00:00Z",
    privacy="unlisted",
    available=True,
)
LIKED_DETAIL = Video(
    id="likedAvailable1",
    title="Liked video",
    channel_id="UClike",
    channel_title="Like Channel",
    description="Liked description.",
    duration_seconds=45,
    published_at="2018-03-01T00:00:00Z",
    privacy="public",
    available=True,
)


def _owned_items_client(*videos: Video) -> InMemoryYouTubeClient:
    return InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="Watch later-ish",
                item_count=3,
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
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=1,
                    video_id="vidDeleted1",
                    title="Deleted video",
                    channel_title="",
                    available=False,
                ),
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=2,
                    video_id="vidAvailable2",
                    title="Third video",
                    channel_title="Other Channel",
                    available=True,
                ),
            )
        },
        videos=videos,
    )


def test_playlist_items_without_hydrate_stay_thin_and_do_not_call_videos_list(
    invoke, credentials
) -> None:
    youtube = _owned_items_client(FIRST, THIRD)

    result = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True
    offline = invoke(
        ["video", "get", "vidAvailable1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    item = result.json()["data"]["items"][0]
    assert "description" not in item
    assert "duration_seconds" not in item
    assert youtube.video_list_calls == []
    assert offline.json()["error"]["code"] == "offline_miss"


def test_playlist_items_hydrate_writes_videos_for_later_offline_get(
    invoke, credentials
) -> None:
    youtube = _owned_items_client(FIRST, THIRD)

    listed = invoke(
        ["playlist", "items", "PLowned1", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True
    first = invoke(
        ["video", "get", "vidAvailable1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )
    third = invoke(
        ["video", "get", "vidAvailable2", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert listed.exit_code == 0
    item = listed.json()["data"]["items"][0]
    assert "description" not in item
    assert listed.json()["meta"]["from_cache"] is False
    assert listed.json()["meta"]["quota_cost"] == 2
    assert youtube.video_list_calls == [
        ("vidAvailable1", "vidAvailable2")
    ]
    assert first.exit_code == 0
    assert first.json()["data"]["description"] == "First description."
    assert first.json()["data"]["duration_seconds"] == 60
    assert third.exit_code == 0
    assert third.json()["data"]["description"] == "Third description."


def test_likes_list_without_hydrate_does_not_call_videos_list(
    invoke, credentials
) -> None:
    youtube = InMemoryYouTubeClient(
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        videos=(LIKED_DETAIL,),
    )

    result = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True
    offline = invoke(
        ["video", "get", "likedAvailable1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    assert "description" not in result.json()["data"]["likes"][0]
    assert youtube.video_list_calls == []
    assert offline.json()["error"]["code"] == "offline_miss"


def test_likes_list_hydrate_writes_videos_for_later_offline_get(
    invoke, credentials
) -> None:
    youtube = InMemoryYouTubeClient(
        likes=(
            LikedVideo(
                video_id="likedAvailable1",
                title="Liked video",
                channel_title="Like Channel",
                available=True,
                position=0,
            ),
        ),
        videos=(LIKED_DETAIL,),
    )

    listed = invoke(
        ["likes", "list", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True
    got = invoke(
        ["video", "get", "likedAvailable1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert listed.exit_code == 0
    assert "description" not in listed.json()["data"]["likes"][0]
    assert listed.json()["meta"]["quota_cost"] == 2
    assert youtube.video_list_calls == [("likedAvailable1",)]
    assert got.exit_code == 0
    assert got.json()["data"]["description"] == "Liked description."


def test_playlist_items_hydrate_on_cached_items_fetches_missing_videos(
    invoke, credentials
) -> None:
    youtube = _owned_items_client(FIRST, THIRD)
    seeded = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    listed = invoke(
        ["playlist", "items", "PLowned1", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True
    got = invoke(
        ["video", "get", "vidAvailable1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert listed.exit_code == 0
    assert listed.json()["meta"]["quota_cost"] == 1
    assert youtube.video_list_calls == [
        ("vidAvailable1", "vidAvailable2")
    ]
    assert got.exit_code == 0
    assert got.json()["data"]["description"] == "First description."


def test_playlist_items_hydrate_skips_videos_already_in_cache(
    invoke, credentials
) -> None:
    youtube = _owned_items_client(FIRST, THIRD)
    first = invoke(
        ["playlist", "items", "PLowned1", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    second = invoke(
        ["playlist", "items", "PLowned1", "--hydrate"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in second.json()["meta"]
    assert youtube.video_list_calls == [
        ("vidAvailable1", "vidAvailable2")
    ]


def test_playlist_items_offline_hydrate_on_missing_videos_is_offline_miss(
    invoke, credentials
) -> None:
    youtube = _owned_items_client(FIRST, THIRD)
    seeded = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    listed = invoke(
        ["playlist", "items", "PLowned1", "--hydrate", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert listed.exit_code == 1
    assert listed.json()["error"]["code"] == "offline_miss"
    assert youtube.video_list_calls == []


def test_video_get_accepts_watch_and_short_urls(invoke, credentials) -> None:
    youtube = _video_client(OUTSIDE)

    by_watch = invoke(
        ["video", "get", "https://www.youtube.com/watch?v=vidOutside1&list=PLabc"],
        credentials=credentials,
        youtube=youtube,
    )
    by_short = invoke(
        ["video", "get", "https://youtu.be/vidOutside1", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )

    assert by_watch.exit_code == 0
    assert by_watch.json()["data"] == OUTSIDE_PAYLOAD
    assert by_short.json()["data"] == OUTSIDE_PAYLOAD
    assert youtube.video_list_calls == [("vidOutside1",), ("vidOutside1",)]
