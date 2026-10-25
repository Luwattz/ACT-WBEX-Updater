# Copyright (c) 2026 Intelligent Efficiency Team. All rights reserved.
"""Build the standalone Windows WBEX updater; never package plugin sources.

This is a developer tool. Both release layouts include Python and Tcl/Tk.
The default folder release avoids unpacking the runtime on every launch.
"""
from __future__ import annotations

import argparse
import ast
from importlib import metadata, util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

try:
    from tools.wbex_updater_version import VERSION, VERSION_TUPLE, PRODUCT_NAME, COMPANY, COPYRIGHT
except ImportError:
    from wbex_updater_version import VERSION, VERSION_TUPLE, PRODUCT_NAME, COMPANY, COPYRIGHT


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "wbex-updater"
FOLDER_OUTPUT = ROOT / "dist" / "wbex-updater-folder"
EXE_NAME = "ACT_WBEX_Updater"
DPI_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">system</dpiAwareness>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/></application>
  </compatibility>
</assembly>"""
RUNTIME_SOURCES = (
    "wbex_updater_app.py",
    "wbex_updater_gui.py",
    "wbex_updater_drop.py",
    "wbex_updater_icon.py",
    "update_wbex.py",
    "wbex_updater_runtime.py",
    "wbex_updater_version.py",
)
RUNTIME_ASSETS = ("updater.ico",)
EXCLUDED_MODULES = (
    "build_wbex", "check_wbex_release", "LumiDyna",
    "tools.build_wbex", "tools.check_wbex_release", "tools.LumiDyna",
)
USAGE = f"""ACT WBEX Updater v{VERSION}
{COMPANY}
{COPYRIGHT}

只需分发 ACT_WBEX_Updater.exe 和要安装的 .wbex 插件包，无需分发源码、
tools 目录、Python 或 CMD 启动器。EXE 可单独移动到其他目录使用。

1. 保存工作并关闭 Workbench、Mechanical、SpaceClaim。
2. 双击 ACT_WBEX_Updater.exe，选择 .wbex 和目标 Ansys 版本目录。
   也可将一个 .wbex 文件拖入已打开的窗口，自动填入路径；拖入不会直接安装。
   EXE 同目录只有一个 .wbex 时，会自动填入该包。
   默认优先选择已安装的 v241；找不到 v241 时选择最新版本，也可手动切换。
3. 点击“检查（不更改）”核对，再点击“更新并设为默认”。
4. 下次启动 Ansys 时使用新版本，并按 Load as default 加载。

