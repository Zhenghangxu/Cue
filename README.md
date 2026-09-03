# Subtitle Maker

A local web app that finds English or target-language subtitles for WebDAV videos, synchronizes them from a five-minute streamed sample, translates English through Chat Completions, and uploads the result beside the video. Choose target-only, bilingual, or Minimalistic cues, then select multiple videos in one folder to run them as a sequential batch; one failure does not stop the remaining files.

Sidecar subtitles are preferred: in target-only mode an existing target-language `.srt`, `.ass`, `.ssa`, or `.vtt` completes the job immediately, while an existing English sidecar is synchronized and translated to a language-tagged SRT. Bilingual mode always uses English as its source so every cue contains both languages. Exact OpenSubtitles movie-hash matches skip audio synchronization, while all other matches retain the five-minute quality check.

Minimalistic mode uses English sources and creates an Infuse-compatible `.ass` sidecar. It checks NGSL word ranks and PHRASE List expression ranks, asks AI to gloss at most three difficult items per cue, and positions the smaller translations above the matching English spans. Configure the 1K–5K cutoff in Settings; the default translates vocabulary beyond the top 2K.

The bundled frequency snapshot uses [NGSL 1.2](https://www.newgeneralservicelist.com/new-general-service-list) by Browne, Culligan, and Phillips under CC BY-SA 4.0, plus the [PHRASE List](https://www.lextutor.ca/freq/lists_download/phrase_list_martinez.htm) by Ron Martinez and Norbert Schmitt. The normalized dictionaries load asynchronously from disk when FastAPI starts; no dataset network request occurs at runtime.

## Setup

Requirements: Python 3.13, `uv`, Node.js 20+, and FFmpeg.

```sh
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/settings/> and enter the service settings, target language, and default subtitle mode. Secrets are saved as plaintext in the ignored project-root `.env` file and are never returned to the browser after saving. Non-secret values live in `~/Library/Application Support/Subtitle Maker/config.json`. A WebDAV endpoint without a scheme is treated as HTTPS. OpenSubtitles search needs the consumer API key; downloads also require the optional username and password so the backend can obtain its 24-hour user token.

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
