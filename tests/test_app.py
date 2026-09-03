import json
import shutil
import struct
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import srt

from backend.app import (
    Config,
    FileEntry,
    JOBS,
    JOBS_LOCK,
    Job,
    JobItem,
    JobRequest,
    OpenSubtitles,
    PipelineError,
    SettingsRequest,
    SubtitleCandidate,
    TARGET_LANGUAGES,
    WebDAV,
    batch_cues,
    calculate_moviehash,
    choose_output_path,
    detect_sidecar_language,
    frequency_data,
    load_frequency_data,
    minimal_candidates,
    normalize_relative,
    process_video,
    create_job,
    get_settings,
    run_job,
    sync_subtitle,
    translate_srt,
    update_settings,
    app,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient


def config() -> Config:
    return Config(
        webdav_username="user",
        webdav_password="pass",
        webdav_endpoint="https://example.test/dav/",
        webdav_scan_path="Media Library",
        opensubtitles_api_key="key",
        opensubtitles_consumer_name="tests",
        openai_base_url="https://ai.example.test/v1/",
        openai_api_key="ai-key",
        openai_model_id="gpt-5.6-luna",
        openai_reasoning_effort="low",
        target_language="zh-cn",
        default_subtitle_mode="bilingual",
    )


SRT = b"1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n"


class CoreTests(unittest.TestCase):
    def test_settings_save_secrets_to_env_and_not_config(self):
        values = {
            "webdav_username": "user",
            "webdav_endpoint": "https://example.test/dav",
            "webdav_scan_path": "Media",
            "opensubtitles_consumer_name": "tests",
            "opensubtitles_username": "subtitle-user",
            "openai_base_url": "https://ai.example.test/v1",
            "openai_model_id": "model",
            "openai_reasoning_effort": "low",
            "target_language": "zh-cn",
            "default_subtitle_mode": "bilingual",
            "minimal_frequency_tier": "2000",
        }
        secrets = {
            "webdav_password": "webdav-secret",
            "opensubtitles_api_key": "subtitle-key",
            "opensubtitles_password": "subtitle-secret",
            "openai_api_key": "ai-secret",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("backend.app.CONFIG_DIR", Path(directory)),
            patch("backend.app.CONFIG_PATH", Path(directory) / "config.json"),
            patch("backend.app.ENV_PATH", Path(directory) / ".env"),
        ):
            defaults = get_settings()["values"]
            self.assertEqual(defaults["target_language"], "zh-cn")
            self.assertEqual(defaults["default_subtitle_mode"], "bilingual")
            self.assertEqual(defaults["minimal_frequency_tier"], "2000")
            self.assertTrue(update_settings(SettingsRequest(values=values, secrets=secrets))["saved"])
            response = get_settings()
            self.assertEqual(response["values"], values)
            self.assertEqual(len(response["options"]["target_languages"]), 20)
            self.assertEqual(response["options"]["subtitle_modes"][-1], {"value": "minimalistic", "label": "Minimalistic"})
            self.assertTrue(all(response["secrets"].values()))
            config_text = (Path(directory) / "config.json").read_text()
            self.assertNotIn("secret", config_text)
            self.assertEqual((Path(directory) / "config.json").stat().st_mode & 0o777, 0o600)
            env_text = (Path(directory) / ".env").read_text()
            self.assertIn("WEBDAV_PASSWORD='webdav-secret'", env_text)
            self.assertIn("OPENAI_API_KEY='ai-secret'", env_text)
            self.assertEqual((Path(directory) / ".env").stat().st_mode & 0o777, 0o600)

            update_settings(SettingsRequest(values=values, clear_secrets=["opensubtitles_password"]))
            self.assertNotIn("OPENSUBTITLES_PASSWORD", (Path(directory) / ".env").read_text())
            with self.assertRaises(HTTPException) as raised:
                update_settings(SettingsRequest(values=values | {"unknown": "value"}))
            self.assertEqual(raised.exception.status_code, 400)
            with self.assertRaises(HTTPException) as raised:
                update_settings(SettingsRequest(values=values | {"target_language": "klingon"}))
            self.assertEqual(raised.exception.status_code, 400)
            with self.assertRaises(HTTPException) as raised:
                update_settings(SettingsRequest(values=values | {"default_subtitle_mode": "invalid"}))
            self.assertEqual(raised.exception.status_code, 400)
            with self.assertRaises(HTTPException) as raised:
                update_settings(SettingsRequest(values=values | {"minimal_frequency_tier": "2500"}))
            self.assertEqual(raised.exception.status_code, 400)

    def test_paths_cannot_escape_scan_root(self):
        self.assertEqual(normalize_relative("Shows/Series/Episode.mkv"), "Shows/Series/Episode.mkv")
        for value in ("../secret", "Shows/../secret", "/etc/passwd", "C:\\secret", "%2e%2e/secret"):
            with self.subTest(value=value), self.assertRaises(PipelineError):
                normalize_relative(value)

    def test_moviehash_matches_unsigned_little_endian_sum(self):
        first = struct.pack("<8192Q", *range(8192))
        last = struct.pack("<8192Q", *range(8192, 16384))
        size = len(first) + len(last)
        expected = (size + sum(range(16384))) & 0xFFFFFFFFFFFFFFFF
        self.assertEqual(calculate_moviehash(size, first, last), f"{expected:016x}")

    def test_output_name_falls_back_without_overwrite(self):
        self.assertEqual(choose_output_path("Movies/Movie.mkv", "es", lambda _: False), "Movies/Movie.srt")
        self.assertEqual(
            choose_output_path("Movies/Movie.mkv", "pt-br", lambda path: path.endswith("Movie.srt")),
            "Movies/Movie.pt-BR.srt",
        )
        with self.assertRaises(PipelineError):
            choose_output_path("Movies/Movie.mkv", "es", lambda _: True)

    def test_cues_are_bounded_by_count_and_characters(self):
        cues = [
            (index, srt.Subtitle(index=index + 1, start=timedelta(), end=timedelta(seconds=1), content="x" * 130))
            for index in range(205)
        ]
        batches = batch_cues(cues)
        self.assertTrue(all(len(batch) <= 200 for batch in batches))
        self.assertTrue(all(sum(len(cue.content) for _, cue in batch) <= 24_000 for batch in batches))
        self.assertEqual(sum(map(len, batches)), len(cues))

    def test_candidate_preference_is_chinese_then_english(self):
        def item(language: str, file_id: int):
            return {
                "attributes": {
                    "language": language,
                    "nb_cd": 1,
                    "release": language,
                    "files": [{"file_id": file_id}],
                }
            }

        selected = OpenSubtitles._prefer([item("en", 1), item("es", 2)], ("es", "en"))
        self.assertEqual(selected.file_id, 2)
        self.assertEqual(len(TARGET_LANGUAGES), 20)

    def test_opensubtitles_login_precedes_download(self):
        requests = []

        def handler(request: httpx.Request):
            requests.append(request)
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"token": "jwt"})
            if request.url.path.endswith("/download"):
                self.assertEqual(request.headers.get("authorization"), "Bearer jwt")
                return httpx.Response(200, json={"link": "https://files.example.test/sub.srt", "remaining": 4})
            return httpx.Response(200, content=SRT)

        authenticated = Config(**{
            **config().__dict__,
            "opensubtitles_username": "member",
            "opensubtitles_password": "secret",
        })
        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(handler),
        )
        data, quota = OpenSubtitles(authenticated, client).download(
            SubtitleCandidate(1, "en", "release", True)
        )
        self.assertEqual(data, SRT)
        self.assertEqual(quota["remaining"], 4)
        self.assertTrue(requests[0].url.path.endswith("/login"))

    def test_opensubtitles_loads_remaining_quota(self):
        def handler(request: httpx.Request):
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"token": "jwt"})
            self.assertEqual(request.headers.get("authorization"), "Bearer jwt")
            return httpx.Response(200, json={"data": {"remaining_downloads": 20}})

        authenticated = Config(**{
            **config().__dict__,
            "opensubtitles_username": "member",
            "opensubtitles_password": "secret",
        })
        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(OpenSubtitles(authenticated, client).remaining_downloads(), 20)

    def test_opensubtitles_retries_server_and_rate_limit_responses(self):
        responses = iter([
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"data": []}),
        ])
        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(lambda _: next(responses)),
        )
        with patch("backend.app.random.uniform", return_value=0.1), patch("backend.app.time.sleep") as sleep:
            self.assertEqual(OpenSubtitles(config(), client)._search({"query": "movie"}), [])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.1, 7.0])

    def test_opensubtitles_reports_api_error_detail(self):
        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(400, json={"errors": ["Not enough parameters"]})
            ),
        )
        with self.assertRaisesRegex(
            PipelineError, r"OpenSubtitles search failed \(400\): Not enough parameters"
        ):
            OpenSubtitles(config(), client)._search({"query": ""})

    def test_opensubtitles_normalizes_bracketed_anime_release(self):
        requests = []

        def handler(request: httpx.Request):
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(PipelineError, "No reliable requested subtitle"):
            OpenSubtitles(config(), client).find(
                "[Airota][Sousou no Frieren][29][1080p HEVC-10bit AAC ASS].mkv",
                "9e433af2ca9cd6a5",
                ("zh-cn", "en"),
            )

        self.assertEqual(requests[1].url.params["query"], "sousou no frieren")
        self.assertEqual(requests[1].url.params["episode_number"], "29")

    def test_opensubtitles_ignores_missing_feature_details(self):
        self.assertFalse(
            OpenSubtitles._metadata_match(
                {"attributes": {"feature_details": None}},
                {"title": "Slow Horses", "type": "episode", "season": 2, "episode": 2},
            )
        )

    def test_opensubtitles_episode_search_omits_series_year(self):
        requests = []

        def handler(request: httpx.Request):
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        client = httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(PipelineError, "No reliable requested subtitle"):
            OpenSubtitles(config(), client).find(
                "Slow Horses (2022) - S02E02 - From Upshott With Love.mkv",
                "9e433af2ca9cd6a5",
                ("en",),
            )

        self.assertNotIn("year", requests[1].url.params)

    def test_sync_uses_16khz_speech_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.srt"
            output = Path(directory) / "output.srt"
            source.write_bytes(SRT)

            def run(args, **_):
                output.write_bytes(SRT)
                return SimpleNamespace(returncode=0)

            with patch("backend.app.shutil.which", return_value="ffsubsync"), patch(
                "backend.app.subprocess.run", side_effect=run
            ) as process:
                sync_subtitle("Movie.mkv", source, output, config())

        arguments = process.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--frame-rate") + 1], "16000")

    def test_sidecar_language_uses_content_and_language_suffix(self):
        video = "Movie.2026.mkv"
        self.assertEqual(detect_sidecar_language(video, "Movie.2026.srt", "你好，世界".encode()), "zh-cn")
        self.assertEqual(detect_sidecar_language(video, "Movie.2026.en.srt", b"Short"), "en")
        self.assertEqual(detect_sidecar_language(video, "Movie.2026.ja.srt", "日本語です".encode()), "ja")
        self.assertEqual(detect_sidecar_language(video, "Movie.2026.zh-Hant.srt", "繁體中文".encode()), "zh-tw")


