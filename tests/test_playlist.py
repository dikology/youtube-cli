from youtube_cli.youtube import InMemoryYouTubeClient, Playlist, PlaylistItem


def test_playlist_show_returns_one_playlist(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {
        "id": "PLowned1",
        "title": "Watch later-ish",
        "item_count": 3,
        "privacy": "private",
        "channel_id": "UCmine",
        "url": "https://www.youtube.com/playlist?list=PLowned1",
    }
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_playlist_show_unknown_id_is_not_found(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "show", "PLmissing"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 5
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_second_playlist_show_is_cache_hit(invoke, credentials, youtube) -> None:
    first = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    second = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"] == first.json()["data"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]


def test_playlist_show_lazy_fill_does_not_fill_playlists_collection(
    invoke, credentials, youtube
) -> None:
    shown = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    listed = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert shown.exit_code == 0
    assert listed.json()["error"]["code"] == "cache_empty"


def test_playlist_show_offline_uses_cache_and_never_calls_adapter(
    invoke, credentials, youtube
) -> None:
    seeded = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "show", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in result.json()["meta"]
    assert result.json()["data"] == seeded.json()["data"]


def test_playlist_show_offline_on_miss_is_offline_miss(invoke, credentials, youtube) -> None:
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "show", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "offline_miss"
    assert body["error"]["message"]


def test_playlist_show_fresh_replaces_cached_playlist(invoke, credentials, youtube) -> None:
    first = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.playlists = (
        Playlist(
            id="PLowned1",
            title="Renamed",
            item_count=4,
            privacy="unlisted",
            channel_id="UCmine",
        ),
    )

    fresh = invoke(
        ["playlist", "show", "PLowned1", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.json()["data"]["title"] == "Watch later-ish"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["title"] == "Renamed"
    assert fresh.json()["data"]["item_count"] == 4
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["title"] == "Renamed"


def test_playlist_show_quota_exceeded_fails_without_partial_or_cache(
    invoke, credentials, youtube
) -> None:
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "show", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    offline = invoke(
        ["playlist", "show", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "offline_miss"


def test_playlist_show_table_prints_playlist_columns(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "show", "PLowned1", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["id", "title", "item_count", "privacy"]
    assert "PLowned1" in lines[1]
    assert "Watch later-ish" in lines[1]


def test_playlist_show_without_id_is_usage(invoke) -> None:
    result = invoke(["playlist", "show"])

    assert result.exit_code == 2
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "usage"


def test_playlist_show_offline_and_fresh_are_usage(invoke) -> None:
    result = invoke(["playlist", "show", "PLowned1", "--offline", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


OWNED_ITEMS = [
    {
        "playlist_id": "PLowned1",
        "position": 0,
        "video_id": "vidAvailable1",
        "title": "First video",
        "channel_title": "Fixture Channel",
        "available": True,
        "url": "https://www.youtube.com/watch?v=vidAvailable1",
    },
    {
        "playlist_id": "PLowned1",
        "position": 1,
        "video_id": "vidDeleted1",
        "title": "Deleted video",
        "channel_title": "",
        "available": False,
        "url": "https://www.youtube.com/watch?v=vidDeleted1",
    },
    {
        "playlist_id": "PLowned1",
        "position": 2,
        "video_id": "vidAvailable2",
        "title": "Third video",
        "channel_title": "Other Channel",
        "available": True,
        "url": "https://www.youtube.com/watch?v=vidAvailable2",
    },
]


def test_playlist_items_returns_items_including_unavailable(
    invoke, credentials, youtube
) -> None:
    result = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["items"] == OWNED_ITEMS
    assert body["data"]["items"][1]["available"] is False
    assert body["data"]["items"][1]["position"] == 1
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_playlist_items_unknown_id_is_not_found(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "items", "PLmissing"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 5
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_second_playlist_items_is_cache_hit(invoke, credentials, youtube) -> None:
    first = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    second = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"]["items"] == first.json()["data"]["items"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]


def test_playlist_items_lazy_fill_is_scoped_to_that_playlist(
    invoke, credentials, youtube
) -> None:
    youtube.playlists = youtube.playlists + (
        Playlist(
            id="PLowned2",
            title="Other list",
            item_count=1,
            privacy="public",
            channel_id="UCmine",
        ),
    )
    youtube.items_by_playlist = {
        **youtube.items_by_playlist,
        "PLowned2": (
            PlaylistItem(
                playlist_id="PLowned2",
                position=0,
                video_id="vidOther",
                title="Other video",
                channel_title="Fixture Channel",
                available=True,
            ),
        ),
    }

    filled = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    other = invoke(
        ["playlist", "items", "PLowned2", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )
    listed = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert filled.exit_code == 0
    assert other.json()["error"]["code"] == "offline_miss"
    assert listed.json()["error"]["code"] == "cache_empty"


def test_playlist_items_offline_uses_cache_and_never_calls_adapter(
    invoke, credentials, youtube
) -> None:
    seeded = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "items", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in result.json()["meta"]
    assert result.json()["data"]["items"] == seeded.json()["data"]["items"]


def test_playlist_items_offline_on_miss_is_offline_miss(
    invoke, credentials, youtube
) -> None:
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "items", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "offline_miss"
    assert body["error"]["message"]


def test_playlist_items_fresh_replaces_cached_items(invoke, credentials, youtube) -> None:
    first = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.items_by_playlist = {
        "PLowned1": (
            PlaylistItem(
                playlist_id="PLowned1",
                position=0,
                video_id="vidNew",
                title="Replacement video",
                channel_title="Fixture Channel",
                available=True,
            ),
        )
    }

    fresh = invoke(
        ["playlist", "items", "PLowned1", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert first.json()["data"]["items"][0]["video_id"] == "vidAvailable1"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["items"] == [
        {
            "playlist_id": "PLowned1",
            "position": 0,
            "video_id": "vidNew",
            "title": "Replacement video",
            "channel_title": "Fixture Channel",
            "available": True,
            "url": "https://www.youtube.com/watch?v=vidNew",
        }
    ]
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["items"][0]["video_id"] == "vidNew"


def test_playlist_items_limit_cap_sets_truncated_and_stays_ok(
    invoke, credentials
) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="Watch later-ish",
                item_count=501,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        items={
            "PLowned1": tuple(
                PlaylistItem(
                    playlist_id="PLowned1",
                    position=i,
                    video_id=f"vid{i:04d}",
                    title=f"Video {i}",
                    channel_title="Fixture Channel",
                    available=True,
                )
                for i in range(501)
            )
        },
    )

    result = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 500
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 500

    youtube.quota_exceeded = True
    cached = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert cached.exit_code == 0
    cached_body = cached.json()
    assert cached_body["ok"] is True
    assert cached_body["meta"]["from_cache"] is True
    assert cached_body["meta"]["truncated"] is True
    assert len(cached_body["data"]["items"]) == 500


def test_playlist_items_explicit_limit_truncates(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "items", "PLowned1", "--limit", "2"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert [item["video_id"] for item in body["data"]["items"]] == [
        "vidAvailable1",
        "vidDeleted1",
    ]
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 2
    assert body["data"]["items"][1]["available"] is False


def test_playlist_items_quota_exceeded_fails_without_partial_or_cache(
    invoke, credentials, youtube
) -> None:
    youtube.quota_exceeded = True

    result = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    offline = invoke(
        ["playlist", "items", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "offline_miss"


def test_playlist_items_table_prints_item_columns(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlist", "items", "PLowned1", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["video_id", "title", "channel_title", "available"]
    assert "vidAvailable1" in lines[1]
    assert "First video" in lines[1]
    assert "true" in lines[1]
    assert "vidDeleted1" in lines[2]
    assert "false" in lines[2]


def test_playlist_items_without_id_is_usage(invoke) -> None:
    result = invoke(["playlist", "items"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_playlist_items_offline_and_fresh_are_usage(invoke) -> None:
    result = invoke(["playlist", "items", "PLowned1", "--offline", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_playlist_items_fresh_quota_failure_keeps_existing_cache(
    invoke, credentials, youtube
) -> None:
    seeded = invoke(
        ["playlist", "items", "PLowned1"],
        credentials=credentials,
        youtube=youtube,
    )
    youtube.quota_exceeded = True

    fresh = invoke(
        ["playlist", "items", "PLowned1", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["playlist", "items", "PLowned1", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert fresh.exit_code == 4
    assert fresh.json()["error"]["code"] == "quota_exceeded"
    assert "data" not in fresh.json()
    assert cached.exit_code == 0
    assert cached.json()["data"]["items"] == seeded.json()["data"]["items"]
