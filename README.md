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
npm run prod
```

Open <http://127.0.0.1:3666/settings/> and choose the media source and subtitle destination, then enter the service settings, target language, and default subtitle mode. Local scan and output paths must be absolute, existing, readable, and writable directories. All values, including credentials, are saved in the permission-restricted `~/Library/Application Support/Subtitle Maker/config.json`; credentials are never returned to the browser after saving. Legacy credential entries in the project-root `.env` are migrated and removed on the next save without disturbing unrelated entries. A WebDAV endpoint without a scheme is treated as HTTPS. OpenSubtitles search needs the consumer API key; downloads also require the optional username and password so the backend can obtain its 24-hour user token. Saved changes apply immediately.

## Development

Run the backend:

```sh
uv run uvicorn backend.app:app --host 127.0.0.1 --port 3666
```

In another terminal, run the frontend:

```sh
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3666 npm --prefix frontend run dev
```

Open <http://127.0.0.1:3000>.

## Local production

```sh
npm run prod
```

Open <http://127.0.0.1:3666>. This builds the frontend's static production export, then starts FastAPI, which serves both the API and frontend. Run `npm start` when the frontend is already built and you only need to restart the server.

## Checks

```sh
uv run python -m unittest discover -s tests
RUN_MEDIA_INTEGRATION=1 uv run python -m unittest tests.test_media_integration
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

Automated tests do not call OpenSubtitles, the AI endpoint, or private WebDAV files.
