# Subtitle Maker

A local web app that finds English or Simplified Chinese subtitles for WebDAV videos, synchronizes them from a five-minute streamed sample, translates English through Chat Completions, and uploads the final SRT beside the video.

Sidecar subtitles are preferred: an existing Chinese `.srt`, `.ass`, `.ssa`, or `.vtt` completes the job immediately; an existing English sidecar is synchronized and translated to `<video>.zh-Hans.srt`; OpenSubtitles is used only when neither is available.

## Setup

Requirements: Python 3.13, `uv`, Node.js 20+, and FFmpeg.

```sh
cp .env.example .env
# Fill in .env, then:
uv sync
npm --prefix frontend install
```

The existing `.env` is supported as-is. A WebDAV endpoint without a scheme is treated as HTTPS. OpenSubtitles search needs the consumer API key; downloads also require `OPENSUBTITLE_USERNAME` and `OPENSUBTITLE_PASSWORD` so the backend can obtain its 24-hour user token.

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
