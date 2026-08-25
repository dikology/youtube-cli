import json
import subprocess


def test_console_script_named_youtube_returns_usage_for_unknown_command() -> None:
    completed = subprocess.run(
        ["youtube", "bogus"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    body = json.loads(completed.stdout)
    assert body["ok"] is False
    assert body["error"]["code"] == "usage"


def test_unknown_command_returns_usage_envelope_and_exits_2(invoke) -> None:
    result = invoke(["bogus"])

    _assert_usage(result)


def test_missing_command_returns_usage_envelope_and_exits_2(invoke) -> None:
    result = invoke([])

    _assert_usage(result)


def test_playlists_without_list_returns_usage(invoke) -> None:
    result = invoke(["playlists"])

    _assert_usage(result)


def test_likes_without_list_returns_usage(invoke) -> None:
    result = invoke(["likes"])

    _assert_usage(result)


def test_subs_without_list_returns_usage(invoke) -> None:
    result = invoke(["subs"])

    _assert_usage(result)


def test_unknown_flag_returns_usage(invoke) -> None:
    result = invoke(["playlists", "list", "--json"])

    _assert_usage(result)


def test_offline_and_fresh_together_are_usage(invoke) -> None:
    result = invoke(["playlists", "list", "--offline", "--fresh"])

    _assert_usage(result)


def test_limit_over_2000_is_usage(invoke) -> None:
    result = invoke(["playlists", "list", "--limit", "2001"])

    _assert_usage(result)


def _assert_usage(result) -> None:
    assert result.exit_code == 2
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "usage"
    assert body["error"]["message"]
