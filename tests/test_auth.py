from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx

from youtube_cli.credentials import InMemoryCredentialStore, Tokens
from youtube_cli.youtube import Channel


def test_auth_status_reports_channel_and_expiry_and_never_prints_the_token(
    invoke, credentials, youtube
) -> None:
    youtube.channel = Channel(id="UCmine", title="Fixture Channel")

    result = invoke(["auth", "status"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {
        "channel_title": "Fixture Channel",
        "token_ok": True,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    assert "test-access" not in result.stdout
    assert "test-refresh" not in result.stdout
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["quota_cost"] == 1
    assert body["meta"]["fetched_at"]


def test_auth_status_table_prints_empty_cells_when_logged_out(invoke) -> None:
    result = invoke(
        ["auth", "status", "--table"],
        credentials=InMemoryCredentialStore(),
    )

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["channel_title", "token_ok", "expires_at"]
    assert lines[1] == "\tfalse\t"


def test_auth_status_table_prints_fixed_columns(invoke, credentials, youtube) -> None:
    youtube.channel = Channel(id="UCmine", title="Fixture Channel")

    result = invoke(
        ["auth", "status", "--table"],
        credentials=credentials,
        youtube=youtube,
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].split() == ["channel_title", "token_ok", "expires_at"]
    assert lines[1].split("\t") == ["Fixture Channel", "true", "2099-01-01T00:00:00Z"]
    assert "test-access" not in result.stdout
    assert "test-refresh" not in result.stdout


def test_auth_status_without_tokens_reports_token_not_ok(invoke, youtube) -> None:
    youtube.quota_exceeded = True
    result = invoke(
        ["auth", "status"],
        credentials=InMemoryCredentialStore(),
        youtube=youtube,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {
        "channel_title": None,
        "token_ok": False,
        "expires_at": None,
    }
    assert "quota_cost" not in body["meta"]


def test_auth_status_rejected_token_reports_token_not_ok(
    invoke, credentials, youtube
) -> None:
    youtube.unauthorized = True

    result = invoke(["auth", "status"], credentials=credentials, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"]["token_ok"] is False
    assert body["data"]["channel_title"] is None
    assert body["meta"]["quota_cost"] == 1
    assert "test-access" not in result.stdout


def test_auth_status_refreshes_expired_access_token(invoke, youtube) -> None:
    store = InMemoryCredentialStore()
    store.save(
        Tokens(
            access_token="old-access",
            refresh_token="refresh-me",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    def refresh_tokens(tokens: Tokens) -> Tokens:
        assert tokens.refresh_token == "refresh-me"
        return Tokens(
            access_token="new-access",
            refresh_token="refresh-me",
            expires_at=datetime(2099, 6, 1, tzinfo=UTC),
        )

    result = invoke(
        ["auth", "status"],
        credentials=store,
        youtube=youtube,
        refresh_tokens=refresh_tokens,
    )

    assert result.exit_code == 0
    body = result.json()
    assert body["data"]["token_ok"] is True
    assert body["data"]["channel_title"] == "Fixture Channel"
    assert body["data"]["expires_at"] == "2099-06-01T00:00:00Z"
    saved = store.load()
    assert saved is not None
    assert saved.access_token == "new-access"
    assert "old-access" not in result.stdout
    assert "new-access" not in result.stdout
    assert "refresh-me" not in result.stdout


def test_playlists_list_refreshes_expired_access_token(invoke, youtube) -> None:
    store = InMemoryCredentialStore()
    store.save(
        Tokens(
            access_token="old-access",
            refresh_token="refresh-me",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    def refresh_tokens(tokens: Tokens) -> Tokens:
        return Tokens(
            access_token="new-access",
            refresh_token="refresh-me",
            expires_at=datetime(2099, 6, 1, tzinfo=UTC),
        )

    result = invoke(
        ["playlists", "list"],
        credentials=store,
        youtube=youtube,
        refresh_tokens=refresh_tokens,
    )

    assert result.exit_code == 0
    assert result.json()["ok"] is True
    saved = store.load()
    assert saved is not None
    assert saved.access_token == "new-access"


def test_auth_status_with_expired_token_reports_token_not_ok(invoke, youtube) -> None:
    youtube.quota_exceeded = True
    store = InMemoryCredentialStore()
    store.save(
        Tokens(
            access_token="expired-access",
            refresh_token="expired-refresh",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    result = invoke(["auth", "status"], credentials=store, youtube=youtube)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {
        "channel_title": None,
        "token_ok": False,
        "expires_at": "2020-01-01T00:00:00Z",
    }
    assert "expired-access" not in result.stdout
    assert "quota_cost" not in body["meta"]


def _write_client_secret(config_dir) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client_secret.json").write_text(
        '{"installed":{"client_id":"test-id","client_secret":"test-secret"}}',
        encoding="utf-8",
    )


def test_auth_logout_deletes_tokens_only(invoke, credentials, youtube, cache_dir, config_dir) -> None:
    _write_client_secret(config_dir)
    listed = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    result = invoke(["auth", "logout"], credentials=credentials, youtube=youtube)

    assert listed.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["ok"] is True
    assert credentials.load() is None
    assert (cache_dir / "library.sqlite").is_file()
    assert (config_dir / "client_secret.json").is_file()
    status = invoke(["cache", "status"], credentials=credentials, youtube=youtube)
    assert status.json()["data"]["collections"]["playlists"]["count"] == 1


def test_auth_logout_wipe_deletes_tokens_and_cache(
    invoke, credentials, youtube, cache_dir, config_dir
) -> None:
    _write_client_secret(config_dir)
    listed = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    result = invoke(
        ["auth", "logout", "--wipe"],
        credentials=credentials,
        youtube=youtube,
    )

    assert listed.exit_code == 0
    assert result.exit_code == 0
    assert result.json()["ok"] is True
    assert credentials.load() is None
    assert not (cache_dir / "library.sqlite").exists()
    assert (config_dir / "client_secret.json").is_file()
    status = invoke(["cache", "status"], credentials=credentials, youtube=youtube)
    assert status.json()["data"]["collections"] == {}


def test_auth_login_loopback_stores_tokens_without_talking_to_google(
    invoke, config_dir
) -> None:
    _write_client_secret(config_dir)
    store = InMemoryCredentialStore()
    opened: list[str] = []

    def open_browser(url: str) -> None:
        opened.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        redirect = query["redirect_uri"][0]
        assert "accounts.google.com" in url
        assert "youtube.readonly" in query["scope"][0]
        assert redirect.startswith("http://127.0.0.1:")
        httpx.get(redirect, params={"code": "loopback-code"})

    def exchange_code(code: str, redirect_uri: str, client) -> Tokens:
        assert code == "loopback-code"
        assert redirect_uri.startswith("http://127.0.0.1:")
        assert client.client_id == "test-id"
        assert client.client_secret == "test-secret"
        return Tokens(
            access_token="login-access",
            refresh_token="login-refresh",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )

    result = invoke(
        ["auth", "login"],
        credentials=store,
        open_browser=open_browser,
        exchange_code=exchange_code,
    )

    assert result.exit_code == 0
    assert result.json()["ok"] is True
    tokens = store.load()
    assert tokens is not None
    assert tokens.access_token == "login-access"
    assert tokens.refresh_token == "login-refresh"
    assert "login-access" not in result.stdout
    assert "login-refresh" not in result.stdout
    assert opened


def test_auth_login_loads_client_secret_from_env_file(
    invoke, tmp_path, monkeypatch
) -> None:
    secret = tmp_path / "from-env.json"
    secret.write_text(
        '{"installed":{"client_id":"env-file-id","client_secret":"env-file-secret"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret))
    captured: list[str] = []

    result = invoke(
        ["auth", "login"],
        credentials=InMemoryCredentialStore(),
        **_login_ports(captured, expected_client_id="env-file-id"),
    )

    assert result.exit_code == 0
    assert captured


def test_auth_login_loads_client_id_and_secret_from_env_vars(
    invoke, monkeypatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    captured: list[str] = []

    result = invoke(
        ["auth", "login"],
        credentials=InMemoryCredentialStore(),
        **_login_ports(captured, expected_client_id="env-id"),
    )

    assert result.exit_code == 0
    assert captured


def test_auth_login_without_client_secret_is_error(invoke) -> None:
    result = invoke(
        ["auth", "login"],
        credentials=InMemoryCredentialStore(),
    )

    assert result.exit_code == 1
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "error"
    assert body["error"]["message"]


def _login_ports(opened: list[str], *, expected_client_id: str):
    def open_browser(url: str) -> None:
        opened.append(url)
        redirect = parse_qs(urlparse(url).query)["redirect_uri"][0]
        httpx.get(redirect, params={"code": "loopback-code"})

    def exchange_code(code: str, redirect_uri: str, client) -> Tokens:
        assert client.client_id == expected_client_id
        return Tokens(
            access_token="login-access",
            refresh_token="login-refresh",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )

    return {"open_browser": open_browser, "exchange_code": exchange_code}