更新前会备份旧安装及配置；普通失败会自动回退。
程序处理当前 Windows 用户的安装，不需要启动 Workbench。
需已安装受支持的 Ansys，并已完成该版本的用户初始化。
如提示同 GUID 的 XML 开发版冲突，请从 Additional Extension Folders
中移除对应开发路径；无需删除源码目录。
"""
FOLDER_USAGE = USAGE.replace(
    "只需分发 ACT_WBEX_Updater.exe 和要安装的 .wbex 插件包，无需分发源码、\n"
    "tools 目录、Python 或 CMD 启动器。EXE 可单独移动到其他目录使用。",
    "请分发完整更新程序文件夹（或 ZIP）和 .wbex 插件包，无需分发源码、\n"
    "tools 目录、Python 或 CMD 启动器。先完整解压 ZIP，再运行 EXE。\n"
    "EXE 必须与 _internal 文件夹一起保留，不能单独移动 EXE。\n"
    "文件夹版无需每次解包运行库，适合单文件版启动缓慢的电脑。")


class StandaloneBuildError(RuntimeError):
    pass


def require_build_environment():
    if sys.platform != "win32":
        raise StandaloneBuildError("Build the Windows updater on Windows.")
    if util.find_spec("PyInstaller") is None:
        raise StandaloneBuildError(
            'Developer build dependency missing. Run:\n"' + sys.executable +
            '" -m pip install "pyinstaller>=6.16,<7"\n'
            "End users do not need Python or PyInstaller."
        )
    try:
        import tkinter  # noqa: F401 - validate the runtime before building
    except ImportError as error:
        raise StandaloneBuildError(
            "This build interpreter needs Tcl/Tk. Repair Python with the "
            "Tcl/Tk component enabled."
        ) from error


def stage_runtime(tools_dir: Path, staged_tools: Path):
    """Copy only updater runtime code, without repository or plugin content."""
    missing = [name for name in RUNTIME_SOURCES if not (tools_dir / name).is_file()]
    if missing:
        raise StandaloneBuildError("Missing updater runtime files: " + ", ".join(missing))
    assets = tools_dir / "assets" / "wbex-updater"
    missing_assets = [name for name in RUNTIME_ASSETS if not (assets / name).is_file()]
    if missing_assets:
        raise StandaloneBuildError("Missing updater icon assets: " + ", ".join(missing_assets))
    staged_tools.mkdir(parents=True)
    for name in RUNTIME_SOURCES:
        shutil.copyfile(tools_dir / name, staged_tools / name)
    staged_assets = staged_tools / "assets" / "wbex-updater"
    staged_assets.mkdir(parents=True)
    for name in RUNTIME_ASSETS:
        shutil.copyfile(assets / name, staged_assets / name)


def pyinstaller_command(staged_tools: Path, temporary_root: Path, mode="onedir"):
    if mode not in ("onedir", "onefile"):
        raise StandaloneBuildError("Unknown release mode: " + mode)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--" + mode,
        "--windowed", "--noupx", "--name", EXE_NAME,
        "--version-file", str(temporary_root / "version-info.txt"),
        "--icon", str(staged_tools / "assets" / "wbex-updater" / "updater.ico"),
        "--add-data", str(staged_tools / "assets" / "wbex-updater" / "updater.ico") + os.pathsep + "updater_assets",
        # PyInstaller 6.16 embeds inline XML in a single-quoted spec literal.
        "--manifest", DPI_MANIFEST.replace("\n", ""),
        "--paths", str(staged_tools),
        "--distpath", str(temporary_root / "dist"),
        "--workpath", str(temporary_root / "work"),
        "--specpath", str(temporary_root / "spec"),
    ]
    for name in EXCLUDED_MODULES:
        command.extend(("--exclude-module", name))
    command.append(str(staged_tools / "wbex_updater_app.py"))
    return command


def verify_module_boundary(work_dir: Path):
    """Fail before publishing if analysis contains builder or plugin modules."""
    analysis_files = sorted(work_dir.rglob("PYZ-*.toc"))
    if not analysis_files:
        raise StandaloneBuildError("PyInstaller produced no module analysis to verify.")
    forbidden = set(EXCLUDED_MODULES)

    def visit(item):
        if isinstance(item, (list, tuple)):
            if item and isinstance(item[0], str):
                module = item[0]
                if any(module == name or module.startswith(name + ".") for name in forbidden):
                    raise StandaloneBuildError("Forbidden packaged module: " + module)
            for child in item:
                visit(child)

    for path in analysis_files:
        try:
            visit(ast.literal_eval(path.read_text(encoding="utf-8")))
        except (SyntaxError, ValueError) as error:
            raise StandaloneBuildError("Cannot verify module analysis: " + str(path)) from error


def publish_file(source: Path, destination: Path):
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def notify_shell_update(executable: Path):
    """Invalidate this file's Shell presentation after replacing an existing EXE."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        shell = ctypes.WinDLL("shell32")
        shell.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        shell.SHChangeNotify.restype = None
        for event, path in ((0x2000, executable), (0x1000, executable.parent)):
            name = ctypes.c_wchar_p(str(path))
            # SHCNE_UPDATEITEM / UPDATEDIR; Unicode path, flush without waiting.
            shell.SHChangeNotify(event, 0x0005 | 0x2000, ctypes.cast(name, ctypes.c_void_p), None)
    except (AttributeError, OSError):
        # A Shell refresh failure does not invalidate a successfully built file.
        pass


