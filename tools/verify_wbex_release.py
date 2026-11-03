# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
"""Verify both built Windows layouts before permitting release publication."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from tools.wbex_updater_version import VERSION, COMPANY

ROOT = Path(__file__).resolve().parents[1]


def verify():
    folder = ROOT / "dist/wbex-updater-folder/ACT_WBEX_Updater"
    single = ROOT / "dist/wbex-updater/ACT_WBEX_Updater.exe"
    results = []
    with tempfile.TemporaryDirectory(prefix="wbex-release-verification-") as temporary:
        temporary = Path(temporary)
        # Test relocated distributions without repository files beside them.
        relocated = temporary / "folder"
        shutil.copytree(folder, relocated)
        onefile = temporary / "single/ACT_WBEX_Updater.exe"
        onefile.parent.mkdir()
        shutil.copyfile(single, onefile)
        for mode, exe in (("onedir", relocated / single.name), ("onefile", onefile)):
            report = temporary / (mode + "-self-check.json")
            subprocess.run([str(exe), "--self-check", str(report)], check=True, timeout=90)
            data = json.loads(report.read_text(encoding="utf-8"))
            for key in ("ok", "frozen", "custom_icon_loaded", "third_party_notices_present"):
                if data.get(key) is not True:
                    raise RuntimeError(mode + " self-check failed: " + key)
            if data["version"] != VERSION or data["company"] != COMPANY:
                raise RuntimeError("Executable identity mismatch.")
            # The export must work with no external notices/repository next to EXE.
            exported = temporary / (mode + "-licenses")
            subprocess.run([str(exe), "--export-licenses", str(exported)], check=True, timeout=90)
            source = ROOT / "tools/legal"
            for original in source.rglob("*"):
                if original.is_file():
                    bundled = exported / original.relative_to(source)
                    if bundled.read_bytes() != original.read_bytes():
                        raise RuntimeError("Missing or changed embedded notice: " + str(original))
            if not (exported / "licenses/Python-installed-LICENSE.txt").is_file():
                raise RuntimeError("Actual Python distribution license missing.")
            # Check PE file/product versions and company using Windows resource API.
            script = ("$v=(Get-Item -LiteralPath '" + str(exe).replace("'", "''") +
                      "').VersionInfo; @{FileVersion=$v.FileVersion; "
                      "ProductVersion=$v.ProductVersion; CompanyName=$v.CompanyName} | ConvertTo-Json")
            pe = json.loads(subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", script], text=True))
            if pe["FileVersion"] != VERSION or pe["ProductVersion"] != VERSION or pe["CompanyName"] != COMPANY:
                raise RuntimeError("PE version metadata mismatch: " + repr(pe))
            results.append({"layout": mode, "self_check": data, "pe_metadata": pe,
                            "license_file_count": len(list(exported.rglob("*.txt")))})
        # External legal materials must also be in the ZIP.
        archive = ROOT / "dist/wbex-updater-folder/ACT_WBEX_Updater.zip"
        with zipfile.ZipFile(archive) as zipped:
            for path in ("LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "BUILD-INFO.json",
                         "licenses/Python-installed-LICENSE.txt", "licenses/SOURCES.json"):
                zipped.getinfo("ACT_WBEX_Updater/" + path)
    output = ROOT / "dist/release"
    output.mkdir(parents=True, exist_ok=True)
    for source, suffix in ((single, "exe"), (archive, "zip")):
        shutil.copyfile(source, output / ("ACT_WBEX_Updater-v" + VERSION + "-windows-x64." + suffix))
    for name in ("LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "BUILD-INFO.json"):
        shutil.copyfile(folder / name, output / name)
    shutil.make_archive(str(output / "THIRD_PARTY_LICENSES"), "zip", root_dir=folder,
                        base_dir="licenses")
    (output / "VERIFICATION.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums = [hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name
            for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("Both standalone layouts passed relocation, self-check, metadata and license export checks.")


if __name__ == "__main__":
    verify()
