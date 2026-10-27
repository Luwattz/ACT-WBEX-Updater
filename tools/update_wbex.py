# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
"""Replace user-installed ACT binary extensions without starting Workbench.

The v241 native installer copies the WBEX and extracts its resource ZIPs into
a sibling directory named after the package file stem. Compiled ``content``
buffers stay in the WBEX. This tool performs that layout change transactionally
and updates only the matching GUID in ACT_DefaultExtensions.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

try:
    from .wbex_updater_runtime import (BuildError, HDF5_SIGNATURE,
                                       discover_ansys_root, embedded_archives)
except ImportError:
    from wbex_updater_runtime import (BuildError, HDF5_SIGNATURE,
                                      discover_ansys_root, embedded_archives)


class UpdateError(RuntimeError):
    pass


class AnsysProcessesRunning(UpdateError):
    def __init__(self, names):
        self.names = tuple(names)
        super().__init__("Close Workbench/Mechanical/SpaceClaim before updating: " + ", ".join(self.names))


MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_RESOURCE_BYTES = 512 * 1024 * 1024
HOST_NAMES = {"ansysfw.exe", "ansysfww.exe", "ansyswbu.exe", "spaceclaim.exe"}
KNOWN_EDITIONS = {
    "879a7bfe-a5ba-4c02-a8bc-870294861822": ("LumiDyna", "LumiDynaFull"),
    "1d70522c-f618-4b9e-9819-927a5c39a7bb": ("LumiDynaLite", "LumiDyna"),
}


def _guid(text):
    try:
        return str(uuid.UUID(text.strip()))
    except (ValueError, AttributeError) as error:
        raise UpdateError("Invalid extension GUID: " + repr(text)) from error


def _segment(name):
    if (not name or name in {".", ".."} or name[-1:] in {".", " "} or
            re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or
            name.split(".", 1)[0].upper() in {
                "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                *["COM" + str(i) for i in range(1, 10)],
                *["LPT" + str(i) for i in range(1, 10)]}):
        raise UpdateError("Unsafe Windows file name: " + repr(name))
    return name


def _field(text, label):
    if not text or re.search(r"[;|\x00-\x1f]", text):
        raise UpdateError("Invalid package " + label + ": " + repr(text))
    return text


@dataclass
class Package:
    path: Path
    name: str
    guid: str
    shortid: str
    major: str
    minor: str
    files: dict[str, bytes]
    payload: bytes

    @property
    def default_entry(self):
        return ";".join(("1", self.name, self.guid, self.shortid, "wbex", self.major, self.minor))

    def metadata(self):
        return {"name": self.name, "guid": self.guid, "shortid": self.shortid,
                "version": self.major + "." + self.minor,
                "sha256": hashlib.sha256(self.payload).hexdigest(),
                "resources": len(self.files)}


def inspect_package(path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".wbex" or not path.is_file():
        raise UpdateError("Select an existing .wbex package: " + str(path))
    _segment(path.stem)
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise UpdateError("WBEX exceeds the supported 1 GiB package limit.")
    payload = path.read_bytes()
    if not payload.startswith(HDF5_SIGNATURE):
        raise UpdateError("Expected a native HDF5 WBEX package; ZIP/XML files cannot be installed.")
    try:
        archives = embedded_archives(payload)
    except (OSError, ValueError) as error:
        raise UpdateError("Cannot read this WBEX format: " + str(error)) from error
    definitions, resources, size = [], {}, 0
    try:
        for _, _, archive in archives:
            entries = archive.infolist()
            for item in entries:
                if item.file_size > MAX_RESOURCE_BYTES:
                    raise UpdateError("WBEX resource exceeds the 512 MiB limit: " + item.filename)
                size += item.file_size
                if size > MAX_PACKAGE_BYTES:
                    raise UpdateError("Expanded WBEX exceeds the supported 1 GiB limit.")
                if item.filename == "content" and len(entries) == 1:
                    data = archive.read(item)
                    try:
                        node = ET.fromstring(data)
                    except ET.ParseError:
                        continue  # Compiled script buffers are retained in the WBEX.
                    if node.tag.lower() == "extension":
                        definitions.append(node)
                    continue
                name = item.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith("/") or ".." in parts or
                        any(part in {".", ""} for part in name.rstrip("/").split("/"))):
                    raise UpdateError("Unsafe resource path: " + repr(name))
                for part in parts:
                    _segment(part)
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise UpdateError("WBEX resource links are not supported: " + name)
                if item.is_dir():
                    continue
                # ACT extracts a single top-level folder, then flattens it.
                if len(parts) < 2:
                    raise UpdateError("WBEX resources must share a top-level folder: " + name)
                normalized = "/".join(parts)
                if normalized.casefold() in resources:
                    raise UpdateError("Duplicate resource path: " + name)
                resources[normalized.casefold()] = (parts, archive.read(item))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        if isinstance(error, UpdateError):
            raise
        raise UpdateError("WBEX resource validation failed: " + str(error)) from error
    finally:
        for _, _, archive in archives:
            archive.close()
    if len(definitions) != 1:
        raise UpdateError("WBEX must contain exactly one readable ACT extension definition.")
    definition = definitions[0]
    guid_node = next((node for node in definition if node.tag.lower() == "guid"), None)
    if guid_node is None:
        raise UpdateError("WBEX has no GUID.")
    name = _field(definition.get("name", ""), "name")
    guid = _guid(guid_node.text or "")
    shortid = _field(guid_node.get("shortid", ""), "shortid")
    major, minor = definition.get("version", "1"), definition.get("minorversion", "0")
    if not re.fullmatch(r"\d+", major) or not re.fullmatch(r"\d+", minor):
        raise UpdateError("WBEX major/minor version must be integers.")
    if guid in KNOWN_EDITIONS and (name, shortid) != KNOWN_EDITIONS[guid]:
        raise UpdateError("WBEX name/shortid do not match its LumiDyna edition GUID.")
    roots = {parts[0].casefold() for parts, _ in resources.values()}
    if len(roots) > 1:
        raise UpdateError("Multiple top-level resource folders are not supported by this updater.")
    files = {"/".join(parts[1:]): data for parts, data in resources.values()}
    folded = {relative.casefold() for relative in files}
    if any(any("/".join(PurePosixPath(relative).parts[:i]).casefold() in folded
               for i in range(1, len(PurePosixPath(relative).parts))) for relative in files):
        raise UpdateError("WBEX contains conflicting file/directory paths.")
    return Package(path, name, guid, shortid, major, minor, files, payload)


def _ansys_process_entries():
    if os.name != "nt":
        raise UpdateError("The ACT updater must run on Windows.")
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise UpdateError("Cannot check running Ansys processes: " + str(ctypes.WinError(ctypes.get_last_error())))
    processes = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        success = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            if entry.szExeFile.casefold() in HOST_NAMES:
                processes.append((entry.th32ProcessID, entry.szExeFile))
            success = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise UpdateError("Process enumeration failed: " + str(ctypes.WinError(ctypes.get_last_error())))
        return processes
    finally:
        kernel.CloseHandle(snapshot)


def active_ansys_processes():
    return sorted({name for _, name in _ansys_process_entries()})


def _terminate_ansys_process(pid, name):
    """Terminate one verified host by handle, avoiding PID reuse after opening."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    handle = kernel.OpenProcess(0x00101001, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # Already exited: ERROR_INVALID_PARAMETER
            return
        raise UpdateError("Cannot close Ansys processes: " + name + ": " +
                          str(ctypes.WinError(ctypes.get_last_error())))
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            return
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return
            raise UpdateError("Cannot close Ansys processes: cannot verify " + name)
        if Path(image.value).name.casefold() != name.casefold():
            raise UpdateError("Cannot close Ansys processes: process identity changed for " + name)
        if not kernel.TerminateProcess(handle, 1) and kernel.WaitForSingleObject(handle, 0) != 0:
            raise UpdateError("Cannot close Ansys processes: " + name + ": " +
                              str(ctypes.WinError(ctypes.get_last_error())))
        if kernel.WaitForSingleObject(handle, 5000) != 0:
            raise UpdateError("Cannot close Ansys processes: timed out waiting for " + name)
    finally:
        kernel.CloseHandle(handle)


