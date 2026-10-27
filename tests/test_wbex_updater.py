"""Exercise WBEX replacement against disposable ANSYS profiles only."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from tools import wbex_updater_runtime as audit
from tools import update_wbex as updater


FULL_GUID = "879A7BFE-A5BA-4C02-A8BC-870294861822"
LITE_GUID = "1D70522C-F618-4B9E-9819-927A5C39A7BB"
DEMO_GUID = "C5138581-40D8-4658-A68F-38B5703B868A"


def native_package(entries):
    """ACT stores independent resource ZIPs inside its HDF5 container."""
    payload = audit.HDF5_SIGNATURE + b"\x00" * 100
    for name, content in entries:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, content)
        payload += stream.getvalue() + b"\x00" * 4
    return payload + b"\x00" * 70000


def default_entry(name="Demo", guid=DEMO_GUID, shortid="Demo", major=2, minor=3):
    return "1;{};{};{};wbex;{};{}".format(name, guid.lower(), shortid, major, minor)


class WbexUpdaterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "Ansys/v241"
        self.extensions = self.profile / "ACT/extensions"
        self.extensions.mkdir(parents=True)
        self.preferences = self.profile / "UserRegFiles_123/ACTPreferences.xml"
        self.preferences.parent.mkdir()
        self.ansys_root = self.root / "installation/v241"
        binaries = self.ansys_root / "Framework/bin/Win64"
        binaries.mkdir(parents=True)
        (binaries / "RunWB2.bat").write_bytes(b"@echo off\r\n")
        (binaries / "AnsysFW.exe").write_bytes(b"mock Workbench binary")
        self.sources = self.root / "packages"
        self.sources.mkdir()
        self.write_preferences([])
        self.processes = patch.object(updater, "active_ansys_processes", return_value=[])
        self.processes.start()
        self.addCleanup(self.processes.stop)

    def package(self, path=None, name="Demo", guid=DEMO_GUID, shortid="Demo",
                major=2, minor=3, assets=None):
        path = path or self.sources / "Demo.wbex"
        definition = ET.Element("extension", name=name, version=str(major),
                                minorversion=str(minor))
        ET.SubElement(definition, "guid", shortid=shortid).text = guid
        ET.SubElement(definition, "script", src="main.py", compiled="true")
        entries = [("content", ET.tostring(definition, encoding="utf-8")),
                   ("content", b"compiled script buffer, not an extracted asset")]
        resources = assets if assets is not None else {
            name + "/Wizard.html": b"<html><body>new wizard</body></html>",
            name + "/images/icon.png": b"\x89PNG\r\nfixture",
        }
        entries.extend(resources.items())
        path.write_bytes(native_package(entries))
        return path

    def write_preferences(self, entries):
        root = ET.Element("KEYS")
        act = ET.SubElement(root, "KEY", ObjectName="ACTPreferences", RegObjectType="0")
        keys = ET.SubElement(act, "KEYS")
        preferences = ET.SubElement(keys, "KEY", ObjectName="PreferenceValues", RegObjectType="0")
        values = ET.SubElement(preferences, "VALUES")
        for key, value in (
                ("ACT_AdditionalExtensionsFolders", "C:\\source\\full;C:\\source\\lite"),
                ("ACT_DebugMode", "True"),
                ("ACT_DefaultExtensions", "|".join(entries)),
                ("ACT_SeenDefaultExtensions", "leave this unrelated history unchanged")):
            ET.SubElement(values, "VALUE", ObjectName=key, Value=value, ValueType="2")
        self.preferences.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))

    def preference_values(self):
        return {node.get("ObjectName"): node.get("Value")
                for node in ET.parse(self.preferences).iter("VALUE")}

    def run_update(self, package, **kwargs):
        options = {"ansys_root": self.ansys_root, "profile_dir": self.profile,
                   "preferences_file": self.preferences, "notify": lambda message: None}
        options.update(kwargs)
        return updater.update(package, **options)

    def snapshot(self, path):
        if not path.exists():
            return None
        return {item.relative_to(path).as_posix(): (None if item.is_dir() else item.read_bytes())
                for item in path.rglob("*")}

    def old_installation(self, stem="old-name", **kwargs):
        package = self.package(self.extensions / (stem + ".wbex"), **kwargs)
        resources = self.extensions / stem
        resources.mkdir()
        (resources / "Wizard.html").write_bytes(b"old wizard " + stem.encode("ascii"))
        (resources / "stale.txt").write_bytes(b"old files must not survive replacement")
        return package, resources

    def version_fixture(self, token, installation=None):
        installation = installation or self.root / "installation" / token
        binaries = installation / "Framework/bin/Win64"
        binaries.mkdir(parents=True)
        (binaries / "RunWB2.bat").write_bytes(b"@echo off\r\n")
        (binaries / "AnsysFW.exe").write_bytes(b"mock Workbench " + token.encode("ascii"))
        profile = self.root / "Ansys" / token
        extensions = profile / "ACT/extensions"
        extensions.mkdir(parents=True)
        preferences = profile / "UserRegFiles_456/ACTPreferences.xml"
        preferences.parent.mkdir()
        preferences.write_bytes(self.preferences.read_bytes())
        return installation, profile, extensions, preferences

    def test_inspect_reads_identity_and_flattens_assets_but_not_content_buffers(self):
        package = self.package(self.sources / "renamed release.wbex")
        actual = updater.inspect_package(package)
        self.assertEqual("Demo", actual.name)
        self.assertEqual(DEMO_GUID.lower(), actual.guid.lower())
        self.assertEqual("Demo", actual.shortid)
        self.assertEqual((2, 3), (int(actual.major), int(actual.minor)))
        self.assertEqual({"Wizard.html": b"<html><body>new wizard</body></html>",
                          "images/icon.png": b"\x89PNG\r\nfixture"}, actual.files)
        self.assertEqual(default_entry(), actual.default_entry)

    def test_initial_install_uses_package_stem_and_preserves_other_preferences(self):
        package = self.package(self.sources / "release-candidate.wbex")
        previous_values = self.preference_values()
        report = self.run_update(package)
        self.assertEqual(package.read_bytes(),
                         (self.extensions / package.name).read_bytes())
        installed = self.extensions / package.stem
        self.assertEqual(b"<html><body>new wizard</body></html>",
                         (installed / "Wizard.html").read_bytes())
        self.assertEqual({"Wizard.html", "images", "images/icon.png"},
                         set(self.snapshot(installed)))
        current_values = self.preference_values()
        self.assertEqual(default_entry(), current_values.pop("ACT_DefaultExtensions"))
        previous_values.pop("ACT_DefaultExtensions")
        self.assertEqual(previous_values, current_values)
        self.assertFalse(report["dry_run"])
        self.assertEqual("Demo", report["package"]["name"])
        self.assertEqual(DEMO_GUID.lower(), report["package"]["guid"])
        self.assertEqual("2.3", report["package"]["version"])
        self.assertEqual(self.extensions / package.name, Path(report["installed_file"]))
        self.assertEqual(installed, Path(report["installed_folder"]))

    def test_explicit_v261_updates_only_its_user_profile(self):
        self.old_installation("v241-must-remain", minor=1)
        self.write_preferences([default_entry(minor=1)])
        installation, profile, extensions, preferences = self.version_fixture("v261")
        before_v241 = self.snapshot(self.profile)
        before_v261_preferences = preferences.read_bytes()
        package = self.package()
        with patch.dict(os.environ, {"APPDATA": str(self.root)}, clear=True):
            report = updater.update(package, ansys_root=installation, notify=lambda message: None)
        self.assertEqual("v261", report["ansys_version"])
        self.assertEqual(profile.resolve(), Path(report["profile_dir"]))
        self.assertEqual(installation.resolve(), Path(report["ansys_root"]))
        self.assertEqual(package.read_bytes(), (extensions / package.name).read_bytes())
        self.assertEqual(b"<html><body>new wizard</body></html>",
                         (extensions / package.stem / "Wizard.html").read_bytes())
        actual_default = next(node.get("Value") for node in ET.parse(preferences).iter("VALUE")
                              if node.get("ObjectName") == "ACT_DefaultExtensions")
        self.assertEqual(default_entry(), actual_default)
        self.assertNotEqual(before_v261_preferences, preferences.read_bytes())
        self.assertEqual(before_v241, self.snapshot(self.profile))

    def test_auto_detection_prefers_installed_v241_and_preserves_newer_profile(self):
        self.old_installation("v241-old-release", minor=1)
        self.write_preferences([default_entry(minor=1)])
        program_files = self.root / "Program Files"
        _, newer_profile, newer_extensions, _ = self.version_fixture(
            "v261", installation=program_files / "ANSYS Inc/v261")
        self.package(newer_extensions / "v261-must-remain.wbex", minor=8)
        before_v261 = self.snapshot(newer_profile)
        package = self.package()
        environment = {"APPDATA": str(self.root), "AWP_ROOT241": str(self.ansys_root),
                       "ProgramFiles": str(program_files)}
        with patch.dict(os.environ, environment, clear=True):
            report = updater.update(package, notify=lambda message: None)
        self.assertEqual("v241", report["ansys_version"])
        self.assertEqual(self.ansys_root.resolve(), Path(report["ansys_root"]))
        self.assertEqual(self.profile.resolve(), Path(report["profile_dir"]))
        self.assertEqual(package.read_bytes(), (self.extensions / package.name).read_bytes())
        self.assertFalse((self.extensions / "v241-old-release.wbex").exists())
        self.assertEqual(default_entry(), self.preference_values()["ACT_DefaultExtensions"])
        self.assertEqual(before_v261, self.snapshot(newer_profile))

    def test_auto_detection_falls_back_to_latest_when_v241_is_missing_or_invalid(self):
        self.old_installation("v241-profile-must-remain", minor=1)
        self.write_preferences([default_entry(minor=1)])
        program_files = self.root / "Program Files"
        installation, profile, extensions, preferences = self.version_fixture(
            "v261", installation=program_files / "ANSYS Inc/v261")
        _, older_profile, _, _ = self.version_fixture(
            "v251", installation=program_files / "ANSYS Inc/v251")
        before_v241 = self.snapshot(self.profile)
        before_v251 = self.snapshot(older_profile)
        # The v241 user profile may remain even when its installation has gone.
        (self.ansys_root / "Framework/bin/Win64/AnsysFW.exe").unlink()
        package = self.package()
        for state in ("missing", "invalid"):
            with self.subTest(v241=state):
                environment = {"APPDATA": str(self.root), "ProgramFiles": str(program_files)}
                if state == "invalid":
                    environment["AWP_ROOT241"] = str(self.ansys_root)
                with patch.dict(os.environ, environment, clear=True):
                    report = updater.update(package, notify=lambda message: None)
                self.assertEqual("v261", report["ansys_version"])
                self.assertEqual(installation.resolve(), Path(report["ansys_root"]))
                self.assertEqual(profile.resolve(), Path(report["profile_dir"]))
                self.assertEqual(package.read_bytes(), (extensions / package.name).read_bytes())
                actual_default = next(node.get("Value") for node in ET.parse(preferences).iter("VALUE")
                                      if node.get("ObjectName") == "ACT_DefaultExtensions")
                self.assertEqual(default_entry(), actual_default)
                self.assertEqual(before_v241, self.snapshot(self.profile))
                self.assertEqual(before_v251, self.snapshot(older_profile))

    def test_manual_v241_selection_overrides_newer_detection_without_touching_v261(self):
        self.old_installation("v241-old-release", minor=1)
        self.write_preferences([default_entry(minor=1)])
        program_files = self.root / "Program Files"
        _, newer_profile, newer_extensions, _ = self.version_fixture(
            "v261", installation=program_files / "ANSYS Inc/v261")
        self.package(newer_extensions / "v261-package.wbex", minor=8)
        newer_resources = newer_extensions / "v261-package"
        newer_resources.mkdir()
        (newer_resources / "Wizard.html").write_bytes(b"v261 must remain untouched")
        before_v261 = self.snapshot(newer_profile)
        package = self.package()
        environment = {"APPDATA": str(self.root), "AWP_ROOT241": str(self.ansys_root),
                       "ProgramFiles": str(program_files)}
        with patch.dict(os.environ, environment, clear=True):
            report = updater.update(package, ansys_root=self.ansys_root, notify=lambda message: None)
        self.assertEqual("v241", report["ansys_version"])
        self.assertEqual(self.ansys_root.resolve(), Path(report["ansys_root"]))
        self.assertEqual(self.profile.resolve(), Path(report["profile_dir"]))
        self.assertEqual(package.read_bytes(), (self.extensions / package.name).read_bytes())
        self.assertFalse((self.extensions / "v241-old-release.wbex").exists())
        self.assertEqual(default_entry(), self.preference_values()["ACT_DefaultExtensions"])
        self.assertEqual(before_v261, self.snapshot(newer_profile))

    def test_upgrade_matches_guid_across_renames_and_preserves_lite(self):
        old_a, resources_a = self.old_installation("former-full", name="LumiDyna",
                                                  guid=FULL_GUID, shortid="LumiDynaFull", minor=1)
        old_b, resources_b = self.old_installation("duplicate-full", name="LumiDyna",
                                                  guid=FULL_GUID, shortid="LumiDynaFull", minor=2)
        lite, lite_resources = self.old_installation("LumiDynaLite", name="LumiDynaLite",
                                                     guid=LITE_GUID, shortid="LumiDyna",
                                                     major=1, minor=9)
        preserved_lite = self.snapshot(lite_resources)
        lite_bytes = lite.read_bytes()
        old_bytes = {old_a.name: old_a.read_bytes(), old_b.name: old_b.read_bytes()}
        lite_entry = default_entry("LumiDynaLite", LITE_GUID, "LumiDyna", 1, 9)
        self.write_preferences([default_entry("LumiDyna", FULL_GUID, "LumiDynaFull", 2, 1),
                                lite_entry,
                                default_entry("LumiDyna", FULL_GUID, "LumiDynaFull", 2, 2)])
        new = self.package(self.sources / "LumiDyna-new.wbex", name="LumiDyna",
                           guid=FULL_GUID, shortid="LumiDynaFull", minor=4)
        report = self.run_update(new)
        self.assertFalse(old_a.exists())
        self.assertFalse(old_b.exists())
        self.assertFalse(resources_a.exists())
        self.assertFalse(resources_b.exists())
        self.assertEqual(lite_bytes, lite.read_bytes())
        self.assertEqual(preserved_lite, self.snapshot(lite_resources))
        self.assertEqual(new.read_bytes(), (self.extensions / new.name).read_bytes())
        self.assertFalse((self.extensions / new.stem / "stale.txt").exists())
        entries = self.preference_values()["ACT_DefaultExtensions"].split("|")
        self.assertEqual({lite_entry, default_entry("LumiDyna", FULL_GUID, "LumiDynaFull", 2, 4)},
                         set(entries))
        self.assertEqual(2, len(entries))
        self.assertEqual({str(old_a), str(old_b), str(resources_a), str(resources_b)},
                         set(report["replaced"]))
        backup = Path(report["backup"])
        self.assertTrue(backup.is_dir())
        self.assertNotIn(self.extensions.resolve(), backup.resolve().parents)
        saved = {path.name: path.read_bytes() for path in backup.rglob("*.wbex")}
        for name, content in old_bytes.items():
            self.assertEqual(content, saved[name])
        self.assertGreaterEqual(len(list(backup.rglob("stale.txt"))), 2)

    def test_unrelated_package_with_same_filename_gets_collision_free_install(self):
        other, resources = self.old_installation("Demo", name="LumiDynaLite",
                                                  guid=LITE_GUID, shortid="LumiDyna",
                                                  major=1, minor=9)
        old_package, old_resources = other.read_bytes(), self.snapshot(resources)
        other_entry = default_entry("LumiDynaLite", LITE_GUID, "LumiDyna", 1, 9)
        self.write_preferences([other_entry])
        package = self.package()
        report = self.run_update(package)
        self.assertEqual(old_package, other.read_bytes())
        self.assertEqual(old_resources, self.snapshot(resources))
        self.assertEqual(self.extensions / "Demo1.wbex", Path(report["installed_file"]))
        self.assertEqual(self.extensions / "Demo1", Path(report["installed_folder"]))
        self.assertEqual(package.read_bytes(), (self.extensions / "Demo1.wbex").read_bytes())
        self.assertEqual({other_entry, default_entry()},
                         set(self.preference_values()["ACT_DefaultExtensions"].split("|")))
        self.assertEqual([], report["replaced"])

    def test_generic_extension_name_change_still_matches_same_guid(self):
        old, old_resources = self.old_installation("former-package", name="FormerName")
        self.write_preferences([default_entry("FormerName")])
        package = self.package(name="RenamedExtension")
        report = self.run_update(package)
        self.assertFalse(old.exists())
        self.assertFalse(old_resources.exists())
        self.assertEqual(default_entry("RenamedExtension"),
                         self.preference_values()["ACT_DefaultExtensions"])
        self.assertEqual({str(old), str(old_resources)}, set(report["replaced"]))

    def test_dry_run_leaves_installed_files_and_preferences_byte_identical(self):
        self.old_installation()
        new = self.package()
        before = self.snapshot(self.profile)
        report = self.run_update(new, dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(before, self.snapshot(self.profile))

    def test_scripted_extension_with_same_guid_blocks_update_without_changes(self):
        self.old_installation()
        development = self.root / "scripted-extension"
        development.mkdir()
        definition = ET.Element("extension", name="Demo", version="2", minorversion="1")
        ET.SubElement(definition, "guid", shortid="Demo").text = DEMO_GUID
        xml = development / "Demo.xml"
        xml.write_bytes(ET.tostring(definition, encoding="utf-8"))
        preferences = ET.parse(self.preferences)
        for node in preferences.iter("VALUE"):
            if node.get("ObjectName") == "ACT_AdditionalExtensionsFolders":
                node.set("Value", str(development))
        preferences.write(self.preferences, encoding="utf-8", xml_declaration=True)
        package = self.package()
        before_profile = self.snapshot(self.profile)
        before_development = self.snapshot(development)
        with self.assertRaises(updater.UpdateError):
            self.run_update(package)
        self.assertEqual(before_profile, self.snapshot(self.profile))
        self.assertEqual(before_development, self.snapshot(development))

    def test_missing_user_default_inherits_machine_defaults_and_replaces_target_guid(self):
        machine = self.ansys_root / "commonfiles/registry/winx64/ACTPreferences.xml"
        machine.parent.mkdir(parents=True)
        lite_entry = default_entry("LumiDynaLite", LITE_GUID, "LumiDyna", 1, 9)
        self.write_preferences([lite_entry, default_entry(minor=1)])
        machine.write_bytes(self.preferences.read_bytes())
        before_machine = machine.read_bytes()
        user = ET.parse(self.preferences)
        for values in user.iter("VALUES"):
            for node in list(values):
                if node.get("ObjectName") == "ACT_DefaultExtensions":
                    values.remove(node)
        user.write(self.preferences, encoding="utf-8", xml_declaration=True)
        previous_values = self.preference_values()
        self.assertNotIn("ACT_DefaultExtensions", previous_values)
        self.run_update(self.package())
        current_values = self.preference_values()
        defaults = current_values.pop("ACT_DefaultExtensions").split("|")
        self.assertEqual({lite_entry, default_entry()}, set(defaults))
        self.assertEqual(2, len(defaults))
        self.assertEqual(previous_values, current_values)
        self.assertEqual(before_machine, machine.read_bytes())

    def test_malformed_package_is_rejected_before_any_profile_change(self):
        self.old_installation()
        malformed_cases = {
            "not-hdf": b"not a WBEX",
            "no-archive": audit.HDF5_SIGNATURE + b"not an archive",
            "no-definition": native_package([("Demo/Wizard.html", b"<html>orphan</html>")]),
            "broken-definition": native_package([("content", b"<extension name='Demo'>")]),
        }
        before = self.snapshot(self.profile)
        for name, content in malformed_cases.items():
            with self.subTest(name=name):
                package = self.sources / (name + ".wbex")
                package.write_bytes(content)
                with self.assertRaises(updater.UpdateError):
                    self.run_update(package)
                self.assertEqual(before, self.snapshot(self.profile))

    def test_unsafe_asset_paths_are_rejected_before_any_profile_change(self):
        before = self.snapshot(self.profile)
        for member in ("Demo/../escape.txt", "../escape.txt", "Demo/../../escape.txt",
                       "Demo\\..\\escape.txt", "C:/escape.txt", "/escape.txt"):
            with self.subTest(member=member):
                package = self.package(assets={member: b"must never escape"})
                with self.assertRaises(updater.UpdateError):
                    self.run_update(package)
                self.assertEqual(before, self.snapshot(self.profile))
                self.assertFalse((self.profile / "escape.txt").exists())

    def test_damaged_resource_crc_is_rejected_before_installed_changes(self):
        self.old_installation()
        package = self.package(assets={})
        stream = io.BytesIO()
        marker = b"resource fixture with an intentionally damaged CRC"
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("Demo/Wizard.html", marker)
        damaged = bytearray(stream.getvalue())
        offset = damaged.find(marker)
        self.assertGreaterEqual(offset, 0)
        damaged[offset] ^= 0x01
        with zipfile.ZipFile(io.BytesIO(damaged)) as archive:
            with self.assertRaises(zipfile.BadZipFile):
                archive.read("Demo/Wizard.html")
        package.write_bytes(package.read_bytes() + bytes(damaged))
        before = self.snapshot(self.profile)
        with self.assertRaises(updater.UpdateError):
            self.run_update(package)
        self.assertEqual(before, self.snapshot(self.profile))

    def test_running_ansys_blocks_update_without_changes(self):
        package = self.package()
        before = self.snapshot(self.profile)
        with patch.object(updater, "active_ansys_processes", return_value=["AnsysWBU.exe"]):
            with self.assertRaises(updater.AnsysProcessesRunning) as raised:
                self.run_update(package)
        self.assertEqual(("AnsysWBU.exe",), raised.exception.names)
        self.assertEqual(before, self.snapshot(self.profile))

    def test_preference_commit_failure_rolls_back_packages_resources_and_preferences(self):
        self.old_installation("previous-release", minor=1)
        self.write_preferences([default_entry(minor=1)])
        new = self.package(self.sources / "new-release.wbex")
        before_extensions = self.snapshot(self.extensions)
        before_preferences = self.preferences.read_bytes()
        original_replace = os.replace
        failed = []

        def fail_preferences_once(source, destination, *args, **kwargs):
            if Path(destination).resolve() == self.preferences.resolve() and not failed:
                failed.append(True)
                raise OSError("injected preferences commit failure")
            return original_replace(source, destination, *args, **kwargs)

        with patch.object(updater.os, "replace", side_effect=fail_preferences_once):
            with self.assertRaises(updater.UpdateError):
                self.run_update(new)
        self.assertEqual([True], failed, "the preference commit must use atomic replacement")
        self.assertEqual(before_extensions, self.snapshot(self.extensions))
        self.assertEqual(before_preferences, self.preferences.read_bytes())

    def test_failure_after_preferences_commit_restores_previous_install_and_preferences(self):
        self.old_installation("previous-release", minor=1)
        self.write_preferences([default_entry(minor=1)])
        package = self.package(self.sources / "new-release.wbex")
        before_extensions = self.snapshot(self.extensions)
        before_preferences = self.preferences.read_bytes()
        original_write_text = Path.write_text
        failures = []

        def fail_report_write(path, data, *args, **kwargs):
            if path.name == "report.json":
                # Reaching report serialization must occur after both the new
                # package and new default preference have been committed.
                self.assertEqual(default_entry(),
                                 self.preference_values()["ACT_DefaultExtensions"])
                self.assertEqual(package.read_bytes(),
                                 (self.extensions / package.name).read_bytes())
                failures.append(True)
                raise OSError("injected report write failure after commit")
            return original_write_text(path, data, *args, **kwargs)

        with patch.object(Path, "write_text", new=fail_report_write):
            with self.assertRaises(updater.UpdateError):
                self.run_update(package)
        self.assertEqual([True], failures)
        self.assertEqual(before_extensions, self.snapshot(self.extensions))
        self.assertEqual(before_preferences, self.preferences.read_bytes())


if __name__ == "__main__":
    unittest.main()