def publish_folder(source: Path, destination: Path):
    """Swap a complete release, restoring the previous folder on failure."""
    staged = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    previous = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".old")
    published = False
    try:
        shutil.copytree(source, staged)
        if destination.exists():
            os.replace(destination, previous)
        try:
            os.replace(staged, destination)
            published = True
        except OSError:
            if previous.exists():
                os.replace(previous, destination)
            raise
    finally:
        # Only clean the two unique siblings created for this publication.
        for owned in ((staged, previous) if published else (staged,)):
            if owned.resolve().parent != destination.resolve().parent:
                raise StandaloneBuildError("Release staging path escaped the output directory.")
            if owned.exists():
                shutil.rmtree(owned)


def write_version_info(path: Path):
    strings = {"CompanyName": COMPANY, "FileDescription": PRODUCT_NAME,
               "FileVersion": VERSION, "InternalName": EXE_NAME,
               "LegalCopyright": COPYRIGHT, "OriginalFilename": EXE_NAME + ".exe",
               "ProductName": PRODUCT_NAME, "ProductVersion": VERSION}
    entries = ",\n".join("StringStruct(" + repr(key) + ", " + repr(value) + ")" for key, value in strings.items())
    path.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers=" + repr(VERSION_TUPLE) +
                    ", prodvers=" + repr(VERSION_TUPLE) + ", mask=0x3f, flags=0x0, OS=0x40004, "
                    "fileType=0x1, subtype=0x0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [" +
                    entries + "])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])", encoding="utf-8")


def build_standalone(output_dir: Path = None, mode="onedir"):
    require_build_environment()
    output_dir = Path(output_dir or (FOLDER_OUTPUT if mode == "onedir" else DEFAULT_OUTPUT)).resolve()
    print("Build Python: " + sys.version.split()[0] + " (" + sys.executable + ")", flush=True)
    print("PyInstaller: " + metadata.version("pyinstaller"), flush=True)
    print("Generated updater default: prefer installed Ansys v241; otherwise newest installed version.", flush=True)
    with tempfile.TemporaryDirectory(prefix="act-wbex-updater-build-") as temporary:
        temporary_root = Path(temporary)
        staged_tools = temporary_root / "source" / "tools"
        stage_runtime(ROOT / "tools", staged_tools)
        write_version_info(temporary_root / "version-info.txt")
        env = dict(os.environ)
        # Avoid inherited repository paths affecting PyInstaller's import graph.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        result = subprocess.run(
            pyinstaller_command(staged_tools, temporary_root, mode),
            cwd=staged_tools.parent, env=env, check=False,
        )
        if result.returncode:
            raise StandaloneBuildError("PyInstaller failed; see the build output above.")
        release = temporary_root / "dist"
        if mode == "onedir":
            release = release / EXE_NAME
        executable = release / (EXE_NAME + ".exe")
        if not executable.is_file():
            raise StandaloneBuildError("PyInstaller did not create " + executable.name)
        verify_module_boundary(temporary_root / "work")
        output_dir.mkdir(parents=True, exist_ok=True)
        usage = temporary_root / "使用说明.txt"
        usage.write_text(FOLDER_USAGE if mode == "onedir" else USAGE, encoding="utf-8-sig")
        if mode == "onedir":
            shutil.copyfile(usage, release / usage.name)
            archive = shutil.make_archive(str(temporary_root / EXE_NAME), "zip",
                                          root_dir=release.parent, base_dir=EXE_NAME)
            publish_folder(release, output_dir / EXE_NAME)
            publish_file(Path(archive), output_dir / (EXE_NAME + ".zip"))
        else:
            publish_file(executable, output_dir / executable.name)
            publish_file(usage, output_dir / usage.name)
    result_path = output_dir / EXE_NAME / (EXE_NAME + ".exe") if mode == "onedir" else output_dir / (EXE_NAME + ".exe")
    notify_shell_update(result_path)
    print("Standalone updater: " + str(result_path))
    print("Distribute the complete folder/ZIP with the .wbex package." if mode == "onedir"
          else "Distribute this EXE with the .wbex package. End users need no Python.")
    return result_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("onedir", "onefile"), default="onedir",
                        help="Release layout (default: onedir, faster startup)")
    parser.add_argument("--output-dir", type=Path,
                        help="Output directory (default depends on release layout)")
    args = parser.parse_args(argv)
    try:
        build_standalone(args.output_dir, args.mode)
        return 0
    except (StandaloneBuildError, OSError) as error:
        print("Standalone updater build failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