def close_ansys_processes(approved_names):
    """Only close allowlisted host names explicitly approved by the GUI user."""
    approved = {name.casefold() for name in approved_names}
    if not approved or not approved <= HOST_NAMES:
        raise UpdateError("Cannot close Ansys processes: unapproved process name.")
    for pid, name in _ansys_process_entries():
        if name.casefold() in approved:
            _terminate_ansys_process(pid, name)
    running = active_ansys_processes()
    if running:
        raise AnsysProcessesRunning(running)


def _read_xml(path):
    try:
        return ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise UpdateError("Cannot read ACT preferences: " + str(path)) from error


def _pref(root, name):
    # PreferenceSpecs also contains nodes with these names; use VALUE only.
    return next((node for node in root.iter("VALUE") if node.get("ObjectName") == name), None)


def _value(root, name, default=""):
    node = _pref(root, name)
    return default if node is None else node.get("Value", "")


def _preferences_path(profile, explicit):
    if explicit is not None:
        original = Path(explicit).absolute()
        path = original.resolve()
        if not path.is_relative_to(profile) or path.name.lower() != "actpreferences.xml":
            raise UpdateError("Preferences file must be ACTPreferences.xml inside the selected Ansys profile.")
        _assert_plain(original)
        _assert_plain(original.parent)
        return path
    candidates = sorted(profile.glob("UserRegFiles_*/ACTPreferences.xml"))
    if len(candidates) == 1:
        path = candidates[0]
        if not path.resolve().is_relative_to(profile):
            raise UpdateError("ACT preferences resolve outside the selected Ansys profile.")
        _assert_plain(path.parent)
        _assert_plain(path)
        return path.resolve()
    directories = [path for path in profile.glob("UserRegFiles_*") if path.is_dir()]
    if not candidates and len(directories) == 1:
        _assert_plain(directories[0])
        path = (directories[0] / "ACTPreferences.xml").resolve()
        if not path.is_relative_to(profile):
            raise UpdateError("ACT preferences resolve outside the selected Ansys profile.")
        return path
    raise UpdateError("Cannot uniquely identify the Workbench user preferences. Use --preferences-file with "
                      "the correct ACTPreferences.xml; the Ansys user profile must already exist.")


