from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from youtube_cli.cli import run
from youtube_cli.credentials import CredentialStore, InMemoryCredentialStore, Tokens
from youtube_cli.oauth import LoginError
from youtube_cli.transcripts import AudioSource, CaptionSource, SpeechRecognizer
from youtube_cli.youtube import InMemoryYouTubeClient, Playlist, PlaylistItem, YouTubeClient

_MISSING = object()


def _reject_browser(url: str) -> None:
    raise AssertionError(f"browser must not open for this command: {url}")


def _reject_refresh(tokens: Tokens) -> Tokens:
    raise LoginError("tests must inject refresh_tokens; refusing to call Google")


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str = ""

    def json(self) -> dict[str, Any]:
        return json.loads(self.stdout)


Invoke = Callable[..., CliResult]


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def credentials() -> InMemoryCredentialStore:
    store = InMemoryCredentialStore()
    store.save(
        Tokens(
            access_token="test-access",
            refresh_token="test-refresh",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    return store


@pytest.fixture
def youtube() -> InMemoryYouTubeClient:
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
    )


@pytest.fixture
def invoke(cache_dir: Path, config_dir: Path) -> Invoke:
    def _invoke(
        argv: list[str],
        *,
        credentials: CredentialStore | None = None,
        youtube: YouTubeClient | None = None,
        captions: CaptionSource | None = None,
        audio: AudioSource | None = None,
        recognizer: SpeechRecognizer | None = None,
        cache_dir_override: Path | None | object = _MISSING,
        config_dir_override: Path | None | object = _MISSING,
        open_browser: Callable[[str], object] | None = None,
        exchange_code: Callable[..., Tokens] | None = None,
        refresh_tokens: Callable[[Tokens], Tokens] | None = None,
    ) -> CliResult:
        stdout = StringIO()
        stderr = StringIO()
        resolved_cache_dir = (
            cache_dir if cache_dir_override is _MISSING else cache_dir_override
        )
        resolved_config_dir = (
            config_dir if config_dir_override is _MISSING else config_dir_override
        )
        exit_code = run(
            argv,
            credentials=credentials,
            youtube=youtube,
            captions=captions,
            audio=audio,
            recognizer=recognizer,
            cache_dir=resolved_cache_dir,  # type: ignore[arg-type]
            config_dir=resolved_config_dir,  # type: ignore[arg-type]
            stdout=stdout,
            stderr=stderr,
            open_browser=open_browser
            or (_reject_browser),
            exchange_code=exchange_code,
            refresh_tokens=refresh_tokens
            if refresh_tokens is not None
            else _reject_refresh,
        )
        return CliResult(
            exit_code=exit_code,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )

    return _invoke
