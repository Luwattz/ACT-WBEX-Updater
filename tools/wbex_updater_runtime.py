# Copyright (c) 2026 Intelligent Efficiency Team. All rights reserved.
"""Standard-library helpers for the distributable ACT WBEX updater.

Keep this module independent of the source builder and release auditor so the
standalone updater never needs to bundle extension or source-protection code.
"""
import io
import os
from pathlib import Path
import re
import struct
import zipfile


class BuildError(RuntimeError):
    """An Ansys installation could not be located or validated."""


HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
EOCD_SIGNATURE = b"PK\x05\x06"
LOCAL_SIGNATURE = b"PK\x03\x04"
DEFAULT_ANSYS_VERSION = "v241"


def _installed(root):
    folder = Path(root) / "Framework" / "bin" / "Win64"
    return (folder / "RunWB2.bat").is_file() and (folder / "AnsysFW.exe").is_file()


def discover_ansys_roots(environ=None):
    """List all detected Workbench installations, newest version first.

    Merge environment and standard installation folders before choosing a
    version: an older AWP_ROOT variable must not hide a newer installation.
    """
    env = os.environ if environ is None else environ
    candidates = {}

    def add(path, fallback_version=0):
        path = Path(path).resolve()
        if not _installed(path):
            return
        match = re.fullmatch(r"v(\d+)", path.name, re.IGNORECASE)
        version = int(match.group(1)) if match else fallback_version
        key = str(path).casefold()
        if key not in candidates or version > candidates[key][0]:
            candidates[key] = (version, path)

    for key, value in env.items():
        match = re.fullmatch(r"AWP_ROOT(\d+)", key, re.IGNORECASE)
        if match and value:
            add(value, int(match.group(1)))
    folders = {key.casefold(): value for key, value in env.items()}
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = folders.get(key.casefold())
        if not value:
            continue
        folder = Path(value) / "ANSYS Inc"
        if folder.is_dir():
            for path in folder.glob("v*"):
                if re.fullmatch(r"v\d+", path.name, re.IGNORECASE):
                    add(path)
    return [path for _, path in sorted(candidates.values(),
                                      key=lambda item: (-item[0], str(item[1]).casefold()))]


def select_default_ansys_root(roots):
    """Prefer v241 from discovered roots, otherwise use the newest detected root.

    ``roots`` must be the validated, newest-first list from discovery.
    """
    roots = list(roots)
    for root in roots:
        if root.name.casefold() == DEFAULT_ANSYS_VERSION:
            return root
    return roots[0] if roots else None


def discover_ansys_root(explicit=None, environ=None):
    """Locate a valid Workbench installation without starting any Ansys host."""
    if explicit is not None:
        root = Path(explicit).resolve()
        if not _installed(root):
            raise BuildError("Ansys installation must contain Framework/bin/Win64/RunWB2.bat and AnsysFW.exe: " + str(root))
        return root
    root = select_default_ansys_root(discover_ansys_roots(environ=environ))
    if root is not None:
        return root
    raise BuildError("No Ansys Workbench installation found. Install Ansys or specify --ansys-root <version folder>.")


def embedded_archives(payload):
    """Read and validate each embedded ACT resource ZIP, including distant ones."""
    archives = []
    try:
        position = payload.find(EOCD_SIGNATURE)
        while position >= 0:
            if position + 22 <= len(payload):
                (_, disk, central_disk, disk_count, total_count, central_size,
                 central_offset, comment_length) = struct.unpack_from("<4s4H2IH", payload, position)
                start = position - central_size - central_offset
                end = position + 22 + comment_length
                if (0 <= start <= position and end <= len(payload)
                        and payload[start:start + 4] in (LOCAL_SIGNATURE, EOCD_SIGNATURE)):
                    if (disk or central_disk or disk_count != total_count
                            or total_count == 0xFFFF or central_size == 0xFFFFFFFF
                            or central_offset == 0xFFFFFFFF):
                        raise ValueError("Unsupported multipart or ZIP64 resource archive at offset {}.".format(start))
                    try:
                        archive = zipfile.ZipFile(io.BytesIO(payload[start:end]))
                        if len(archive.infolist()) != total_count:
                            archive.close()
                            raise ValueError("Resource ZIP count does not match its directory at offset {}.".format(start))
                    except zipfile.BadZipFile as error:
                        raise ValueError("Corrupt embedded resource ZIP at offset {}: {}".format(start, error))
                    archives.append((start, end, archive))
            position = payload.find(EOCD_SIGNATURE, position + 4)
        if not archives:
            raise ValueError("No readable resource ZIP found; this WBEX format cannot be verified.")
        # Corrupt directories must never cause exposed resources to be omitted.
        position = payload.find(LOCAL_SIGNATURE)
        while position >= 0:
            if not any(start <= position < end for start, end, _ in archives):
                raise ValueError("Uninspected ZIP resource record at offset {}; package may be corrupt.".format(position))
            position = payload.find(LOCAL_SIGNATURE, position + 4)
        return archives
    except BaseException:
        for _, _, archive in archives:
            archive.close()
        raise
