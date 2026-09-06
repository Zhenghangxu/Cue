import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.app import FileEntry, PipelineError, WebDAV, sync_subtitle
from backend.audio_sample import extract_audio
from backend.media_range import memory_media
from tests.test_app import config


@unittest.skipUnless(os.getenv("RUN_MEDIA_INTEGRATION") == "1", "set RUN_MEDIA_INTEGRATION=1 for FFmpeg/ffsubsync smoke test")
class MediaIntegrationTest(unittest.TestCase):
    def test_remote_sample_matches_local_without_full_transfer(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not shutil.which("ffsubsync"):
            self.skipTest("FFmpeg and ffsubsync are required")

        def run(*args):
            return subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *args],
                                  check=True, capture_output=True, timeout=60).stdout

        with tempfile.TemporaryDirectory(prefix="subtitle-media-test-") as directory:
            root = Path(directory)
            original = root / "tail-index.mp4"
            shifted = root / "shifted.srt"
            shifted.write_text("1\n00:00:02,000 --> 00:00:04,000\nTest dialogue\n\n"
                               "2\n00:09:50,000 --> 00:09:52,000\nLate dialogue\n\n", encoding="utf-8")
            # A ten-minute container with its MP4 index at the end exercises
            # backward seeks. Nontrivial video data makes transfer assertions
            # meaningful; a tiny black video would fit in a single cache block.
            run("-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=600",
                "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=16000:duration=600",
                "-c:v", "mpeg4", "-q:v", "3", "-c:a", "aac", "-shortest", str(original))
            faststart = root / "faststart.mp4"
            embedded = root / "embedded.mkv"
            run("-i", str(original), "-c", "copy", "-movflags", "+faststart", str(faststart))
            run("-i", str(original), "-i", str(shifted), "-map", "0", "-map", "1", "-c", "copy", str(embedded))

            class RangeHandler(BaseHTTPRequestHandler):
                transferred = 0
                full_gets = 0
                ranges = []

                def log_message(self, *_):
                    pass

                def do_GET(self):
                    video = root / self.path.lstrip("/")
                    size = video.stat().st_size
                    header = self.headers.get("Range")
                    if not header:
                        RangeHandler.full_gets += 1
                        self.send_error(400)
                        return
                    start, end = map(int, header[6:].split("-"))
                    RangeHandler.ranges.append((start, end))
                    self.send_response(206)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    with video.open("rb") as media:
                        media.seek(start)
                        data = media.read(end - start + 1)
                    RangeHandler.transferred += len(data)
                    self.wfile.write(data)

            server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cfg = replace(config(), webdav_endpoint=f"http://127.0.0.1:{server.server_port}/", webdav_scan_path="")
            source = WebDAV(cfg)
            try:
                for video in (original, faststart, embedded):
                    with self.subTest(container=video.name):
                        RangeHandler.transferred = RangeHandler.full_gets = 0
                        RangeHandler.ranges = []
                        local_output = root / f"{video.stem}-local.srt"
                        remote_output = root / f"{video.stem}-remote.srt"
                        # Force the same audio reference locally; the MKV also
                        # contains subtitles which must not trigger a full scan.
                        local_audio = extract_audio(str(video))
                        with memory_media(local_audio) as audio_url:
                            subprocess.run([
                                shutil.which("ffsubsync"), audio_url, "-i", str(shifted), "-o", str(local_output),
                                "--max-duration-seconds", "195", "--frame-rate", "8000",
                                "--skip-sync-on-low-quality", "--reference-stream", "0:a:0",
                                "--no-fix-framerate", "--skip-infer-framerate-ratio",
                            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=60)
                        info = FileEntry(video.name, video.name, "video", video.stat().st_size)
                        with patch.object(source, "file_info", return_value=info):
                            started = time.monotonic()
                            with source.sync_input(video.name) as url:
                                sync_subtitle(url, shifted, remote_output, cfg)
                                elapsed = time.monotonic() - started
                                # Compare decoded samples too: a low-quality VAD
                                # skip alone could otherwise hide timing damage.
                                self.assertEqual(extract_audio(url), local_audio)
                        self.assertEqual(remote_output.read_bytes(), local_output.read_bytes())
                        self.assertEqual(RangeHandler.full_gets, 0)
                        self.assertEqual(len(RangeHandler.ranges), len(set(RangeHandler.ranges)))
                        self.assertLess(RangeHandler.transferred, video.stat().st_size * 0.20)
                        print(f"\n{video.name}: {elapsed:.2f}s, transferred {RangeHandler.transferred:,} / {video.stat().st_size:,} bytes")
                # A subtitle-guided seek must preserve AAC delay and the
                # original timeline, not merely work when sampling from zero.
                info = FileEntry(original.name, original.name, "video", original.stat().st_size)
                with patch.object(source, "file_info", return_value=info):
                    with source.sync_input(original.name) as url:
                        self.assertEqual(extract_audio(url, 85), extract_audio(str(original), 85))
                # Exercise the limit through actual FFmpeg requests, including
                # ffsubsync's retries/probes after a stream is cut short.
                RangeHandler.transferred = RangeHandler.full_gets = 0
                limit = 2 * 1024 * 1024
                info = FileEntry(original.name, original.name, "video", original.stat().st_size)
                with patch("backend.media_range.MAX_SYNC_BYTES", limit), patch.object(source, "file_info", return_value=info):
                    with self.assertRaisesRegex(PipelineError, "transfer limit"):
                        with source.sync_input(original.name) as url:
                            sync_subtitle(url, shifted, root / "limited.srt", cfg)
                self.assertLessEqual(RangeHandler.transferred, limit)
                self.assertEqual(RangeHandler.full_gets, 0)
            finally:
                source.client.close()
                source.media_client.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