def _new_preferences():
    root = ET.Element("KEYS")
    key = ET.SubElement(root, "KEY", ObjectName="ACTPreferences", RegObjectType="0")
    keys = ET.SubElement(key, "KEYS")
    values_key = ET.SubElement(keys, "KEY", ObjectName="PreferenceValues", RegObjectType="0")
    ET.SubElement(values_key, "VALUES")
    return root


def _set_default(root, package, inherited):
    old = _value(root, "ACT_DefaultExtensions", inherited)
    keep = []
    for entry in filter(None, old.split("|")):
        fields = entry.split(";")
        if len(fields) >= 3:
            try:
                if _guid(fields[2]) == package.guid:
                    continue
            except UpdateError:
                pass
        keep.append(entry)
    keep.append(package.default_entry)
    node = _pref(root, "ACT_DefaultExtensions")
    if node is None:
        values = next((key.find("VALUES") for key in root.iter("KEY")
                       if key.get("ObjectName") == "PreferenceValues"), None)
        if values is None:
            raise UpdateError("ACT preferences have an unsupported XML structure.")
        node = ET.SubElement(values, "VALUE", ObjectName="ACT_DefaultExtensions", ValueType="2")
    node.set("Value", "|".join(keep))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _assert_plain(path):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UpdateError("Refusing to replace a linked/reparse path: " + str(path))


def _check_source_conflicts(root, package):
    for folder in filter(None, _value(root, "ACT_AdditionalExtensionsFolders").split(";")):
        directory = Path(os.path.expandvars(folder))
        if not directory.is_dir():
            continue
        for xml in directory.glob("*.xml"):
            try:
                definition = ET.fromstring(xml.read_bytes())
                guid = next((node.text for node in definition if node.tag.lower() == "guid"), "")
                same_guid = _guid(guid) == package.guid
            except (OSError, ET.ParseError, UpdateError):
                continue
            if same_guid:
                raise UpdateError("A scripted XML extension with the same GUID is in Additional Extension "
                                  "Folders: " + str(xml) + ". Remove that development search path before installing WBEX.")


