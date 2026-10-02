# youtube-cli

A personal, local-first command line for one person's YouTube library and the videos in it.

## Language

**Library Cache**:
The local, disposable copy of everything the CLI has learned from YouTube. Anything in it can be rebuilt, at the cost of time or quota.
_Avoid_: Database, store

**Captions**:
Timed text for a video that YouTube itself holds, whether written by the uploader or produced by YouTube automatically.
_Avoid_: Subtitles, transcription

**Transcript**:
The timed text of a video's speech as held by the CLI: an ordered list of Segments in one language, with a Source.
_Avoid_: Transcription, subtitles, captions (when meaning the CLI's copy)

**Segment**:
One stretch of a Transcript: a start time, an end time, and the text spoken between them.
_Avoid_: Line, cue, chunk

**Source**:
Where a Transcript came from: `captions` when taken from uploader-written Captions, `auto-captions` when taken from Captions YouTube produced automatically, `generated` when produced by Speech Recognition. A video has at most one Transcript per language, whatever its Source.
_Avoid_: Origin, provider

**Speech Recognition**:
Producing a Transcript from a video's audio on this machine, without YouTube's involvement.
_Avoid_: ASR, transcription, STT
