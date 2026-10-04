from __future__ import annotations

import importlib
import json
import platform
import sys
import tempfile
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO, cast
from urllib.parse import parse_qs, urlparse

from youtube_cli.youtube import NetworkError, NotFoundError

Source = Literal["captions", "auto-captions", "generated"]

INSTALL_HINT = "uv sync --extra transcripts"
_SOURCE_PREFERENCE: tuple[Source, ...] = ("captions", "auto-captions")
_CAPTION_FORMAT = "json3"
# yt-dlp's language_preference for the original audio track; its "default"
# track ranks lower and may be a dub picked for the viewer's locale.
_ORIGINAL_AUDIO = 10
DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"
# Biases Speech Recognition towards Simplified script with punctuation.
CHINESE_PROMPT = "以下是普通话的句子，使用简体中文，并加上标点符号。"


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    video_id: str
    language: str
    source: Source
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    source: Source
    translated: bool = False
    ref: str = ""


@dataclass(frozen=True)
class VideoCaptions:
    original_language: str | None
    tracks: tuple[CaptionTrack, ...]


class CaptionSource(Protocol):
    def list_captions(self, video_id: str) -> VideoCaptions: ...

    def fetch_segments(
        self, video_id: str, track: CaptionTrack
    ) -> tuple[Segment, ...]: ...


class AudioSource(Protocol):
    def download(self, video_id: str, directory: Path) -> Path: ...


class SpeechRecognizer(Protocol):
    def detect_language(self, audio: Path, *, model: str) -> str: ...

    def recognize(
        self, audio: Path, *, model: str, language: str, prompt: str | None
    ) -> tuple[Segment, ...]: ...


class TranscriptError(Exception):
    pass


class NoCaptionsError(TranscriptError):
    pass


class VideoRestrictedError(TranscriptError):
    pass


class TranscriptsExtraMissingError(TranscriptError):
    pass


def language_matches(wanted: str, language: str) -> bool:
    wanted, language = wanted.lower(), language.lower()
    return (
        wanted == language
        or wanted.split("-")[0] == language
        or language.split("-")[0] == wanted
    )


def best_language_match[T](
    wanted: str, candidates: Iterable[T], *, language: Callable[[T], str]
) -> T | None:
    """The candidate in exactly the wanted language, else a regional variant."""
    pool = tuple(candidates)
    return next(
        (item for item in pool if language(item).lower() == wanted.lower()), None
    ) or next((item for item in pool if language_matches(wanted, language(item))), None)


def choose_track(captions: VideoCaptions, *, language: str | None) -> CaptionTrack:
    usable = tuple(track for track in captions.tracks if not track.translated)
    if not usable:
        raise NoCaptionsError("video has no Captions")
    available = sorted({track.language for track in usable})
    wanted = language or captions.original_language
    if wanted is None:
        if len(available) > 1:
            raise TranscriptError(
                "original language is unknown; pass --lang "
                f"(available: {', '.join(available)})"
            )
        wanted = available[0]
    for source in _SOURCE_PREFERENCE:
        track = best_language_match(
            wanted,
            (track for track in usable if track.source == source),
            language=lambda track: track.language,
        )
        if track is not None:
            return track
    raise NoCaptionsError(
        f"video has no Captions in {wanted} (available: {', '.join(available)})"
    )


def generate_transcript(
    video_id: str,
    *,
    language: str | None,
    model: str,
    audio: AudioSource,
    recognizer: SpeechRecognizer,
    progress: Callable[[str], None],
) -> Transcript:
    """Speech Recognition over the video's audio, which is deleted afterwards."""
    with tempfile.TemporaryDirectory(prefix="youtube-cli-") as directory:
        progress(f"downloading audio for {video_id}")
        path = audio.download(video_id, Path(directory))
        spoken = (
            _engine_language(language)
            if language is not None
            else recognizer.detect_language(path, model=model)
        )
        progress(f"recognizing speech ({spoken}) with {model}")
        segments = recognizer.recognize(
            path,
            model=model,
            language=spoken,
            prompt=CHINESE_PROMPT if spoken == "zh" else None,
        )
    return Transcript(
        video_id=video_id,
        language=language or spoken,
        source="generated",
        segments=segments,
    )


