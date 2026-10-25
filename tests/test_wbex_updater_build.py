"""Check the standalone packaging boundary without building an EXE in tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wbex_updater_build_test", ROOT / "tools" / "build_wbex_updater.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class StandaloneBuildTests(unittest.TestCase):
    def test_packaged_runtime_keeps_v241_first_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / "stage/tools"
            builder.stage_runtime(ROOT / "tools", staged)
            spec = importlib.util.spec_from_file_location(
                "staged_updater_runtime", staged / "wbex_updater_runtime.py")
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            self.assertEqual("v241", runtime.DEFAULT_ANSYS_VERSION)
            roots = [Path("Ansys/v261"), Path("Ansys/v241")]
            self.assertEqual(roots[1], runtime.select_default_ansys_root(roots))
            self.assertEqual(roots[0], runtime.select_default_ansys_root(roots[:1]))

    def test_staging_excludes_repository_and_plugin_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            for name in builder.RUNTIME_SOURCES:
                (tools / name).write_text("# updater runtime\n", encoding="utf-8")
            assets = tools / "assets" / "wbex-updater"
            assets.mkdir(parents=True)
            for name in builder.RUNTIME_ASSETS:
                (assets / name).write_bytes(b"runtime icon fixture")
            (assets / "updater-master.png").write_bytes(b"do not bundle the design master")
            (tools / "build_wbex.py").write_text("# build tooling\n", encoding="utf-8")
            (tools / "secret.py").write_text("# plugin source\n", encoding="utf-8")
            plugin = tools / "LumiDyna"
            plugin.mkdir()
            (plugin / "main.py").write_text("# plugin\n", encoding="utf-8")
            staged = root / "stage" / "tools"
            builder.stage_runtime(tools, staged)
            self.assertEqual(set(builder.RUNTIME_SOURCES), {p.name for p in staged.iterdir() if p.is_file()})
            self.assertEqual(set(builder.RUNTIME_ASSETS),
                             {p.name for p in (staged / "assets/wbex-updater").iterdir()})

    def test_pyinstaller_defaults_to_folder_with_optional_single_file(self):
        command = builder.pyinstaller_command(Path("stage/tools"), Path("temporary"))
        self.assertIn("--onedir", command)
        self.assertNotIn("--onefile", command)
        single = builder.pyinstaller_command(Path("stage/tools"), Path("temporary"), "onefile")
        self.assertIn("--onefile", single)
        self.assertNotIn("--onedir", single)
        self.assertIn("--windowed", command)
        icon = Path("stage/tools/assets/wbex-updater/updater.ico")
        self.assertEqual(str(icon), command[command.index("--icon") + 1])
        self.assertEqual(str(icon) + builder.os.pathsep + "updater_assets", command[command.index("--add-data") + 1])
        self.assertEqual("ACT_WBEX_Updater", command[command.index("--name") + 1])
        for module in ("build_wbex", "check_wbex_release", "LumiDyna"):
            self.assertIn(module, command)

    def test_both_release_modes_embed_dpi_awareness(self):
        for mode in ("onedir", "onefile"):
            command = builder.pyinstaller_command(Path("stage/tools"), Path("temporary"), mode)
            xml = command[command.index("--manifest") + 1]
            self.assertNotIn("\n", xml, "Inline XML must survive PyInstaller's spec quoting")
            manifest = ET.fromstring(xml)
            self.assertEqual("true", manifest.find(
                ".//{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware").text)
            self.assertEqual("system", manifest.find(
                ".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness").text)
            self.assertEqual("true", manifest.find(
                ".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}longPathAware").text)

    def test_folder_publication_replaces_old_runtime_and_restores_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "release"
            source.mkdir()
            (source / "new.dll").write_bytes(b"new")
            destination.mkdir()
            (destination / "old.dll").write_bytes(b"old")
            replace = builder.os.replace

            def fail_new_release(src, dst):
                if Path(src).name.endswith(".tmp"):
                    raise OSError("simulated locked release")
                return replace(src, dst)

            with patch.object(builder.os, "replace", side_effect=fail_new_release):
                with self.assertRaisesRegex(OSError, "locked release"):
                    builder.publish_folder(source, destination)
            self.assertEqual(b"old", (destination / "old.dll").read_bytes())
            builder.publish_folder(source, destination)
            self.assertEqual(["new.dll"], [p.name for p in destination.iterdir()])
            self.assertEqual({"source", "release"}, {p.name for p in root.iterdir()})

    def test_build_audit_rejects_plugin_module_before_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toc = root / "PYZ-00.toc"
            toc.write_text(repr([("update_wbex", "update_wbex.py", "PYMODULE"),
                                 ("LumiDyna.main", "main.py", "PYMODULE")]), encoding="utf-8")
            with self.assertRaisesRegex(builder.StandaloneBuildError, "LumiDyna.main"):
                builder.verify_module_boundary(root)
            toc.write_text(repr([("update_wbex", "update_wbex.py", "PYMODULE")]), encoding="utf-8")
            builder.verify_module_boundary(root)


if __name__ == "__main__":
    unittest.main()
