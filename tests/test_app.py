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
    SubtitleCandidate,
    WebDAV,
    batch_cues,
    calculate_moviehash,
    choose_output_path,
    detect_sidecar_language,
    normalize_relative,
    process_video,
    create_job,
    run_job,
    sync_subtitle,
    translate_srt,
)
from fastapi import HTTPException


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
    )


SRT = b"1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n"


class CoreTests(unittest.TestCase):
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
        self.assertEqual(choose_output_path("Movies/Movie.mkv", lambda _: False), "Movies/Movie.srt")
        self.assertEqual(
            choose_output_path("Movies/Movie.mkv", lambda path: path.endswith("Movie.srt")),
            "Movies/Movie.zh-Hans.srt",
        )
        with self.assertRaises(PipelineError):
            choose_output_path("Movies/Movie.mkv", lambda _: True)

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

        selected = OpenSubtitles._prefer([item("en", 1), item("zh-cn", 2)])
        self.assertEqual(selected.file_id, 2)

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
        self.assertIsNone(detect_sidecar_language(video, "Movie.2026.ja.srt", "日本語です".encode()))


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

    def find(self, *_):
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
            "Movie.mkv", config(), webdav, ForbiddenOpenSubtitles(), lambda *_: None, syncer=copy_sync
        )
        self.assertTrue(result["existing"])
        self.assertEqual(result["outputPath"], entry.path)
        self.assertEqual(webdav.hash_calls, 0)
        self.assertEqual(webdav.uploads, {})

    def test_existing_english_sidecar_is_translated_to_language_output(self):
        webdav = FakeWebDAV()
        entry = FileEntry("Movie.en.srt", "Movie.en.srt", "file", len(SRT))
        webdav.sidecar_entries = [entry]
        webdav.sidecar_data[entry.path] = SRT

        class ForbiddenOpenSubtitles:
            def find(self, *_):
                raise AssertionError("Existing English must skip OpenSubtitles")

        def translator(source, destination, _):
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

        def forbidden_ai(*_):
            raise AssertionError("Chinese subtitles must not call AI")

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            FakeOpenSubtitles("zh-cn"),
            lambda *_: None,
            syncer=copy_sync,
            translator=forbidden_ai,
        )
        self.assertEqual(result["outputPath"], "Movie.srt")
        self.assertEqual(webdav.uploads["Movie.srt"], SRT)

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
        )
        self.assertEqual(len(sync_calls), 2)

    def test_english_flow_translates_before_upload(self):
        webdav = FakeWebDAV()

        def translator(source, destination, _):
            destination.write_text(source.read_text() + "\nTranslated", encoding="utf-8")
            return {"promptTokens": 10, "completionTokens": 5, "totalTokens": 15}

        result = process_video(
            "Movie.mkv",
            config(),
            webdav,
            FakeOpenSubtitles("en"),
            lambda *_: None,
            syncer=copy_sync,
            translator=translator,
        )
        self.assertIn(b"Translated", webdav.uploads["Movie.srt"])
        self.assertEqual(result["aiUsage"]["totalTokens"], 15)

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

    def test_create_job_validates_paths_and_keeps_order(self):
        with patch("backend.app.require_services"), patch("backend.app.EXECUTOR.submit"):
            for paths in ([], ["Movie.mkv", "./Movie.mkv"], ["../Movie.mkv"]):
                with self.subTest(paths=paths), self.assertRaises(HTTPException) as raised:
                    create_job(JobRequest(paths=paths))
                self.assertEqual(raised.exception.status_code, 400)

            response = create_job(JobRequest(paths=["B.mkv", "A.mkv"]))
            self.assertEqual([item.path for item in JOBS[response["jobId"]].items], ["B.mkv", "A.mkv"])
            with self.assertRaises(HTTPException) as raised:
                create_job(JobRequest(paths=["C.mkv"]))
            self.assertEqual(raised.exception.status_code, 409)

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