def _engine_language(language: str) -> str:
    return language.split("-")[0].lower()


@dataclass(frozen=True)
class FakeTrack:
    language: str
    source: Source
    segments: tuple[Segment, ...]
    translated: bool = False


@dataclass(frozen=True)
class FakeVideo:
    original_language: str | None
    tracks: tuple[FakeTrack, ...]


class InMemoryCaptionSource:
    def __init__(
        self,
        videos: dict[str, FakeVideo] | None = None,
        *,
        restricted: bool = False,
        network_error: bool = False,
    ) -> None:
        self.videos = videos or {}
        self.restricted = restricted
        self.network_error = network_error
        self.list_calls: list[str] = []

    def list_captions(self, video_id: str) -> VideoCaptions:
        self.list_calls.append(video_id)
        if self.network_error:
            raise NetworkError("network failure")
        if self.restricted:
            raise VideoRestrictedError(f"video {video_id} is restricted")
        video = self.videos.get(video_id)
        if video is None:
            raise NotFoundError(f"video {video_id} not found")
        return VideoCaptions(
            original_language=video.original_language,
            tracks=tuple(
                CaptionTrack(
                    language=track.language,
                    source=track.source,
                    translated=track.translated,
                    ref=str(index),
                )
                for index, track in enumerate(video.tracks)
            ),
        )

    def fetch_segments(
        self, video_id: str, track: CaptionTrack
    ) -> tuple[Segment, ...]:
        return self.videos[video_id].tracks[int(track.ref)].segments


class InMemoryAudioSource:
    def __init__(self, *, network_error: bool = False) -> None:
        self.network_error = network_error
        self.downloads: list[str] = []
        self.paths: list[Path] = []

    def download(self, video_id: str, directory: Path) -> Path:
        self.downloads.append(video_id)
        path = directory / f"{video_id}.m4a"
        path.write_bytes(b"audio")
        self.paths.append(path)
        if self.network_error:
            raise NetworkError("network failure")
        return path


@dataclass(frozen=True)
class RecognitionCall:
    model: str
    language: str
    prompt: str | None


@dataclass
class InMemorySpeechRecognizer:
    language: str = "en"
    segments: tuple[Segment, ...] = ()
    fails: bool = False
    detections: int = 0
    runs: list[RecognitionCall] = field(default_factory=list[RecognitionCall])

    def detect_language(self, audio: Path, *, model: str) -> str:
        self.detections += 1
        return self.language

    def recognize(
        self, audio: Path, *, model: str, language: str, prompt: str | None
    ) -> tuple[Segment, ...]:
        if not audio.exists():
            raise AssertionError(f"audio is missing: {audio}")
        self.runs.append(RecognitionCall(model=model, language=language, prompt=prompt))
        if self.fails:
            raise TranscriptError("Speech Recognition failed")
        return self.segments


_RESTRICTED_MARKERS = (
    "private video",
    "members-only",
    "members only",
    "join this channel",
    "age-restricted",
    "confirm your age",
    "inappropriate for some users",
)
_NOT_FOUND_MARKERS = (
    "video unavailable",
    "video is unavailable",
    "has been removed",
    "does not exist",
    "incomplete youtube id",
    "truncated",
)


