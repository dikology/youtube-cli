import sqlite3
from datetime import UTC, datetime

from youtube_cli.credentials import InMemoryCredentialStore, Tokens
from youtube_cli.youtube import InMemoryYouTubeClient, Playlist


def test_missing_tokens_are_auth_required_and_do_not_call_youtube(
    invoke, youtube
) -> None:
    youtube.quota_exceeded = True
    result = invoke(
        ["playlists", "list"],
        credentials=InMemoryCredentialStore(),
        youtube=youtube,
    )

    assert result.exit_code == 3
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "auth_required"
    assert body["error"]["message"]


def test_expired_tokens_are_auth_expired_and_do_not_call_youtube(
    invoke, youtube
) -> None:
    youtube.quota_exceeded = True
    store = InMemoryCredentialStore()
    store.save(
        Tokens(
            access_token="expired-access",
            refresh_token="expired-refresh",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    result = invoke(["playlists", "list"], credentials=store, youtube=youtube)

    assert result.exit_code == 3
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "auth_expired"
    assert body["error"]["message"]


def test_playlists_list_returns_owned_playlists(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlists", "list"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["playlists"] == [
        {
            "id": "PLowned1",
            "title": "Watch later-ish",
            "item_count": 3,
            "privacy": "private",
            "channel_id": "UCmine",
            "url": "https://www.youtube.com/playlist?list=PLowned1",
        }
    ]
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["truncated"] is False
    assert body["meta"]["limit"] == 500
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_second_playlists_list_is_cache_hit(invoke, credentials, youtube) -> None:
    first = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    second = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert first.exit_code == 0
    assert second.exit_code == 0
    body = second.json()
    assert body["ok"] is True
    assert body["data"]["playlists"] == first.json()["data"]["playlists"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert "quota_cost" not in body["meta"]


def test_lazy_fill_writes_playlists_only(invoke, credentials, youtube, cache_dir) -> None:
    result = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    conn = sqlite3.connect(cache_dir / "library.sqlite")
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    item_rows = (
        conn.execute("SELECT COUNT(*) FROM playlist_items").fetchone()[0]
        if "playlist_items" in tables
        else 0
    )
    item_meta = conn.execute(
        "SELECT name FROM collection_meta WHERE name LIKE 'playlist_items:%'"
    ).fetchall()
    conn.close()
    assert "playlists" in tables
    assert "likes" not in tables
    assert "subscriptions" not in tables
    assert item_rows == 0
    assert item_meta == []


def test_fresh_snapshot_replaces_cached_playlists(
    invoke, credentials, youtube
) -> None:
    first = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    youtube.playlists = (
        Playlist(
            id="PLnew",
            title="Replacement",
            item_count=1,
            privacy="public",
            channel_id="UCmine",
        ),
    )

    fresh = invoke(
        ["playlists", "list", "--fresh"],
        credentials=credentials,
        youtube=youtube,
    )
    cached = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert first.json()["data"]["playlists"][0]["id"] == "PLowned1"
    assert fresh.exit_code == 0
    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["meta"]["quota_cost"] == 1
    assert fresh.json()["data"]["playlists"] == [
        {
            "id": "PLnew",
            "title": "Replacement",
            "item_count": 1,
            "privacy": "public",
            "channel_id": "UCmine",
            "url": "https://www.youtube.com/playlist?list=PLnew",
        }
    ]
    assert cached.json()["meta"]["from_cache"] is True
    assert cached.json()["data"]["playlists"][0]["id"] == "PLnew"


def test_offline_uses_cache_and_never_calls_adapter(
    invoke, credentials, youtube
) -> None:
    seeded = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    youtube.quota_exceeded = True

    result = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert seeded.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True
    assert "quota_cost" not in result.json()["meta"]
    assert result.json()["data"]["playlists"] == seeded.json()["data"]["playlists"]


def test_offline_on_empty_cache_is_cache_empty(invoke, credentials, youtube) -> None:
    youtube.quota_exceeded = True

    result = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "cache_empty"
    assert body["error"]["message"]


def test_limit_cap_sets_truncated_and_stays_ok(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=tuple(
            Playlist(
                id=f"PL{i:04d}",
                title=f"List {i}",
                item_count=i,
                privacy="public",
                channel_id="UCmine",
            )
            for i in range(501)
        )
    )

    result = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert len(body["data"]["playlists"]) == 500
    assert body["meta"]["truncated"] is True
    assert body["meta"]["limit"] == 500

    youtube.quota_exceeded = True
    cached = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert cached.exit_code == 0
    cached_body = cached.json()
    assert cached_body["ok"] is True
    assert cached_body["meta"]["from_cache"] is True
    assert cached_body["meta"]["truncated"] is True
    assert len(cached_body["data"]["playlists"]) == 500


def test_quota_exceeded_fails_without_partial_list_or_cache(
    invoke, credentials, cache_dir
) -> None:
    youtube = InMemoryYouTubeClient(
        playlists=(
            Playlist(
                id="PLowned1",
                title="Watch later-ish",
                item_count=3,
                privacy="private",
                channel_id="UCmine",
            ),
        ),
        quota_exceeded=True,
    )

    result = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)
    offline = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 4
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quota_exceeded"
    assert "data" not in body
    assert offline.json()["error"]["code"] == "cache_empty"
    assert not (cache_dir / "library.sqlite").exists() or _playlists_unfilled(cache_dir)


def test_table_prints_playlist_columns(invoke, credentials, youtube) -> None:
    result = invoke(
        ["playlists", "list", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["id", "title", "item_count", "privacy"]
    assert "PLowned1" in lines[1]
    assert "Watch later-ish" in lines[1]
    assert "3" in lines[1]
    assert "private" in lines[1]


def test_cache_directory_is_0700(invoke, credentials, youtube, cache_dir) -> None:
    result = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    assert cache_dir.is_dir()
    assert (cache_dir.stat().st_mode & 0o777) == 0o700


def test_youtube_cache_dir_env_selects_sqlite_path(
    invoke, credentials, youtube, tmp_path, monkeypatch
) -> None:
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv("YOUTUBE_CACHE_DIR", str(env_dir))

    result = invoke(
        ["playlists", "list"],
        credentials=credentials,
        youtube=youtube,
        cache_dir_override=None,
    )

    assert result.exit_code == 0
    assert (env_dir / "library.sqlite").is_file()


def test_network_failure_is_network_and_exit_6(invoke, credentials) -> None:
    youtube = InMemoryYouTubeClient(network_error=True)

    result = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 6
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "network"
    assert body["error"]["message"]


def _playlists_unfilled(cache_dir) -> bool:
    db = cache_dir / "library.sqlite"
    if not db.exists():
        return True
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT 1 FROM collection_meta WHERE name = 'playlists'"
    ).fetchone()
    conn.close()
    return row is None
