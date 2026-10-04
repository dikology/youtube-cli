import sys
import types

from youtube_cli.transcripts import (
    FakeTrack,
    FakeVideo,
    InMemoryCaptionSource,
    LiveCaptionSource,
    Segment,
    Source,
    choose_track,
)

HELLO = (
    Segment(start=0.0, end=2.5, text="Hello there."),
    Segment(start=2.5, end=5.0, text="Welcome back."),
)
HELLO_PAYLOAD = [
    {"start": 0.0, "end": 2.5, "text": "Hello there."},
    {"start": 2.5, "end": 5.0, "text": "Welcome back."},
]
AUTO = (Segment(start=0.0, end=1.0, text="hello there"),)
FRENCH = (Segment(start=0.0, end=2.5, text="Bonjour."),)
LONG = (
    Segment(start=5.0, end=7.0, text="Early on."),
    Segment(start=3725.4, end=3730.0, text="Much later."),
)


def _source(
    *tracks: FakeTrack,
    original_language: str | None = "en",
    video_id: str = "vidTalk1",
) -> InMemoryCaptionSource:
    return InMemoryCaptionSource(
        {video_id: FakeVideo(original_language=original_language, tracks=tracks)}
    )


def _track(
    language: str = "en",
    source: Source = "captions",
    *,
    translated: bool = False,
    segments: tuple[Segment, ...] = HELLO,
) -> FakeTrack:
    return FakeTrack(
        language=language,
        source=source,
        translated=translated,
        segments=segments,
    )


def test_video_transcript_returns_captions_as_a_transcript_without_login(
    invoke,
) -> None:
    captions = _source(_track())

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {
        "video_id": "vidTalk1",
        "language": "en",
        "source": "captions",
        "segments": HELLO_PAYLOAD,
    }
    assert body["meta"]["from_cache"] is False
    assert body["meta"]["fetched_at"]


def test_watch_and_short_urls_return_the_same_transcript_as_the_bare_id(
    invoke,
) -> None:
    captions = _source(_track(), video_id="dQw4w9WgXcQ")

    by_id = invoke(["video", "transcript", "dQw4w9WgXcQ"], captions=captions)
    by_watch = invoke(
        [
            "video",
            "transcript",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc&t=42s",
            "--fresh",
        ],
        captions=captions,
    )
    by_short = invoke(
        ["video", "transcript", "https://youtu.be/dQw4w9WgXcQ?si=xyz", "--fresh"],
        captions=captions,
    )

    assert by_id.exit_code == 0
    assert by_id.json()["data"]["video_id"] == "dQw4w9WgXcQ"
    assert by_watch.json()["data"] == by_id.json()["data"]
    assert by_short.json()["data"] == by_id.json()["data"]
    assert captions.list_calls == ["dQw4w9WgXcQ"] * 3


def test_video_transcript_rejects_a_url_that_is_not_a_video(invoke) -> None:
    result = invoke(
        ["video", "transcript", "https://www.youtube.com/playlist?list=PLabc"],
        captions=_source(_track()),
    )

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"


def test_uploader_captions_win_over_automatic_ones(invoke) -> None:
    captions = _source(
        _track("en", "auto-captions", segments=AUTO),
        _track("en", "captions"),
    )

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.json()["data"]["source"] == "captions"
    assert result.json()["data"]["segments"] == HELLO_PAYLOAD


def test_automatic_captions_are_used_when_the_uploader_wrote_none(invoke) -> None:
    captions = _source(_track("en", "auto-captions", segments=AUTO))

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.exit_code == 0
    assert result.json()["data"]["source"] == "auto-captions"
    assert result.json()["data"]["segments"] == [
        {"start": 0.0, "end": 1.0, "text": "hello there"}
    ]


def test_without_lang_the_original_language_is_used(invoke) -> None:
    captions = _source(
        _track("en", "captions"),
        _track("fr", "auto-captions", segments=FRENCH),
        original_language="fr",
    )

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.json()["data"]["language"] == "fr"
    assert result.json()["data"]["source"] == "auto-captions"


def test_lang_selects_a_caption_track(invoke) -> None:
    captions = _source(
        _track("en", "captions"),
        _track("fr", "captions", segments=FRENCH),
    )

    result = invoke(
        ["video", "transcript", "vidTalk1", "--lang", "fr"], captions=captions
    )

    assert result.exit_code == 0
    assert result.json()["data"]["language"] == "fr"
    assert result.json()["data"]["segments"] == [
        {"start": 0.0, "end": 2.5, "text": "Bonjour."}
    ]


def test_translated_tracks_are_never_used(invoke) -> None:
    captions = _source(
        _track("en", "auto-captions", segments=AUTO),
        _track("fr", "auto-captions", translated=True, segments=FRENCH),
    )

    result = invoke(
        ["video", "transcript", "vidTalk1", "--lang", "fr"], captions=captions
    )

    assert result.exit_code == 7
    assert result.json()["error"]["code"] == "no_captions"