class _SilentLogger:
    """Keeps yt-dlp off stdout and stderr; failures surface as exceptions."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


def _import_extra(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise TranscriptsExtraMissingError(
            f"transcripts need the optional extra; run: {INSTALL_HINT}"
        ) from exc


def _with_yt_dlp(
    yt_dlp: Any, video_id: str, options: dict[str, object], action: Callable[[Any], Any]
) -> Any:
    options = {
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        "noplaylist": True,
        **options,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            return action(ydl)
    except Exception as exc:
        raise _translate_error(video_id, exc) from exc


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


class LiveCaptionSource:
    """Captions via yt-dlp. Never passes browser cookies (see ADR 0001)."""

    def __init__(self) -> None:
        self._yt_dlp = _import_extra("yt_dlp")

    def list_captions(self, video_id: str) -> VideoCaptions:
        info = _object_map(
            self._call(
                video_id,
                lambda ydl: ydl.extract_info(
                    _watch_url(video_id), download=False, process=False
                ),
            )
        )
        tracks = (
            *_tracks_from(info.get("subtitles"), source="captions"),
            *_tracks_from(info.get("automatic_captions"), source="auto-captions"),
        )
        original = _original_language(info, tracks)
        return VideoCaptions(original_language=original, tracks=tracks)

    def fetch_segments(
        self, video_id: str, track: CaptionTrack
    ) -> tuple[Segment, ...]:
        body = self._call(video_id, lambda ydl: ydl.urlopen(track.ref).read())
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise TranscriptError("YouTube returned unreadable Captions") from exc
        return segments_from_json3(payload)

    def _call(self, video_id: str, action: Callable[[Any], Any]) -> Any:
        return _with_yt_dlp(self._yt_dlp, video_id, {"skip_download": True}, action)


class LiveAudioSource:
    """A video's audio via yt-dlp. Never passes browser cookies (see ADR 0001)."""

    def __init__(self) -> None:
        self._yt_dlp = _import_extra("yt_dlp")

    def download(self, video_id: str, directory: Path) -> Path:
        def fetch(ydl: Any) -> str:
            info = ydl.extract_info(_watch_url(video_id), download=True)
            return ydl.prepare_filename(info)

        options: dict[str, object] = {
            "format": "bestaudio/best",
            "outtmpl": str(directory / "%(id)s.%(ext)s"),
        }
        return Path(_with_yt_dlp(self._yt_dlp, video_id, options, fetch))


class LiveSpeechRecognizer:
    """Speech Recognition via mlx-whisper; everything it prints goes to stderr."""

    def __init__(self, stderr: TextIO) -> None:
        try:
            self._whisper = _import_extra("mlx_whisper")
        except TranscriptsExtraMissingError:
            if (sys.platform, platform.machine()) != ("darwin", "arm64"):
                raise TranscriptError(
                    "Speech Recognition needs an Apple Silicon Mac"
                ) from None
            raise
        self._stderr = stderr

    def detect_language(self, audio: Path, *, model: str) -> str:
        whisper: Any = importlib.import_module("mlx_whisper.transcribe")
        with self._engine(model):
            loaded = whisper.ModelHolder.get_model(model, whisper.mx.float16)
            if not loaded.is_multilingual:
                return "en"
            mel = whisper.log_mel_spectrogram(
                str(audio), n_mels=loaded.dims.n_mels, padding=whisper.N_SAMPLES
            )
            window = whisper.pad_or_trim(mel, whisper.N_FRAMES, axis=-2)
            _, probabilities = loaded.detect_language(window.astype(whisper.mx.float16))
        return str(max(probabilities, key=probabilities.get))

    def recognize(
        self, audio: Path, *, model: str, language: str, prompt: str | None
    ) -> tuple[Segment, ...]:
        with self._engine(model):
            result = self._whisper.transcribe(
                str(audio),
                path_or_hf_repo=model,
                language=language,
                initial_prompt=prompt,
                verbose=False,
            )
        return segments_from_whisper(result)

    @contextmanager
    def _engine(self, model: str) -> Generator[None]:
        if not Path(model).exists() and not self._downloaded(model):
            print(
                f"downloading Speech Recognition model {model} (first use only)",
                file=self._stderr,
                flush=True,
            )
        try:
            with redirect_stdout(self._stderr):
                yield
        except Exception as exc:
            raise TranscriptError(f"Speech Recognition failed: {exc}") from exc

    def _downloaded(self, model: str) -> bool:
        try:
            hub: Any = importlib.import_module("huggingface_hub")
            return isinstance(hub.try_to_load_from_cache(model, "config.json"), str)
        except Exception:
            return False


