def test_cache_status_on_empty_cache_shows_path_and_no_collections(
    invoke, cache_dir
) -> None:
    result = invoke(["cache", "status"])

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["path"] == str(cache_dir / "library.sqlite")
    assert body["data"]["collections"] == {}
    assert not (cache_dir / "library.sqlite").exists()


def test_cache_status_shows_path_fetched_at_and_counts(
    invoke, credentials, youtube, cache_dir
) -> None:
    listed = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["cache", "status"], credentials=credentials, youtube=youtube)

    assert listed.exit_code == 0
    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["path"] == str(cache_dir / "library.sqlite")
    assert body["data"]["collections"]["playlists"] == {
        "fetched_at": listed.json()["meta"]["fetched_at"],
        "count": 1,
    }
    assert "quota_cost" not in body["meta"]


def test_cache_clear_deletes_sqlite_and_leaves_tokens(
    invoke, credentials, youtube, cache_dir
) -> None:
    listed = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["cache", "clear"], credentials=credentials, youtube=youtube)

    assert listed.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["ok"] is True
    assert not (cache_dir / "library.sqlite").exists()

    status = invoke(["cache", "status"], credentials=credentials, youtube=youtube)
    auth = invoke(["auth", "status"], credentials=credentials, youtube=youtube)
    offline = invoke(
        ["playlists", "list", "--offline"],
        credentials=credentials,
        youtube=youtube,
    )

    assert status.json()["data"]["collections"] == {}
    assert auth.exit_code == 0
    assert auth.json()["data"]["token_ok"] is True
    assert offline.json()["error"]["code"] == "cache_empty"
