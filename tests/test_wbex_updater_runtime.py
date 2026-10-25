"""Standalone updater discovery and embedded ZIP validation contracts."""
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tools import wbex_updater_runtime as runtime


def resource_zip(name="content", content=b"test resource"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, content)
    return stream.getvalue()


class UpdaterRuntimeTests(unittest.TestCase):
    def installation(self, root):
        binaries = root / "Framework/bin/Win64"
        binaries.mkdir(parents=True)
        (binaries / "RunWB2.bat").write_bytes(b"fixture")
        (binaries / "AnsysFW.exe").write_bytes(b"fixture")
        return root

    def test_updater_import_does_not_load_builder_or_extension_modules(self):
        root = Path(__file__).resolve().parents[1]
        script = ("import json,sys;sys.path.insert(0," + repr(str(root)) + ");"
                  "import tools.update_wbex;"
                  "print(json.dumps(sorted(name for name in sys.modules "
                  "if name.startswith(('tools.', 'LumiDyna')))))")
        result = subprocess.run([sys.executable, "-I", "-c", script],
                                capture_output=True, text=True, check=True)
        self.assertEqual(["tools.update_wbex", "tools.wbex_updater_runtime"],
                         json.loads(result.stdout))

    def test_discovery_checks_explicit_root_and_prefers_valid_v241_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "v241")
            new = self.installation(root / "v251")
            self.assertEqual(old.resolve(), runtime.discover_ansys_root(old, {}))
            self.assertEqual(old.resolve(), runtime.discover_ansys_root(environ={
                "AWP_ROOT241": str(old), "awp_root251": str(new),
                "AWP_ROOT261": str(root / "missing"),
            }))
            with self.assertRaises(runtime.BuildError):
                runtime.discover_ansys_root(root / "missing", {"AWP_ROOT241": str(old)})

    def test_discovery_falls_back_to_program_files_and_requires_both_host_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "main/ANSYS Inc/v241")
            new = self.installation(root / "alternate/ANSYS Inc/v251")
            incomplete = self.installation(root / "main/ANSYS Inc/v261")
            (incomplete / "Framework/bin/Win64/AnsysFW.exe").unlink()
            self.assertEqual(old.resolve(), runtime.discover_ansys_root(environ={
                "ProgramFiles": str(root / "main"),
                "ProgramFiles(x86)": str(root / "alternate"),
            }))
            with self.assertRaises(runtime.BuildError):
                runtime.discover_ansys_root(environ={})
            self.assertTrue(old.is_dir())

    def test_discovery_merges_older_environment_and_newer_program_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "custom/ANSYS Inc/v241")
            new = self.installation(root / "programs/ANSYS Inc/v261")
            environ = {
                "AWP_ROOT241": str(old),
                "ProgramFiles": str(root / "programs"),
            }
            self.assertEqual([new.resolve(), old.resolve()],
                             runtime.discover_ansys_roots(environ))
            self.assertEqual(old.resolve(), runtime.discover_ansys_root(environ=environ))
            self.assertEqual(old.resolve(), runtime.discover_ansys_root(old, environ))
            self.assertEqual(new.resolve(), runtime.discover_ansys_root(new, environ))

    def test_default_selection_falls_back_to_newest_when_v241_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "custom/v251")
            new = self.installation(root / "programs/ANSYS Inc/v261")
            environ = {
                "AWP_ROOT251": str(old),
                "ProgramFiles": str(root / "programs"),
            }
            self.assertEqual(new.resolve(), runtime.discover_ansys_root(environ=environ))
            self.assertEqual(new.resolve(), runtime.select_default_ansys_root(
                runtime.discover_ansys_roots(environ)))
            self.assertIsNone(runtime.select_default_ansys_root([]))

    def test_default_selection_ignores_invalid_v241_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = self.installation(root / "custom/v241")
            (invalid / "Framework/bin/Win64/AnsysFW.exe").unlink()
            new = self.installation(root / "programs/ANSYS Inc/v261")
            environ = {
                "AWP_ROOT241": str(invalid),
                "ProgramFiles": str(root / "programs"),
            }
            self.assertEqual([new.resolve()], runtime.discover_ansys_roots(environ))
            self.assertEqual(new.resolve(), runtime.discover_ansys_root(environ=environ))

    def test_default_selection_prefers_v241_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferred = self.installation(root / "custom/V241")
            newest = self.installation(root / "custom/v261")
            self.assertEqual(preferred, runtime.select_default_ansys_root([newest, preferred]))

    def test_discovery_supports_environment_only_custom_installation_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "drive-d/engineering/v241")
            new = self.installation(root / "drive-e/applications/v261")
            self.assertEqual([new.resolve(), old.resolve()], runtime.discover_ansys_roots({
                "AWP_ROOT241": str(old), "awp_root261": str(new),
            }))

    def test_discovery_sorts_actual_versions_numerically_and_skips_invalid_newest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "programs/ANSYS Inc/v99")
            new = self.installation(root / "programs/ANSYS Inc/v261")
            incomplete = self.installation(root / "programs/ANSYS Inc/v271")
            (incomplete / "Framework/bin/Win64/RunWB2.bat").unlink()
            self.assertEqual([new.resolve(), old.resolve()], runtime.discover_ansys_roots({
                "AWP_ROOT999": str(old),
                "AWP_ROOT271": str(incomplete),
                "ProgramFiles": str(root / "programs"),
            }))
            self.assertEqual([], runtime.discover_ansys_roots({}))

    def test_discovery_deduplicates_resolved_paths_across_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            new = self.installation(root / "programs/ANSYS Inc/v261")
            self.assertEqual([new.resolve()], runtime.discover_ansys_roots({
                "AWP_ROOT261": str(new),
                "AWP_ROOT251": str(new.parent / "unused" / ".." / new.name),
                "AWP_ROOT271": str(new).upper(),
                "ProgramFiles": str(root / "programs"),
                "ProgramFiles(x86)": str(root / "programs"),
                "ProgramW6432": str(root / "programs"),
            }))

    def test_discovery_scans_native_program_files_from_32_bit_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self.installation(root / "x86/ANSYS Inc/v241")
            new = self.installation(root / "native/ANSYS Inc/v261")
            self.assertEqual([new.resolve(), old.resolve()], runtime.discover_ansys_roots({
                "ProgramFiles": str(root / "x86"),
                "ProgramW6432": str(root / "native"),
            }))

    def test_scanner_reads_multiple_embedded_archives_far_from_package_end(self):
        first = resource_zip(content=b"definition")
        second = resource_zip("Demo/Wizard.html", b"resource")
        payload = runtime.HDF5_SIGNATURE + first + b"\x00" * 100 + second + b"\x00" * 70000
        archives = runtime.embedded_archives(payload)
        try:
            self.assertEqual(2, len(archives))
            self.assertEqual(b"definition", archives[0][2].read("content"))
            self.assertEqual(b"resource", archives[1][2].read("Demo/Wizard.html"))
        finally:
            for _, _, archive in archives:
                archive.close()

    def test_scanner_rejects_missing_or_uninspected_resource_records(self):
        for payload in (runtime.HDF5_SIGNATURE,
                        runtime.HDF5_SIGNATURE + resource_zip() + b"PK\x03\x04orphan"):
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(ValueError):
                    runtime.embedded_archives(payload)

    def test_scanner_rejects_multipart_and_inconsistent_directory_counts(self):
        for offset, value in ((4, 1), (8, 2), (10, 2)):
            payload = bytearray(resource_zip())
            eocd = payload.rfind(b"PK\x05\x06")
            struct.pack_into("<H", payload, eocd + offset, value)
            with self.subTest(offset=offset):
                with self.assertRaises(ValueError):
                    runtime.embedded_archives(runtime.HDF5_SIGNATURE + payload)


if __name__ == "__main__":
    unittest.main()
