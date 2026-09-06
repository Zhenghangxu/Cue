import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config_storage import config_path


class ConfigStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.legacy = self.home / "Library" / "Application Support" / "Cue" / "config.json"
        self.destination = self.home / ".config" / "subtitle-maker" / "config.json"

    def save_legacy(self):
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_bytes(b'{"openai_api_key": "test-secret", "target_language": "es"}\n')

    def test_fresh_install_does_not_create_empty_config(self):
        self.assertEqual(config_path(self.home), self.destination)
        self.assertFalse(self.destination.exists())

    def test_migration_preserves_original_and_survives_app_data_removal(self):
        self.save_legacy()
        original = self.legacy.read_bytes()
        self.assertEqual(config_path(self.home), self.destination)
        self.assertEqual(self.legacy.read_bytes(), original)
        self.assertEqual(self.destination.read_bytes(), original)
        if os.name != "nt":
            self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.destination.parent.stat().st_mode & 0o777, 0o700)
        self.legacy.unlink()
        self.legacy.parent.rmdir()
        self.assertEqual(config_path(self.home).read_bytes(), original)

    def test_existing_config_is_never_overwritten(self):
        self.save_legacy()
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b'{}\n')
        self.assertEqual(config_path(self.home).read_bytes(), b'{}\n')

    def test_failed_copy_preserves_legacy_without_partial_config(self):
        self.save_legacy()
        with patch("backend.config_storage.os.fsync", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                config_path(self.home)
        self.assertTrue(self.legacy.is_file())
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_concurrent_config_is_not_replaced(self):
        self.save_legacy()

        def concurrent_save(source, destination):
            destination.write_bytes(b'{"target_language": "fr"}')
            raise FileExistsError

        with patch("backend.config_storage.os.link", side_effect=concurrent_save):
            self.assertEqual(config_path(self.home).read_bytes(), b'{"target_language": "fr"}')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])
