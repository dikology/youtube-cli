# Unofficial download path, confined to transcripts

The YouTube Data API cannot return a video's audio, nor Captions for videos the user does not own, so Transcripts are impossible on the official API alone. We accept `yt-dlp` for this, knowing it is outside YouTube's terms and breaks when YouTube changes, but confine it to the transcript command and ship it as an optional extra: every library command stays on the official API with the `youtube.readonly` scope, and a broken downloader can never take the rest of the CLI down with it.

## Considered Options

- **Stay official-only, accept a user-supplied audio file.** Rejected: it moves the unofficial download to the user's shell without removing it, and loses caption fetching.
- **Make `yt-dlp` a core dependency.** Rejected: it would tie the stable, quota-bound library commands to a tool that needs frequent updates.

## Consequences

Speech Recognition runs locally (`mlx-whisper`) and lives in the same optional extra, so the default install stays at `httpx` and `keyring`. The transcript command must fail with a clear install hint when the extra is absent.
