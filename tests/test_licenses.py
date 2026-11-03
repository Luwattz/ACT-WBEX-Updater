"""Verify offline legal assets survive packaging and export without data loss."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import wbex_updater_licenses as legal
from tools import wbex_updater_app as app
from tools import build_wbex_updater as builder


class LicenseTests(unittest.TestCase):
    def test_upstream_texts_match_recorded_original_hashes(self):
        root = legal.license_directory()
        records = json.loads((root / "licenses/SOURCES.json").read_text())
        self.assertGreaterEqual(len(records), 13)
        for name, record in records.items():
            with self.subTest(name=name):
                self.assertTrue(record["url"].startswith("https://"))
                self.assertEqual(record["sha256"], hashlib.sha256(
                    (root / "licenses" / name).read_bytes()).hexdigest())
        self.assertEqual((root / "LICENSE.txt").read_bytes(),
                         (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes())

    def test_cli_export_is_complete_offline_and_does_not_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "许可证"
            with patch.object(app, "update", side_effect=AssertionError("must not install")):
                self.assertEqual(0, app.main(["--export-licenses", str(destination)]))
            root = legal.license_directory()
            for source in legal.license_files():
                self.assertEqual(source.read_bytes(), (destination / source.relative_to(root)).read_bytes())
            original = (destination / "LICENSE.txt").read_bytes()
            with self.assertRaises(FileExistsError):
                legal.export_licenses(destination)
            self.assertEqual(original, (destination / "LICENSE.txt").read_bytes())

    def test_frozen_lookup_uses_embedded_assets_without_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "legal"
            legal.export_licenses(destination)
            with patch.object(legal.sys, "frozen", True, create=True), patch.object(
                    legal.sys, "_MEIPASS", temporary, create=True):
                self.assertEqual(destination, legal.license_directory())
                content = legal.license_text()
                for text in ("Intelligent Efficiency Team", "Python Software Foundation",
                             "Julian R Seward", "Stefan Krah", "Bootloader Exception",
                             "Apache License", "Anthony Green"):
                    self.assertIn(text, content)

    def test_both_build_modes_embed_legal_directory(self):
        for mode in ("onedir", "onefile"):
            command = builder.pyinstaller_command(Path("stage"), Path("temporary"), mode)
            self.assertIn(str(Path("temporary/legal")) + builder.os.pathsep + "legal", command)
