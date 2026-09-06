# Cue

> [!WARNING]
> **Experimental:** Local file source and output support is still being tested. Keep backups of your media and subtitles before using it.

A local web app that finds English or target-language subtitles for WebDAV or local videos, synchronizes them from a five-minute sample, and translates English through Chat Completions. Choose target-only or bilingual English-and-target cues, then select multiple videos in one folder to run them as a sequential batch; one failure does not stop the remaining files.

Storage is configured globally in Settings. WebDAV sources can save subtitles beside the remote video or flatten all results into one local output folder. Local sources save subtitles beside each video and support the same browser and Smart Rename workflow. Local paths refer to the filesystem of the machine running Cue, not to browser uploads. Every subtitle written by the app includes its language before the extension, such as `Movie.es.srt`; bilingual files add an English postfix, such as `Movie.es.en.srt`. Existing files are never overwritten; flat local-output collisions preserve those language postfixes with names such as `Movie (1).es.srt`, `Movie (2).es.srt`, and so on.

Sidecar subtitles are preferred: in target-only mode an existing target-language `.srt`, `.ass`, `.ssa`, or `.vtt` completes the job immediately, while an existing English sidecar is synchronized and translated to a language-tagged SRT. Bilingual mode always uses English as its source so every cue contains both languages. Exact OpenSubtitles movie-hash matches skip audio synchronization, while all other matches retain the five-minute quality check.

Newly generated SRT cues include a font size scaled from resolution metadata in the video filename. Common release formats such as `720p`, `1080p`, `2160p`, and `1920x1080` are recognized without probing or decoding the video; filenames without resolution metadata use a 1080p default.

Synchronization runs locally. WebDAV videos are downloaded once to a temporary file, then synchronized using the same five-minute sample, 16 kHz analysis, and quality checks. The temporary video is deleted after synchronization, including on failure; no video or audio cache is retained. Local-source videos are used directly. Remote synchronization therefore requires temporary disk space for the full video and downloads the entire file, even for long movies.

## Setup

Requirements: Python 3.13, `uv`, Node.js 20+, and FFmpeg.

```sh
uv sync
npm --prefix frontend install
npm run prod
```

Open <http://127.0.0.1:3666/>. With empty settings, Cue automatically starts a five-step setup: storage, subtitle preferences, OpenSubtitles, OpenAI, and review. Back and Edit preserve your entries; nothing is saved until you select **Save and open library**. The wizard requires an OpenSubtitles account for downloads. Existing configurations open the library as usual and can be edited at <http://127.0.0.1:3666/settings/>.

Local scan and output paths must be absolute, existing, readable, and writable directories. All values, including credentials, are saved in the permission-restricted `~/Library/Application Support/Cue/config.json`; credentials are never returned to the browser after saving. Legacy credential entries in the project-root `.env` are migrated and removed on the next save without disturbing unrelated entries. A WebDAV endpoint without a scheme is treated as HTTPS. OpenSubtitles search needs the consumer API key; downloads also require the username and password so the backend can obtain its 24-hour user token. Saved changes apply immediately. Saving validates configuration values, not remote service credentials.

Cue is intended to run on loopback: requests must use `127.0.0.1` or `localhost`. Browser requests are accepted from the app's own origin and the development frontend on port 3000. Service URLs must keep credentials in their separate settings fields. Local Smart Rename requires a filesystem that supports hard links; if removing the original name fails, both names are retained and the job reports the failure.

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

## Install as an app

Run the production build with `npm run prod`, open <http://127.0.0.1:3666/>, and use your browser's **Install Cue** action (usually in the address bar or menu). On macOS Safari, use **File → Add to Dock**. Cue opens in its own window with its app icon. Installation is available on supported browsers; loopback HTTP works without a certificate. Other origins require HTTPS, and Cue's backend currently accepts only loopback hosts.

Keep the Cue server running when using the installed app. After the first online visit enables the service worker, opening Cue while the server is stopped or unreachable shows an English or Chinese connection screen with a retry button. The worker caches only that self-contained screen; credentials, API responses, library contents, and media are never stored in its cache. Subtitle jobs still require the backend and their configured services.

Service worker registration is disabled in `next dev`. Production pages and assets load from the network, so rebuilds are not held in an app-shell cache. Worker updates take over after existing Cue windows close; bump `CACHE_NAME` in `frontend/public/sw.js` when changing `offline.html` so the new fallback is installed.

## Checks

```sh
uv run python -m unittest discover -s tests
RUN_MEDIA_INTEGRATION=1 uv run python -m unittest tests.test_media_integration
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Automated tests do not call OpenSubtitles, the AI endpoint, or private WebDAV files.

## Performance

Translation runs up to four requests concurrently, with at most 32 cues or 6,000 characters per batch. Results are merged by cue ID to preserve order and timestamps, and subtitles are saved only after every batch succeeds. Smaller batches add some prompt-token overhead. Video batches remain sequential. WebDAV movie hashes read the two 64 KiB ranges concurrently; sidecar language tags avoid unnecessary downloads, including target subtitles reused in place.