def update(package_path, ansys_root=None, profile_dir=None, preferences_file=None,
           dry_run=False, notify=print):
    package = inspect_package(package_path)
    try:
        ansys = discover_ansys_root(ansys_root)
    except BuildError as error:
        raise UpdateError(str(error)) from error
    if not re.fullmatch(r"v\d{3}", ansys.name, re.IGNORECASE):
        raise UpdateError("Select an Ansys version directory named vNNN (for example v241 or v261).")
    ansys_version = ansys.name.lower()
    appdata = os.environ.get("APPDATA")
    if profile_dir is None and not appdata:
        raise UpdateError("APPDATA is missing; cannot locate the current Windows user's Ansys profile.")
    profile = Path(profile_dir or Path(appdata) / "Ansys" / ansys_version).resolve()
    preferences = _preferences_path(profile, preferences_file)
    original_preferences = preferences.read_bytes() if preferences.is_file() else None
    root = _read_xml(preferences) if original_preferences is not None else _new_preferences()
    machine_path = ansys / "commonfiles/registry/winx64/ACTPreferences.xml"
    machine = _read_xml(machine_path) if machine_path.is_file() else _new_preferences()
    _check_source_conflicts(root, package)
    _check_source_conflicts(machine, package)
    new_preferences = _set_default(root, package, _value(machine, "ACT_DefaultExtensions"))
    extensions = (profile / "ACT/extensions").resolve()
    _assert_plain(profile / "ACT")
    _assert_plain(profile / "ACT/extensions")
    _assert_plain(preferences)
    old_files = []
    for path in sorted(extensions.glob("*.wbex")):
        _assert_plain(path)
        try:
            installed = inspect_package(path)
        except UpdateError as error:
            raise UpdateError("Cannot identify an installed WBEX safely; no changes were made: " + str(path)) from error
        if installed.guid == package.guid:
            folder = path.with_suffix("")
            _assert_plain(folder)
            old_files.append(path)
            if folder.exists():
                old_files.append(folder)
    old_set = set(old_files)
    stem, index = package.path.stem, 0
    while True:
        installed_file = extensions / (stem + ".wbex")
        installed_folder = extensions / stem
        if all((not path.exists() and not path.is_symlink()) or path in old_set
               for path in (installed_file, installed_folder)):
            break
        index += 1
        stem = package.path.stem + str(index)
    report = {"package": package.metadata(), "ansys_root": str(ansys), "ansys_version": ansys_version,
              "profile_dir": str(profile),
              "preferences": str(preferences), "installed_file": str(installed_file),
              "installed_folder": str(installed_folder), "replaced": [str(path) for path in old_files],
              "load_as_default": True, "dry_run": bool(dry_run), "backup": None}
    notify("Package: {name} {version} / {guid}".format(**report["package"]))
    notify("Target Ansys: " + ansys_version + " / " + str(ansys))
    notify("Ansys profile: " + str(profile))
    notify("Replace {} old package/resource paths; install {} resources; Load as default = true.".format(
        len(old_files), len(package.files)))
    if dry_run:
        notify("Check complete. No files or preferences were changed.")
        return report
    running = active_ansys_processes()
    if running:
        raise AnsysProcessesRunning(running)
    act = profile / "ACT"
    _assert_plain(act / "extension_update_backups")
    act.mkdir(parents=True, exist_ok=True)
    lock = act / ".wbex-updater.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise UpdateError("Another update is active (or left a lock after interruption): " + str(lock)) from error
    os.close(descriptor)
    run = act / "extension_update_backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + package.guid)
    staged, moved, created = run / "staged", [], []
    committed_preferences = False
    try:
        run.mkdir(parents=True)
        (run / "old").mkdir()
        staged.mkdir()
        if original_preferences is not None:
            (run / "ACTPreferences.before.xml").write_bytes(original_preferences)
        stage_file, stage_folder = staged / installed_file.name, staged / installed_folder.name
        stage_file.write_bytes(package.payload)
        stage_folder.mkdir()
        for relative, data in package.files.items():
            output = stage_folder.joinpath(*PurePosixPath(relative).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        (run / "ACTPreferences.after.xml").write_bytes(new_preferences)
        if active_ansys_processes():
            raise UpdateError("An Ansys application started during staging. Close it and retry.")
        current = preferences.read_bytes() if preferences.is_file() else None
        if current != original_preferences:
            raise UpdateError("ACT preferences changed during staging; retry after closing Ansys.")
        extensions.mkdir(parents=True, exist_ok=True)
        preferences.parent.mkdir(parents=True, exist_ok=True)
        for path in old_files:
            # All replaced paths must be immediate children of this profile's
            # extensions directory; no source checkout is moved or deleted.
            _assert_plain(path)
            if path.parent != extensions or path.resolve().parent != extensions:
                raise UpdateError("Replacement target is outside the selected extensions directory.")
            backup = run / "old" / path.name
            os.replace(path, backup)
            moved.append((path, backup))
        for source, target in ((stage_file, installed_file), (stage_folder, installed_folder)):
            if target.exists() or target.is_symlink():
                raise UpdateError("Installation target appeared during update: " + str(target))
            os.replace(source, target)
            created.append(target)
        temporary_preferences = preferences.with_name("ACTPreferences.updater-" + uuid.uuid4().hex + ".tmp")
        try:
            temporary_preferences.write_bytes(new_preferences)
            os.replace(temporary_preferences, preferences)
            committed_preferences = True
        finally:
            temporary_preferences.unlink(missing_ok=True)
        if installed_file.read_bytes() != package.payload:
            raise UpdateError("Installed WBEX failed verification.")
        if _value(_read_xml(preferences), "ACT_DefaultExtensions").split("|").count(package.default_entry) != 1:
            raise UpdateError("Load as default verification failed.")
        report["backup"] = str(run)
        report["status"] = "complete"
        (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        notify("Update complete. Previous installation/preferences backed up at: " + str(run))
        return report
    except Exception as error:
        failures = []
        for path in reversed(created):
            try:
                if path.parent != extensions or path.resolve().parent != extensions:
                    raise UpdateError("Rollback target is outside the extensions directory.")
                _assert_plain(path)
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except (OSError, UpdateError) as rollback_error:
                failures.append(str(rollback_error))
        for path, backup in reversed(moved):
            try:
                os.replace(backup, path)
            except OSError as rollback_error:
                failures.append(str(rollback_error))
        if committed_preferences:
            recovery = preferences.with_name("ACTPreferences.recovery-" + uuid.uuid4().hex + ".tmp")
            try:
                if original_preferences is None:
                    preferences.unlink(missing_ok=True)
                else:
                    recovery.write_bytes(original_preferences)
                    os.replace(recovery, preferences)
            except OSError as rollback_error:
                failures.append(str(rollback_error))
            finally:
                recovery.unlink(missing_ok=True)
        message = str(error) + "\nUpdate failed; " + (
            "rollback needs attention: " + "; ".join(failures) if failures else "previous installation restored.")
        raise UpdateError(message + "\nRecovery files: " + str(run)) from error
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            notify("Could not remove the update lock; remove it before the next update: " + str(lock))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="New ACT .wbex package")
    parser.add_argument("--ansys-root", help="Installed Ansys vNNN directory; omit to prefer v241, otherwise the newest installed version")
    parser.add_argument("--profile-dir", help="Explicit Ansys user version profile (also useful for isolated tests)")
    parser.add_argument("--preferences-file", help="Explicit ACTPreferences.xml when multiple user registry profiles exist")
    parser.add_argument("--dry-run", action="store_true", help="Validate and show the plan without modifying any files")
    args = parser.parse_args(argv)
    try:
        report = update(args.package, ansys_root=args.ansys_root, profile_dir=args.profile_dir,
                        preferences_file=args.preferences_file, dry_run=args.dry_run)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except (UpdateError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("WBEX update failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