class WebDAVTests(unittest.TestCase):
    def test_listing_ignores_entries_outside_scan_root(self):
        xml = b"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response><d:href>/dav/Media%20Library/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
          <d:response><d:href>/dav/Media%20Library/Shows/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
          <d:response><d:href>/dav/Media%20Library/Movie.mkv</d:href><d:propstat><d:prop><d:resourcetype/><d:getcontentlength>123</d:getcontentlength></d:prop></d:propstat></d:response>
          <d:response><d:href>/dav/private.mkv</d:href><d:propstat><d:prop><d:resourcetype/><d:getcontentlength>999</d:getcontentlength></d:prop></d:propstat></d:response>
        </d:multistatus>"""

        def handler(request: httpx.Request):
            self.assertEqual(request.method, "PROPFIND")
            return httpx.Response(207, content=xml)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        entries = WebDAV(config(), client).list("")
        self.assertEqual([(entry.type, entry.path) for entry in entries], [("directory", "Shows"), ("video", "Movie.mkv")])

    def test_range_request_requires_206(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"ignored")))
        with self.assertRaisesRegex(PipelineError, "does not support"):
            WebDAV(config(), client).read_range("Movie.mkv", 0, 9)

    def test_media_redirect_does_not_forward_webdav_credentials(self):
        initial = httpx.Client(
            auth=("user", "pass"),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"Location": "https://cdn.example.test/file"})
            ),
        )

        def cdn(request: httpx.Request):
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(request.headers["range"], "bytes=0-9")
            return httpx.Response(206, content=b"0123456789")

        media = httpx.Client(transport=httpx.MockTransport(cdn))
        self.assertEqual(WebDAV(config(), initial, media).read_range("Movie.mkv", 0, 9), b"0123456789")


class FakeWebDAV:
    def __init__(self):
        self.uploads = {}
        self.sidecar_entries = []
        self.sidecar_data = {}
        self.hash_calls = 0

    def file_info(self, relative):
        return FileEntry(name=Path(relative).name, path=relative, type="video", size=131_072)

    def exists(self, _):
        return False

    def moviehash(self, *_):
        self.hash_calls += 1
        return "1234567890abcdef"

    def sidecars(self, _):
        return self.sidecar_entries

    def read_small(self, relative):
        return self.sidecar_data[relative]

    def put(self, relative, data):
        self.uploads[relative] = data


class FakeOpenSubtitles:
    def __init__(self, language):
        self.language = language
        self.languages = None

    def find(self, *args):
        self.languages = args[-1]
        return SubtitleCandidate(file_id=1, language=self.language, release="Matched.Release", moviehash_match=True)

    def download(self, _):
        return SRT, {"remaining": 4, "resetTimeUtc": "tomorrow"}


def copy_sync(_, source, destination, __):
    shutil.copyfile(source, destination)


class PipelineTests(unittest.TestCase):
    def test_existing_chinese_sidecar_completes_without_network_or_upload(self):
        webdav = FakeWebDAV()
        entry = FileEntry("Movie.zh-Hans.srt", "Movie.zh-Hans.srt", "file", 20)
        webdav.sidecar_entries = [entry]
        webdav.sidecar_data[entry.path] = "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n".encode()

        class ForbiddenOpenSubtitles:
            def find(self, *_):
                raise AssertionError("Existing Chinese must skip OpenSubtitles")

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            ForbiddenOpenSubtitles(),
            lambda *_: None,
            syncer=copy_sync,
            subtitle_mode="target",
        )
        self.assertTrue(result["existing"])
        self.assertEqual(result["outputPath"], entry.path)
        self.assertEqual(webdav.hash_calls, 0)
        self.assertEqual(webdav.uploads, {})

    def test_bilingual_ignores_existing_target_sidecar_and_uses_english(self):
        webdav = FakeWebDAV()
        entry = FileEntry("Movie.zh-Hans.srt", "Movie.zh-Hans.srt", "file", 20)
        webdav.sidecar_entries = [entry]
        webdav.sidecar_data[entry.path] = "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n".encode()

        def translator(source, destination, _, **options):
            self.assertEqual(options["subtitle_mode"], "bilingual")
            destination.write_text(source.read_text() + "\nTranslated", encoding="utf-8")
            return {"promptTokens": 1, "completionTokens": 1, "totalTokens": 2}

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            FakeOpenSubtitles("en"),
            lambda *_: None,
            syncer=copy_sync,
            translator=translator,
        )
        self.assertNotIn("existing", result)
        self.assertIn(b"Translated", webdav.uploads["Movie.srt"])

    def test_minimalistic_uses_english_and_uploads_ass(self):
        webdav = FakeWebDAV()
        entry = FileEntry("Movie.zh-Hans.srt", "Movie.zh-Hans.srt", "file", 20)
        webdav.sidecar_entries = [entry]
        webdav.sidecar_data[entry.path] = "1\n00:00:01,000 --> 00:00:02,000\n你好\n\n".encode()
        opensubtitles = FakeOpenSubtitles("en")

        def translator(source, destination, _, **options):
            self.assertEqual(options["subtitle_mode"], "minimalistic")
            destination.write_text("[Script Info]\n", encoding="utf-8")
            return {"promptTokens": 1, "completionTokens": 1, "totalTokens": 2}

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            opensubtitles,
            lambda *_: None,
            syncer=copy_sync,
            translator=translator,
            subtitle_mode="minimalistic",
        )

        self.assertEqual(opensubtitles.languages, ("en",))
        self.assertEqual(result["outputPath"], "Movie.minimal.zh-Hans.ass")
        self.assertEqual(webdav.uploads[result["outputPath"]], b"[Script Info]\n")

    def test_existing_english_sidecar_is_translated_to_language_output(self):
        webdav = FakeWebDAV()
        entry = FileEntry("Movie.en.srt", "Movie.en.srt", "file", len(SRT))
        webdav.sidecar_entries = [entry]
        webdav.sidecar_data[entry.path] = SRT

        class ForbiddenOpenSubtitles:
            def find(self, *_):
                raise AssertionError("Existing English must skip OpenSubtitles")

        def translator(source, destination, _, **__):
            destination.write_text(source.read_text() + "\nTranslated", encoding="utf-8")
            return {"promptTokens": 1, "completionTokens": 1, "totalTokens": 2}

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            ForbiddenOpenSubtitles(),
            lambda *_: None,
            syncer=copy_sync,
            translator=translator,
        )
        self.assertEqual(result["outputPath"], "Movie.zh-Hans.srt")
        self.assertEqual(webdav.hash_calls, 0)
        self.assertIn(b"Translated", webdav.uploads["Movie.zh-Hans.srt"])

    def test_chinese_flow_skips_ai_and_uploads_srt(self):
        webdav = FakeWebDAV()
        opensubtitles = FakeOpenSubtitles("zh-cn")

        def forbidden_ai(*_):
            raise AssertionError("Chinese subtitles must not call AI")

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            opensubtitles,
            lambda *_: None,
            syncer=copy_sync,
            translator=forbidden_ai,
            subtitle_mode="target",
        )
        self.assertEqual(result["outputPath"], "Movie.srt")
        self.assertEqual(webdav.uploads["Movie.srt"], SRT)
        self.assertEqual(opensubtitles.languages, ("zh-cn", "en"))

    def test_exact_moviehash_skips_sync_but_metadata_match_does_not(self):
        webdav = FakeWebDAV()

        def forbidden_sync(*_):
            raise AssertionError("Exact movie hash must skip synchronization")

        process_video(
            "Exact.mkv",
            config(),
            webdav,
            FakeOpenSubtitles("zh-cn"),
            lambda *_: None,
            syncer=forbidden_sync,
            subtitle_mode="target",
        )

        class MetadataMatch(FakeOpenSubtitles):
            def find(self, *_):
                return SubtitleCandidate(1, "zh-cn", "Metadata.Match", False)

        sync_calls = []

        def record_sync(*args):
            sync_calls.append(args)
            copy_sync(*args)

        process_video(
            "Fallback.mkv",
            config(),
            webdav,
            MetadataMatch("zh-cn"),
            lambda *_: None,
            syncer=record_sync,
            subtitle_mode="target",
        )
        self.assertEqual(len(sync_calls), 1)

        class InvalidExact(FakeOpenSubtitles):
            def download(self, _):
                return b"not an srt", {"remaining": 3, "resetTimeUtc": "tomorrow"}

        process_video(
            "Invalid.mkv",
            config(),
            webdav,
            InvalidExact("zh-cn"),
            lambda *_: None,
            syncer=record_sync,
            subtitle_mode="target",
        )
        self.assertEqual(len(sync_calls), 2)

    def test_english_flow_translates_before_upload(self):
        webdav = FakeWebDAV()

        def translator(source, destination, _, **__):
            destination.write_text(source.read_text() + "\nTranslated", encoding="utf-8")
            return {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15}

        opensubtitles = FakeOpenSubtitles("en")
        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            opensubtitles,
            lambda *_: None,
            syncer=copy_sync,
            translator=translator,
        )
        self.assertIn(b"Translated", webdav.uploads["Movie.srt"])
        self.assertEqual(result["aiUsage"]["totalTokens"], 15)
        self.assertEqual(opensubtitles.languages, ("en",))

    def test_no_subtitle_stops_before_download_or_upload(self):
        webdav = FakeWebDAV()

        class NoResults(FakeOpenSubtitles):
            def find(self, *_):
                raise PipelineError("No reliable subtitle")

            def download(self, _):
                raise AssertionError("No candidate means no download")

        with self.assertRaisesRegex(PipelineError, "No reliable"):
            process_video(
                "Movie.mkv",
                config(),
                webdav,
                NoResults("en"),
                lambda *_: None,
                syncer=copy_sync,
            )
        self.assertEqual(webdav.uploads, {})


class BatchJobTests(unittest.TestCase):
    def setUp(self):
        with JOBS_LOCK:
            JOBS.clear()

    def tearDown(self):
        with JOBS_LOCK:
            JOBS.clear()

    def test_backend_logs_rejected_requests_with_correlation_id(self):
        with (
            patch("backend.app.require_services", return_value=(config(), object(), object())),
            TestClient(app) as client,
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            rejected = client.post("/api/jobs", json={"paths": []})
            invalid = client.put(
                "/api/settings",
                json={"values": [], "secrets": {"openai_api_key": "must-not-be-logged"}},
            )

        logs = "\n".join(captured.output)
        self.assertEqual(rejected.status_code, 400)
        self.assertTrue(rejected.headers["X-Request-ID"])
        self.assertEqual(invalid.status_code, 422)
        self.assertTrue(invalid.headers["X-Request-ID"])
        self.assertIn("request_rejected", logs)
        self.assertIn("detail='Select at least one video'", logs)
        self.assertIn("request_validation_failed", logs)
        self.assertIn('"field": "body.values"', logs)
        self.assertNotIn("must-not-be-logged", logs)

    def test_create_job_validates_paths_keeps_order_and_queues_more(self):
        job_config = Config(**(config().__dict__ | {"target_language": "es"}))
        with patch("backend.app.require_services", return_value=(job_config, object(), object())), patch(
            "backend.app.EXECUTOR.submit"
        ) as submit:
            for paths in ([], ["Movie.mkv", "./Movie.mkv"], ["../Movie.mkv"]):
                with self.subTest(paths=paths), self.assertRaises(HTTPException) as raised:
                    create_job(JobRequest(paths=paths))
                self.assertEqual(raised.exception.status_code, 400)

            response = create_job(JobRequest(paths=["B.mkv", "A.mkv"]))
            self.assertEqual([item.path for item in JOBS[response["jobId"]].items], ["B.mkv", "A.mkv"])
            queued = create_job(JobRequest(paths=["C.mkv"], mode="target"))
            self.assertEqual([item.path for item in JOBS[queued["jobId"]].items], ["C.mkv"])
            self.assertEqual(JOBS[queued["jobId"]].target_language, "es")
            self.assertEqual(JOBS[response["jobId"]].subtitle_mode, "bilingual")
            self.assertEqual(JOBS[queued["jobId"]].subtitle_mode, "target")
            self.assertEqual(submit.call_count, 2)
            with self.assertRaises(HTTPException) as raised:
                create_job(JobRequest(paths=["A.mkv"]))
            self.assertEqual(raised.exception.status_code, 409)
            with self.assertRaises(HTTPException) as raised:
                create_job(JobRequest(paths=["D.mkv"], mode="invalid"))
            self.assertEqual(raised.exception.status_code, 400)

    def test_batch_continues_after_item_failure(self):
        JOBS["batch"] = Job(id="batch", items=[JobItem(path=path) for path in ("A.mkv", "B.mkv", "C.mkv")])
        calls = []

        def process(path, *_args, **_kwargs):
            calls.append(path)
            if path == "B.mkv":
                raise PipelineError("No subtitle")
            return {"existing": False, "outputPath": path.replace(".mkv", ".srt")}

        with (
            patch("backend.app.require_services", return_value=(config(), object(), object())),
            patch("backend.app.OpenAI"),
            patch("backend.app.process_video", side_effect=process),
        ):
            run_job("batch")

        self.assertEqual(calls, ["A.mkv", "B.mkv", "C.mkv"])
        self.assertEqual(JOBS["batch"].status, "completed")
        self.assertEqual([item.status for item in JOBS["batch"].items], ["completed", "failed", "completed"])
        self.assertTrue(all(item.started_at and item.finished_at and item.finished_at >= item.started_at for item in JOBS["batch"].items))
        self.assertIn("2 of 3", JOBS["batch"].message)

    def test_all_failed_batch_is_failed(self):
        JOBS["batch"] = Job(id="batch", items=[JobItem(path="A.mkv"), JobItem(path="B.mkv")])
        with (
            patch("backend.app.require_services", return_value=(config(), object(), object())),
            patch("backend.app.OpenAI"),
            patch("backend.app.process_video", side_effect=PipelineError("No subtitle")),
        ):
            run_job("batch")

        self.assertEqual(JOBS["batch"].status, "failed")
        self.assertTrue(all(item.status == "failed" for item in JOBS["batch"].items))
        self.assertEqual(JOBS["batch"].error, "Every video in the batch failed")


class FakeCompletions:
    def __init__(self, invalid=False):
        self.calls = []
        self.invalid = invalid

    def create(self, **kwargs):
        self.calls.append(kwargs)
        requested = json.loads(kwargs["messages"][1]["content"])
        translations = [] if self.invalid else [{"id": row["id"], "text": "你好。"} for row in requested]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"translations": translations})))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )


class FakeAI:
    def __init__(self, invalid=False):
        self.chat = SimpleNamespace(completions=FakeCompletions(invalid))

    @property
    def responses(self):
        raise AssertionError("Responses API must never be accessed")


class TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_frequency_data()

    def test_minimalistic_selects_rare_words_and_positions_glosses(self):
        data = frequency_data()
        _, candidates = minimal_candidates(
            "The path ahead is treacherous, but the view is breathtaking.",
            data,
            2000,
        )
        terms = {candidate["text"] for candidate in candidates}
        self.assertIn("treacherous", terms)
        self.assertIn("breathtaking", terms)
        self.assertNotIn("path", terms)

        class MinimalCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                requested = json.loads(kwargs["messages"][1]["content"])
                translations = []
                for row in requested:
                    selected = [candidate for candidate in row["candidates"] if candidate["text"] in {"treacherous", "breathtaking"}]
                    translations.append({
                        "id": row["id"],
                        "glosses": [
                            {"candidate": candidate["id"], "text": "险峻的" if candidate["text"] == "treacherous" else "令人惊叹的"}
                            for candidate in selected
                        ],
                    })
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"translations": translations})))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4, total_tokens=12),
                )

        completions = MinimalCompletions()
        fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        source_text = "1\n00:00:01,000 --> 00:00:03,000\nThe path ahead is treacherous,\nbut the view is breathtaking.\n\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.srt"
            output = Path(directory) / "out.ass"
            source.write_text(source_text, encoding="utf-8")
            usage = translate_srt(source, output, config(), fake, subtitle_mode="minimalistic", frequency=data)
            rendered = output.read_text()

        self.assertEqual(usage["totalTokens"], 12)
        self.assertIn("[V4+ Styles]", rendered)
        self.assertIn("险峻的", rendered)
        self.assertIn("令人惊叹的", rendered)
        self.assertIn("treacherous, but", rendered)
        base_lines = [line for line in rendered.splitlines() if line.startswith("Dialogue: 0")]
        gloss_lines = [line for line in rendered.splitlines() if line.startswith("Dialogue: 1")]
        self.assertEqual(len(base_lines), 1)
        self.assertEqual(len(gloss_lines), 2)
        base_x = base_lines[0].partition(r"\pos(")[2].partition(",")[0]
        self.assertTrue(all(",English," in line and rf"\an4\pos({base_x}," in line for line in gloss_lines))
        self.assertTrue(all("The path ahead is " in line and ", but the view is " in line for line in gloss_lines))
        self.assertIn(r"\fscx220\fscy58}险峻的", rendered)
        self.assertIn(r"\fscx144\fscy58}令人惊叹的", rendered)
        self.assertEqual(completions.calls[0]["response_format"]["json_schema"]["name"], "subtitle_glosses")

    def test_minimalistic_skips_ai_when_every_word_is_common(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.srt"
            output = Path(directory) / "out.ass"
            source.write_text("1\n00:00:01,000 --> 00:00:03,000\nI am here.\n\n", encoding="utf-8")
            usage = translate_srt(
                source,
                output,
                config(),
                SimpleNamespace(chat=None),
                subtitle_mode="minimalistic",
                frequency=frequency_data(),
            )
            rendered = output.read_text()

        self.assertEqual(usage["totalTokens"], 0)
        self.assertIn("I am here.", rendered)
        self.assertNotIn("Dialogue: 1", rendered)

    def test_chat_completions_shape_and_bilingual_output(self):
        fake = FakeAI()
        with tempfile.TemporaryDirectory() as directory, patch("backend.app.OpenAI", return_value=fake) as factory:
            source = Path(directory) / "in.srt"
            output = Path(directory) / "out.srt"
            source.write_bytes(SRT)
            usage = translate_srt(source, output, config())
            rendered = output.read_text()

        self.assertIn("Hello there.\n你好。", rendered)
        self.assertEqual(usage["totalTokens"], 18)
        call = fake.chat.completions.calls[0]
        self.assertEqual([message["role"] for message in call["messages"]], ["developer", "user"])
        self.assertEqual(call["response_format"]["type"], "json_schema")
        self.assertEqual(call["reasoning_effort"], "low")
        self.assertIs(call["store"], False)
        self.assertNotIn("input", call)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 2)

    def test_target_only_replaces_english_and_names_target_language(self):
        fake = FakeAI()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.srt"
            output = Path(directory) / "out.srt"
            source.write_bytes(SRT)
            translate_srt(
                source,
                output,
                config(),
                fake,
                target_language="es",
                subtitle_mode="target",
            )
            rendered = output.read_text()

        self.assertNotIn("Hello there.", rendered)
        self.assertIn("Spanish", fake.chat.completions.calls[0]["messages"][0]["content"])

    def test_invalid_translation_ids_fail_after_three_chat_calls(self):
        fake = FakeAI(invalid=True)
        with tempfile.TemporaryDirectory() as directory, patch("backend.app.time.sleep"):
            source = Path(directory) / "in.srt"
            source.write_bytes(SRT)
            with self.assertRaisesRegex(PipelineError, "three attempts"):
                translate_srt(source, Path(directory) / "out.srt", config(), fake)
        self.assertEqual(len(fake.chat.completions.calls), 3)

    def test_transport_failure_is_not_retried_by_schema_loop(self):
        calls = []

        class BrokenCompletions:
            def create(self, **_):
                calls.append(1)
                raise RuntimeError("transport failed")

        fake = SimpleNamespace(chat=SimpleNamespace(completions=BrokenCompletions()))
        with tempfile.TemporaryDirectory() as directory, patch("backend.app.time.sleep") as sleep:
            source = Path(directory) / "in.srt"
            source.write_bytes(SRT)
            with self.assertRaisesRegex(PipelineError, "request failed"):
                translate_srt(source, Path(directory) / "out.srt", config(), fake)
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
