from youtube_cli.youtube import InMemoryYouTubeClient, LikedVideo

LIKED = [
    {
        "video_id": "likedAvailable1",
        "title": "Liked video",
        "channel_title": "Like Channel",
        "available": True,
        "position": 0,
        "url": "https://www.youtube.com/watch?v=likedAvailable1",
    },
    {
        "video_id": "likedDeleted1",
        "title": "Deleted video",
        "channel_title": "",
        "available": False,
        "position": 1,
        "url": "https://www.youtube.com/watch?v=likedDeleted1",
    },
]


def _likes_client(
    likes: tuple[LikedVideo, ...] | None = None,
    *,
    quota_exceeded: bool = False,
    network_error: bool = False,
) -> InMemoryYouTubeClient:
    return InMemoryYouTubeClient(
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
            LikedVideo(
                video_id="likedDeleted1",
                title="Deleted video",
                channel_title="",
                available=False,
                position=1,
            ),
        ),
        quota_exceeded=quota_exceeded,
        network_error=network_error,
    )


def test_likes_list_returns_liked_videos(invoke, credentials) -> None:
    youtube = _likes_client()

    result = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["likes"] == LIKED
    assert "LL" not in result.stdout
    assert all("playlist_id" not in item for item in body["data"]["likes"])
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_second_likes_list_is_cache_hit(invoke, credentials) -> None:
    youtube = _likes_client()
    first = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    second = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"]["likes"] == first.json()["data"]["likes"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]


def test_likes_list_lazy_fill_does_not_fill_playlists(invoke, credentials) -> None:
    youtube = _likes_client()
    filled = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    listed = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert filled.exit_code == 0
    assert listed.json()["error"]["code"] == "cache_empty"


def test_cache_status_after_likes_list_shows_likes_only(
    invoke, credentials, cache_dir
) -> None:
    youtube = _likes_client()
    listed = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["cache", "status"], credentials=credentials, youtube=youtube)

    assert listed.exit_code == 0
    assert result.exit_code == 0
    body = result.json()
    assert body["data"]["collections"] == {
        "likes": {
            "fetched_at": listed.json()["meta"]["fetched_at"],
            "count": 2,
        }
    }


def test_fresh_snapshot_replaces_cached_likes(invoke, credentials) -> None:
    youtube = _likes_client()
    first = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.likes = (
        LikedVideo(
            video_id="likedNew",
            title="Replacement like",
            channel_title="Like Channel",
            available=True,
            position=0,
        ),
    )

    fresh = invoke(
        ["likes", "list", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert first.json()["data"]["likes"][0]["video_id"] == "likedAvailable1"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["likes"] == [
        {
            "video_id": "likedNew",
            "title": "Replacement like",
            "channel_title": "Like Channel",
            "available": True,
            "position": 0,
            "url": "https://www.youtube.com/watch?v=likedNew",
        }
    ]
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["likes"][0]["video_id"] == "likedNew"


def test_offline_uses_likes_cache_and_never_calls_adapter(invoke, credentials) -> None:
    youtube = _likes_client()
    seeded = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    result = invoke(
        ["likes", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in result.json()["meta"]
    assert result.json()["data"]["likes"] == seeded.json()["data"]["likes"]


def test_offline_on_empty_likes_cache_is_cache_empty(invoke, credentials) -> None:
    youtube = _likes_client(quota_exceeded=True)

    result = invoke(
        ["likes", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "cache_empty"
    assert body["error"]["message"]


def test_likes_explicit_limit_truncates(invoke, credentials) -> None:
    youtube = _likes_client()

    result = invoke(
        ["likes", "list", "--limit", "1"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert [item["video_id"] for item in body["data"]["likes"]] == ["likedAvailable1"]
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 1


def test_likes_limit_cap_sets_truncated_and_stays_ok(invoke, credentials) -> None:
    youtube = _likes_client(
        tuple(
            LikedVideo(
                video_id=f"liked{i:04d}",
                title=f"Like {i}",
                channel_title="Like Channel",
                available=True,
                position=i,
            )
            for i in range(501)
        )
    )

    result = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert len(body["data"]["likes"]) == 500
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 500

    youtube.quota_exceeded = True
    cached = invoke(["likes", "list"], credentials=credentials, youtube=youtube)

    assert cached.exit_code == 0
    cached_body = cached.json()
    assert cached_body["ok"] is True
    assert cached_body["meta"]["from_cache"] is True
    assert cached_body["meta"]["truncated"] is True
    assert len(cached_body["data"]["likes"]) == 500


def test_likes_quota_exceeded_fails_without_partial_list_or_cache(
    invoke, credentials, cache_dir
) -> None:
    youtube = _likes_client(quota_exceeded=True)

    result = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    offline = invoke(
        ["likes", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "cache_empty"


def test_likes_table_prints_item_columns(invoke, credentials) -> None:
    youtube = _likes_client()

    result = invoke(
        ["likes", "list", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["video_id", "title", "channel_title", "available"]
    assert "likedAvailable1" in lines[1]
    assert "Liked video" in lines[1]
    assert "true" in lines[1]
    assert "likedDeleted1" in lines[2]
    assert "false" in lines[2]


def test_likes_offline_and_fresh_are_usage(invoke) -> None:
    result = invoke(["likes", "list", "--offline", "--fresh"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_likes_list_with_id_is_usage(invoke) -> None:
    result = invoke(["likes", "list", "LL"])

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_likes_fresh_quota_failure_keeps_existing_cache(invoke, credentials) -> None:
    youtube = _likes_client()
    seeded = invoke(["likes", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    fresh = invoke(
        ["likes", "list", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(
        ["likes", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert fresh.exit_code == 4
    assert fresh.json()["error"]["code"] == "quota_exceeded"
    assert "data" not in fresh.json()
    assert cached.exit_code == 0
    assert cached.json()["data"]["likes"] == seeded.json()["data"]["likes"]
