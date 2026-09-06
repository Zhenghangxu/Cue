"""Server deployment and media-library integrity regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import backend.app as app
from tests.test_app import config


def rename_client(name):
    content = json.dumps({'renames': [{'id': 0, 'name': name}]})
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: completion)))


class ServerUsageTests(unittest.TestCase):
    def tearDown(self):
        app.JOBS.clear()

    def test_explicit_server_hosts_and_proxy_origin(self):
        script = '''
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import patch
from backend.app import app
with TestClient(app, base_url="http://127.0.0.1:3666") as client:
    assert client.get("/api/health", headers={"Host": "media.internal"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "unknown.internal"}).status_code == 400
    with patch("backend.app.require_services", side_effect=HTTPException(status_code=503)):
        response = client.post("/api/jobs", headers={"Origin": "https://media.internal"}, json={"paths": []})
        assert response.status_code == 503, response.text
    assert client.post("/api/jobs", headers={"Origin": "https://evil.internal"}, json={"paths": []}).status_code == 403
    response = client.options("/api/jobs", headers={"Origin": "https://media.internal", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://media.internal"
'''
        result = subprocess.run(
            [sys.executable, '-c', script], capture_output=True, text=True,
            env=os.environ | {'CUE_ALLOWED_HOSTS': 'media.internal',
                              'CUE_ALLOWED_ORIGINS': 'https://media.internal'},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_job_types_keep_submission_services_after_settings_change(self):
        for kind in ('subtitles', 'rename'):
            with self.subTest(kind=kind):
                source = Mock()
                services = (config(), source, source, Mock())
                with patch.object(app, 'require_services', return_value=services), patch.object(app.EXECUTOR, 'submit') as submit:
                    if kind == 'subtitles':
                        response = app.create_job(app.JobRequest(paths=['Movie.mkv']))
                    else:
                        response = app.rename_files(app.RenameRequest(paths=['Movie.mkv'], title='Movie'))
                with patch.object(app, 'require_services', side_effect=AssertionError('Must not read new settings')), \
                     patch.object(app, 'OpenAI'), \
                     patch.object(app, 'process_video', return_value={}) as process, \
                     patch.object(app, 'smart_rename', return_value=[]) as rename:
                    callback, *args = submit.call_args.args
                    callback(*args)
                job = app.get_job(response['jobId'])
                self.assertEqual(job['status'], 'completed')
                self.assertIs((process if kind == 'subtitles' else rename).call_args.args[2 if kind == 'subtitles' else 3], source)
                self.assertNotIn('services', job)
                self.assertNotIn('ai-key', json.dumps(job))
                app.JOBS.clear()

    def test_rename_preserves_subtitle_tags_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as root:
            names = ['Old.mkv', 'Old.srt', 'Old.zh-cn.forced.srt', 'Old.en.sdh.ass', 'Other.srt', 'Oldish.srt']
            for name in names:
                Path(root, name).write_bytes(name.encode())
            result = app.smart_rename(['Old.mkv'], 'New', config(), app.LocalStorage(root), rename_client('New.mkv'))
            self.assertEqual(result, [{'from': 'Old.mkv', 'to': 'New.mkv'}])
            for name in names:
                renamed = 'New' + name[3:] if name.startswith('Old.') else name
                self.assertEqual(Path(root, renamed).read_bytes(), name.encode())
            self.assertFalse(Path(root, 'Old.mkv').exists())

    def test_subtitle_collision_leaves_video_and_subtitles_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            names = ['Old.mkv', 'Old.zh-cn.srt', 'New.zh-cn.srt']
            for name in names:
                Path(root, name).write_bytes(name.encode())
            with self.assertRaisesRegex(app.PipelineError, 'already exists'):
                app.smart_rename(['Old.mkv'], 'New', config(), app.LocalStorage(root), rename_client('New.mkv'))
            self.assertEqual(sorted(p.name for p in Path(root).iterdir()), sorted(names))
            for name in names:
                self.assertEqual(Path(root, name).read_bytes(), name.encode())

    def test_rename_failure_restores_preceding_subtitle_move(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ['Old.mkv', 'Old.srt']:
                Path(root, name).write_bytes(name.encode())
            source = app.LocalStorage(root)
            move = source.move
            def fail_video(original, destination):
                if original == 'Old.mkv':
                    raise app.PipelineError('Simulated video failure')
                move(original, destination)
            with patch.object(source, 'move', side_effect=fail_video), self.assertRaisesRegex(app.PipelineError, 'earlier moves were restored'):
                app.smart_rename(['Old.mkv'], 'New', config(), source, rename_client('New.mkv'))
            self.assertEqual(sorted(p.name for p in Path(root).iterdir()), ['Old.mkv', 'Old.srt'])

    def test_rename_reports_failed_rollback(self):
        source = Mock()
        source.sidecars.return_value = [app.FileEntry('Old.srt', 'Old.srt', 'file', 10)]
        source.exists.return_value = False
        source.move.side_effect = [None, app.PipelineError('Video move failed'), app.PipelineError('Restore failed')]
        with self.assertRaisesRegex(app.PipelineError, 'could not restore: New.srt'):
            app.smart_rename(['Old.mkv'], 'New', config(), source, rename_client('New.mkv'))
