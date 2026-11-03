# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
"""Offline access to the exact notices shipped inside the application."""
from pathlib import Path
import shutil
import sys


def license_directory():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "legal"
    return Path(__file__).resolve().parent / "legal"


def license_files():
    root = license_directory()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not (root / "THIRD_PARTY_NOTICES.txt").is_file() or not files:
        raise FileNotFoundError("Bundled third-party notices are missing.")
    return files


def license_text():
    root = license_directory()
    files = license_files()
    first = root / "THIRD_PARTY_NOTICES.txt"
    files.remove(first)
    return "\n\n".join(
        "=" * 72 + "\n" + path.relative_to(root).as_posix() + "\n" + "=" * 72 +
        "\n\n" + path.read_text(encoding="utf-8-sig") for path in [first] + files)


def export_licenses(destination):
    root = license_directory().resolve()
    destination = Path(destination).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Choose a folder outside the bundled license directory.")
    license_files()
    shutil.copytree(root, destination)
    return destination