def test_video_without_captions_fails_with_its_own_error_code(invoke) -> None:
    result = invoke(["video", "transcript", "vidTalk1"], captions=_source())

    assert result.exit_code == 7
    body = result.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "no_captions"
    assert body["error"]["message"]


def test_restricted_video_fails_with_a_clear_error(invoke) -> None:
    captions = _source(_track())
    captions.restricted = True

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.exit_code == 9
    assert result.json()["error"]["code"] == "video_restricted"


def test_unknown_video_is_not_found(invoke) -> None:
    result = invoke(["video", "transcript", "vidMissing"], captions=_source(_track()))

    assert result.exit_code == 5
    assert result.json()["error"]["code"] == "not_found"


def test_second_call_is_served_from_the_library_cache(invoke) -> None:
    captions = _source(_track())
    first = invoke(["video", "transcript", "vidTalk1"], captions=captions)
    captions.network_error = True

    second = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert second.exit_code == 0
    body = second.json()
    assert body["data"] == first.json()["data"]
    assert body["meta"]["from_cache"] is True
    assert body["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert captions.list_calls == ["vidTalk1"]


def test_each_language_is_cached_separately(invoke) -> None:
    captions = _source(
        _track("en", "captions"),
        _track("fr", "captions", segments=FRENCH),
    )
    invoke(["video", "transcript", "vidTalk1"], captions=captions)
    invoke(["video", "transcript", "vidTalk1", "--lang", "fr"], captions=captions)
    captions.network_error = True

    english = invoke(["video", "transcript", "vidTalk1"], captions=captions)
    french = invoke(
        ["video", "transcript", "vidTalk1", "--lang", "fr"], captions=captions
    )

    assert english.json()["data"]["language"] == "en"
    assert french.json()["data"]["language"] == "fr"
    assert french.json()["meta"]["from_cache"] is True
    assert captions.list_calls == ["vidTalk1", "vidTalk1"]


def test_fresh_refetches_and_replaces_the_cached_transcript(invoke) -> None:
    invoke(
        ["video", "transcript", "vidTalk1"],
        captions=_source(_track("en", "auto-captions", segments=AUTO)),
    )
    improved = _source(_track("en", "captions"))

    fresh = invoke(["video", "transcript", "vidTalk1", "--fresh"], captions=improved)
    improved.network_error = True
    after = invoke(["video", "transcript", "vidTalk1"], captions=improved)

    assert fresh.json()["meta"]["from_cache"] is False
    assert fresh.json()["data"]["source"] == "captions"
    assert after.json()["meta"]["from_cache"] is True
    assert after.json()["data"]["source"] == "captions"
    assert after.json()["data"]["segments"] == HELLO_PAYLOAD


def test_offline_returns_the_cached_transcript_without_fetching(invoke) -> None:
    captions = _source(_track())
    invoke(["video", "transcript", "vidTalk1"], captions=captions)

    result = invoke(["video", "transcript", "vidTalk1", "--offline"], captions=captions)

    assert result.exit_code == 0
    assert result.json()["data"]["segments"] == HELLO_PAYLOAD
    assert captions.list_calls == ["vidTalk1"]


def test_offline_miss_fails_without_fetching(invoke) -> None:
    captions = _source(_track())

    result = invoke(["video", "transcript", "vidTalk1", "--offline"], captions=captions)

    assert result.exit_code == 1
    assert result.json()["error"]["code"] == "offline_miss"
    assert captions.list_calls == []


def test_table_prints_one_segment_per_row_with_its_start_time(invoke) -> None:
    result = invoke(
        ["video", "transcript", "vidTalk1", "--table"],
        captions=_source(_track(segments=LONG)),
    )

    assert result.exit_code == 0
    assert result.stdout == "start\ttext\n0:05\tEarly on.\n1:02:05\tMuch later.\n"


def test_text_prints_only_the_text_one_segment_per_line(invoke) -> None:
    result = invoke(
        ["video", "transcript", "vidTalk1", "--text"],
        captions=_source(_track()),
    )

    assert result.exit_code == 0
    assert result.stdout == "Hello there.\nWelcome back.\n"


def test_table_with_text_is_a_usage_error(invoke) -> None:
    captions = _source(_track())

    result = invoke(
        ["video", "transcript", "vidTalk1", "--table", "--text"], captions=captions
    )

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"
    assert captions.list_calls == []


def test_text_and_lang_are_rejected_on_other_commands(invoke) -> None:
    for flag in (["--text"], ["--lang", "en"]):
        result = invoke(["video", "get", "vidTalk1", *flag])

        assert result.exit_code == 2
        assert result.json()["error"]["code"] == "usage"


def test_cache_status_reports_a_transcripts_count(invoke) -> None:
    captions = _source(
        _track("en", "captions"),
        _track("fr", "captions", segments=FRENCH),
    )
    first = invoke(["video", "transcript", "vidTalk1"], captions=captions)
    invoke(["video", "transcript", "vidTalk1", "--fresh"], captions=captions)
    last = invoke(["video", "transcript", "vidTalk1", "--lang", "fr"], captions=captions)

    result = invoke(["cache", "status"])

    assert first.exit_code == 0
    assert result.json()["data"]["collections"]["transcripts"] == {
        "fetched_at": last.json()["meta"]["fetched_at"],
        "count": 2,
    }


def test_missing_extra_prints_the_install_line(invoke, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", None)

    result = invoke(["video", "transcript", "vidTalk1"])

    assert result.exit_code == 8
    body = result.json()
    assert body["error"]["code"] == "transcripts_extra_missing"
    assert "uv sync --extra transcripts" in body["error"]["message"]


def test_missing_extra_does_not_affect_cached_transcripts_or_other_commands(
    invoke, credentials, youtube, monkeypatch
) -> None:
    invoke(["video", "transcript", "vidTalk1"], captions=_source(_track()))
    monkeypatch.setitem(sys.modules, "yt_dlp", None)

    cached = invoke(["video", "transcript", "vidTalk1"])
    listed = invoke(["playlists", "list"], credentials=credentials, youtube=youtube)

    assert cached.exit_code == 0
    assert cached.json()["meta"]["from_cache"] is True
    assert listed.exit_code == 0


def test_refetching_by_lang_keeps_the_default_transcript_cached(invoke) -> None:
    captions = _source(_track(), original_language=None)
    invoke(["video", "transcript", "vidTalk1"], captions=captions)
    invoke(
        ["video", "transcript", "vidTalk1", "--lang", "en", "--fresh"],
        captions=captions,
    )
    captions.network_error = True

    result = invoke(["video", "transcript", "vidTalk1"], captions=captions)

    assert result.exit_code == 0
    assert result.json()["meta"]["from_cache"] is True


def test_video_transcript_rejects_an_argument_that_is_not_an_id(invoke) -> None:
    captions = _source(_track())

    result = invoke(["video", "transcript", "watch?v=vidTalk1"], captions=captions)

    assert result.exit_code == 2
    assert result.json()["error"]["code"] == "usage"
    assert captions.list_calls == []


class _FakeYoutubeDL:
    def __init__(self, info: dict[str, object]) -> None:
        self._info = info

    def __enter__(self) -> "_FakeYoutubeDL":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, **kwargs: object) -> dict[str, object]:
        return self._info


def _live_source(monkeypatch, info: dict[str, object]) -> LiveCaptionSource:
    module = types.SimpleNamespace(YoutubeDL=lambda options: _FakeYoutubeDL(info))
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    return LiveCaptionSource()


def _caption_formats(language: str, **query: str) -> list[dict[str, str]]:
    params = "&".join(f"{key}={value}" for key, value in {"lang": language, **query}.items())
    return [{"ext": "json3", "url": f"https://www.youtube.com/api/timedtext?{params}"}]


def _audio(language: str | None, preference: int) -> dict[str, object]:
    return {"language": language, "language_preference": preference}


def test_original_language_of_a_dubbed_video_is_its_original_audio_track(
    monkeypatch,
) -> None:
    source = _live_source(
        monkeypatch,
        {
            "formats": [
                *[_audio("es", -1)] * 3,
                *[_audio("ar", -1)] * 3,
                *[_audio("en-US", 10)] * 2,
                _audio(None, -1),
            ],
            "subtitles": {
                "es": _caption_formats("es"),
                "en": _caption_formats("en"),
            },
        },
    )

    captions = source.list_captions("vidDubbed1")

    assert captions.original_language == "en-US"
    assert choose_track(captions, language=None).language == "en"


def test_original_language_falls_back_to_the_untranslated_automatic_captions(
    monkeypatch,
) -> None:
    source = _live_source(
        monkeypatch,
        {
            "formats": [_audio("es", 5), _audio("de", -1)],
            "subtitles": {"es": _caption_formats("es")},
            "automatic_captions": {
                "es": _caption_formats("de", kind="asr", tlang="es"),
                "de": _caption_formats("de", kind="asr"),
            },
        },
    )

    assert source.list_captions("vidTalk1").original_language == "de"


def test_original_language_is_the_only_audio_language_when_nothing_else_says(
    monkeypatch,
) -> None:
    source = _live_source(
        monkeypatch,
        {
            "formats": [_audio("fr", -1), _audio("fr", -1), _audio(None, -1)],
            "subtitles": {"en": _caption_formats("en"), "fr": _caption_formats("fr")},
        },
    )

    assert source.list_captions("vidTalk1").original_language == "fr"
