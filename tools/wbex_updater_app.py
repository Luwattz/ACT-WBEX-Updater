# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
"""Single executable entry point for the ACT WBEX updater."""
from __future__ import annotations

import time
import sys
sys._wbex_updater_entry_time = time.perf_counter()

import argparse
import json
from pathlib import Path

try:
    from .update_wbex import update
    from .wbex_updater_version import VERSION, PRODUCT_NAME, COMPANY, COPYRIGHT
except ImportError:
    from update_wbex import update
    from wbex_updater_version import VERSION, PRODUCT_NAME, COMPANY, COPYRIGHT


def main(argv=None):
    parser = argparse.ArgumentParser(description="ACT WBEX standalone updater")
    parser.add_argument("--version", action="version", version=PRODUCT_NAME + " " + VERSION + " | " + COMPANY)
    parser.add_argument("package", nargs="?", help="Optional WBEX to preselect in the GUI")
    parser.add_argument("--headless", action="store_true", help="Run without a window; requires --report")
    parser.add_argument("--report", help="Write the headless result/log to this JSON file")
    parser.add_argument("--self-check", metavar="REPORT", help="Check the bundled GUI/runtime without installing anything")
    parser.add_argument("--ansys-root")
    parser.add_argument("--profile-dir")
    parser.add_argument("--preferences-file")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(argv)
    if options.self_check:
        try:
            from .wbex_updater_gui import UpdaterApp, ROOT, create_window
        except ImportError:
            from wbex_updater_gui import UpdaterApp, ROOT, create_window
        window = create_window()
        window.withdraw()
        try:
            app = UpdaterApp(window, defer_detection=True)
            window.update_idletasks()
            app.record_window_ready()
            deadline = time.perf_counter() + 5
            while app.startup_pending and time.perf_counter() < deadline:
                window.update()
                time.sleep(0.01)
            result = {"ok": True, "frozen": bool(getattr(sys, "frozen", False)),
                      "version": VERSION, "company": COMPANY, "copyright": COPYRIGHT,
                      "gui_title": window.title(), "tk_version": window.tk.call("package", "provide", "Tk"),
                      "display_dpi": window._ld_dpi, "ui_scale": window._ld_ui_scale,
                      "custom_icon_loaded": window._ld_icon_loaded,
                      "theme": app.theme_mode.get(),
                      "application_directory": str(ROOT), "selected_package": app.package.get(),
                      "detected_ansys_roots": [str(path) for path in app.installations],
                      "selected_ansys_root": app.ansys_root.get(),
                      "discovery_pending": app.startup_pending,
                      "startup_log": app.log_text,
                      "technical_details": "\n".join(app.details),
                      "source_tools_required": False}
            Path(options.self_check).resolve().write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            window.destroy()
        return 0
    if not options.headless:
        if options.report or options.profile_dir or options.preferences_file or options.dry_run or options.ansys_root:
            parser.error("Use --headless and --report for command-line update options.")
        try:
            from .wbex_updater_gui import main as gui_main
        except ImportError:
            from wbex_updater_gui import main as gui_main
        gui_main(package=options.package)
        return 0
    if not options.package or not options.report:
        parser.error("--headless requires a WBEX package and --report <result.json>.")
    report_path = Path(options.report).resolve()
    messages = []
    try:
        result = update(options.package, ansys_root=options.ansys_root,
                        profile_dir=options.profile_dir, preferences_file=options.preferences_file,
                        dry_run=options.dry_run, notify=messages.append)
        report = {"ok": True, "result": result, "log": messages,
                  "frozen": bool(getattr(sys, "frozen", False))}
        code = 0
    except Exception as error:
        report = {"ok": False, "error": str(error), "log": messages,
                  "frozen": bool(getattr(sys, "frozen", False))}
        code = 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
