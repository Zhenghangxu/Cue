# Subtitle Maker

> [!WARNING]
> **Experimental:** Local file source and output support is still being tested. Keep backups of your media and subtitles before using it.

A local web app that finds English or target-language subtitles for WebDAV or local videos, synchronizes them from a five-minute sample, and translates English through Chat Completions. Choose target-only or bilingual English-and-target cues, then select multiple videos in one folder to run them as a sequential batch; one failure does not stop the remaining files.

Storage is configured globally in Settings. WebDAV sources can save subtitles beside the remote video or flatten all results into one local output folder. Local sources save subtitles beside each video and support the same browser and Smart Rename workflow. Local paths refer to the filesystem of the machine running Subtitle Maker, not to browser uploads. Existing files are never overwritten; flat local-output collisions use names such as `Movie (1).srt`, `Movie (2).srt`, and so on.

Sidecar subtitles are preferred: in target-only mode an existing target-language `.srt`, `.ass`, `.ssa`, or `.vtt` completes the job immediately, while an existing English sidecar is synchronized and translated to a language-tagged SRT. Bilingual mode always uses English as its source so every cue contains both languages. Exact OpenSubtitles movie-hash matches skip audio synchronization, while all other matches retain the five-minute quality check.

## Setup

Requirements: Python 3.13, `uv`, Node.js 20+, and FFmpeg.

```sh
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/settings/> and choose the media source and subtitle destination, then enter the service settings, target language, and default subtitle mode. Local scan and output paths must be absolute, existing, readable, and writable directories. Secrets are saved as plaintext in the ignored project-root `.env` file and are never returned to the browser after saving. Non-secret values live in `~/Library/Application Support/Subtitle Maker/config.json`. A WebDAV endpoint without a scheme is treated as HTTPS. OpenSubtitles search needs the consumer API key; downloads also require the optional username and password so the backend can obtain its 24-hour user token. Restart Subtitle Maker after saving changes.

## Development

Run the backend:

```sh
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

In another terminal, run the frontend:

```sh
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm --prefix frontend run dev
```

Open <http://127.0.0.1:3000>.

## Local production

```sh
npm --prefix frontend run build
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Build the frontend before starting the backend so FastAPI can mount the static export.

## Checks

```sh
uv run python -m unittest discover -s tests
RUN_MEDIA_INTEGRATION=1 uv run python -m unittest tests.test_media_integration
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

Automated tests do not call OpenSubtitles, the AI endpoint, or private WebDAV files.
