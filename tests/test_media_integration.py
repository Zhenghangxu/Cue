import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@unittest.skipUnless(os.getenv("RUN_MEDIA_INTEGRATION") == "1", "set RUN_MEDIA_INTEGRATION=1 for FFmpeg/ffsubsync smoke test")
class MediaIntegrationTest(unittest.TestCase):
    def test_shifted_fixture_through_range_server(self):
        ffmpeg = shutil.which("ffmpeg")
        ffsubsync = shutil.which("ffsubsync")
        if not ffmpeg or not ffsubsync:
            self.skipTest("FFmpeg and ffsubsync are required")

        with tempfile.TemporaryDirectory(prefix="subtitle-media-test-") as directory:
            root = Path(directory)
            video = root / "fixture.mp4"
            shifted = root / "shifted.srt"
            output = root / "synced.srt"
            shifted.write_text(
                "1\n00:00:02,000 --> 00:00:04,000\nTest dialogue\n\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x180:r=10:d=8",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=220:sample_rate=16000:duration=8",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    "-shortest",
                    str(video),
                ],
                check=True,
            )

            class RangeHandler(BaseHTTPRequestHandler):
                ranges = 0

                def log_message(self, *_):
                    pass

                def do_HEAD(self):
                    self._send(False)

                def do_GET(self):
                    self._send(True)

                def _send(self, body):
                    data = video.read_bytes()
                    start, end, status = 0, len(data) - 1, 200
                    header = self.headers.get("Range")
                    if header and header.startswith("bytes="):
                        RangeHandler.ranges += 1
                        values = header[6:].split("-", 1)
                        start = int(values[0] or 0)
                        end = min(int(values[1]) if values[1] else len(data) - 1, len(data) - 1)
                        status = 206
                    chunk = data[start : end + 1]
                    self.send_response(status)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(chunk)))
                    if status == 206:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                    self.end_headers()
                    if body:
                        self.wfile.write(chunk)

            server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run(
                    [
                        ffsubsync,
                        f"http://127.0.0.1:{server.server_port}/fixture.mp4",
                        "-i",
                        str(shifted),
                        "-o",
                        str(output),
                        "--max-duration-seconds",
                        "5",
                        "--frame-rate",
                        "16000",
                        "--extract-audio-first",
                        "--skip-sync-on-low-quality",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=False,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(output.exists() and output.stat().st_size)
            self.assertGreater(RangeHandler.ranges, 0)


if __name__ == "__main__":
    unittest.main()