def segments_from_whisper(result: object) -> tuple[Segment, ...]:
    return tuple(
        Segment(start=_as_float(entry.get("start")), end=_as_float(entry.get("end")), text=text)
        for entry in map(_object_map, _object_list(_object_map(result).get("segments")))
        if (text := _as_str(entry.get("text")).strip())
    )


def _translate_error(video_id: str, exc: Exception) -> Exception:
    message = str(exc)
    lowered = message.lower()
    if any(marker in lowered for marker in _RESTRICTED_MARKERS):
        return VideoRestrictedError(
            f"video {video_id} is restricted (age-gated, members-only or private); "
            "transcripts only work for public videos"
        )
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return NotFoundError(f"video {video_id} not found")
    if type(exc).__name__ in {"DownloadError", "ExtractorError"}:
        return TranscriptError(f"yt-dlp failed: {message}")
    return NetworkError(f"network failure: {message}")


def _original_language(
    info: dict[str, object], tracks: tuple[CaptionTrack, ...]
) -> str | None:
    language = info.get("language")
    if isinstance(language, str) and language:
        return language
    audio = [
        (_as_int(entry.get("language_preference")), language)
        for entry in map(_object_map, _object_list(info.get("formats")))
        if isinstance(language := entry.get("language"), str) and language
    ]
    marked = next(
        (language for preference, language in audio if preference >= _ORIGINAL_AUDIO),
        None,
    )
    if marked is not None:
        return marked
    spoken = next(
        (
            track.language
            for track in tracks
            if track.source == "auto-captions" and not track.translated
        ),
        None,
    )
    if spoken is not None:
        return spoken
    languages = {language for _, language in audio}
    return next(iter(languages)) if len(languages) == 1 else None


def _tracks_from(value: object, *, source: Source) -> tuple[CaptionTrack, ...]:
    tracks: dict[str, CaptionTrack] = {}
    for key, formats in _object_map(value).items():
        url = next(
            (
                entry.get("url")
                for entry in map(_object_map, _object_list(formats))
                if entry.get("ext") == _CAPTION_FORMAT
            ),
            None,
        )
        if not isinstance(url, str) or not url:
            continue
        track = CaptionTrack(
            language=key.removesuffix("-orig"),
            source=source,
            translated="tlang" in parse_qs(urlparse(url).query),
            ref=url,
        )
        known = tracks.get(track.language)
        if known is None or (known.translated and not track.translated):
            tracks[track.language] = track
    return tuple(tracks.values())


def segments_from_json3(payload: object) -> tuple[Segment, ...]:
    timed: list[tuple[int, int, str]] = []
    for event in map(_object_map, _object_list(_object_map(payload).get("events"))):
        text = " ".join(
            "".join(
                _as_str(seg.get("utf8"))
                for seg in map(_object_map, _object_list(event.get("segs")))
            ).split()
        )
        if not text:
            continue
        start = _as_int(event.get("tStartMs"))
        timed.append((start, start + _as_int(event.get("dDurationMs")), text))
    segments: list[Segment] = []
    for index, (start, end, text) in enumerate(timed):
        # Automatic Captions overlap the next Segment while it scrolls in.
        following = timed[index + 1][0] if index + 1 < len(timed) else None
        if following is not None and (start < following < end or end == start):
            end = max(start, following)
        segments.append(Segment(start=start / 1000, end=end / 1000, text=text))
    return tuple(segments)


def _object_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    typed = cast(dict[object, object], value)
    return {str(key): item for key, item in typed.items()}


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)
