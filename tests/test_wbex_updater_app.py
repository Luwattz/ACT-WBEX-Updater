"""Guard the standalone updater entry point and in-process GUI engine calls."""
from contextlib import redirect_stderr
import importlib
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from tools import update_wbex as engine
from tools import wbex_updater_app as app

try:
    import tkinter as tk
except ModuleNotFoundError:
    tk = None

if tk is not None:
    from tools import wbex_updater_gui as gui
else:
    gui = None


class StandaloneUpdaterAppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "LumiDyna.wbex"
        self.package.write_bytes(b"the engine is mocked; never install this fixture")
        self.report = self.root / "result.json"

    def test_headless_writes_result_log_and_passes_explicit_engine_options(self):
        ansys, profile = self.root / "v241", self.root / "profile"
        preferences = profile / "UserRegFiles_123/ACTPreferences.xml"
        expected = {"package": {"name": "LumiDyna"}, "dry_run": True}

        def update(package, **options):
            self.assertEqual(str(self.package), package)
            self.assertEqual(str(ansys), options["ansys_root"])
            self.assertEqual(str(profile), options["profile_dir"])
            self.assertEqual(str(preferences), options["preferences_file"])
            self.assertIs(True, options["dry_run"])
            options["notify"]("检查包身份")
            options["notify"]("No files changed.")
            return expected

        with patch.object(app, "update", side_effect=update) as bundled_update, patch.object(
                subprocess, "Popen", side_effect=AssertionError("external process launch")):
            code = app.main([str(self.package), "--headless", "--report", str(self.report),
                             "--ansys-root", str(ansys), "--profile-dir", str(profile),
                             "--preferences-file", str(preferences), "--dry-run"])
        self.assertEqual(0, code)
        bundled_update.assert_called_once()
        saved = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertIs(True, saved["ok"])
        self.assertEqual(expected, saved["result"])
        self.assertEqual(["检查包身份", "No files changed."], saved["log"])
        self.assertEqual(bool(getattr(sys, "frozen", False)), saved["frozen"])
        self.assertFalse((self.root / "tools").exists())

    def test_headless_engine_error_is_saved_with_failure_exit_code(self):
        def update(*args, **kwargs):
            kwargs["notify"]("Identity inspection completed.")
            raise engine.UpdateError("Close Workbench before updating.")

        with patch.object(app, "update", side_effect=update):
            code = app.main([str(self.package), "--headless", "--report", str(self.report)])
        self.assertEqual(1, code)
        saved = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertIs(False, saved["ok"])
        self.assertEqual("Close Workbench before updating.", saved["error"])
        self.assertEqual(["Identity inspection completed."], saved["log"])
        self.assertNotIn("result", saved)

    def test_headless_requires_both_package_and_report_before_calling_engine(self):
        for arguments in ([str(self.package), "--headless"],
                          ["--headless", "--report", str(self.report)]):
            with self.subTest(arguments=arguments), patch.object(app, "update") as update:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    app.main(arguments)
                self.assertEqual(2, error.exception.code)
                update.assert_not_called()
                self.assertFalse(self.report.exists())

    @unittest.skipIf(gui is None, "Tkinter is not installed")
    def test_default_entry_point_opens_gui_with_optional_package_without_updating(self):
        for arguments, selected in (([], None), ([str(self.package)], str(self.package))):
            with self.subTest(arguments=arguments), patch.object(gui, "main") as open_gui, patch.object(
                    app, "update") as update:
                self.assertEqual(0, app.main(arguments))
                open_gui.assert_called_once_with(package=selected)
                update.assert_not_called()

    def test_command_line_update_options_require_explicit_headless_mode(self):
        with patch.object(app, "update") as update:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                app.main([str(self.package), "--dry-run", "--report", str(self.report)])
            self.assertEqual(2, error.exception.code)
            update.assert_not_called()
            self.assertFalse(self.report.exists())


@unittest.skipIf(gui is None, "Tkinter is not installed")
class RoundedSurfaceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.window = tk.Tk()
            self.window.withdraw()
        except tk.TclError as error:
            self.skipTest("Tk cannot initialize: " + str(error))
        self.addCleanup(self.window.destroy)

    def test_curved_edges_have_blended_pixels_and_are_symmetric(self):
        image = gui.rounded_surface(self.window, "#0071e3", "#0071e3", outside="#f5f5f7")
        pixels = [[image.get(x, y) for x in range(image.width())] for y in range(image.height())]
        colors = {color for row in pixels for color in row}
        self.assertGreater(len(colors), 3, "Curves need blended pixels, not a binary cutout")
        self.assertEqual((245, 245, 247), pixels[0][0])
        self.assertEqual((0, 113, 227), pixels[12][12])
        self.assertEqual(pixels, list(reversed(pixels)))
        for row in pixels:
            self.assertEqual(row, list(reversed(row)))

    def test_border_and_parent_background_remain_distinct(self):
        image = gui.rounded_surface(self.window, "#ffffff", "#dedee3", outside="#f5f5f7")
        self.assertEqual((222, 222, 227), image.get(12, 0))
        self.assertEqual((255, 255, 255), image.get(12, 12))
        white_parent = gui.rounded_surface(self.window, "#0071e3", "#0071e3", outside="#ffffff")
        self.assertEqual((255, 255, 255), white_parent.get(0, 0))
        self.assertNotEqual(image.get(0, 0), white_parent.get(0, 0))

    def test_sliding_thumb_corners_preserve_track_and_focus_outline_at_each_scale(self):
        for scale in (1, 1.25, 1.5, 2):
            p = lambda value: round(value * scale)
            width, height, inset = p(132), p(34), p(3)
            thumb_width = round((width - 2 * inset) / 2)
            for mode, c in gui.PALETTES.items():
                with self.subTest(scale=scale, mode=mode):
                    track_fill = tuple(int(c["toggle"][i:i + 2], 16) for i in (1, 3, 5))
                    track = gui.rounded_bitmap(self.window, width, height, c["toggle"],
                                               c["accent"], p(11), c["background"])
                    thumb = gui.rounded_bitmap(self.window, thumb_width, height - 2 * inset,
                                               c["toggle_selected"], c["toggle_selected"], p(8),
                                               c["toggle"], transparent_corners=True)
                    self.assertTrue(thumb.transparency_get(0, 0))
                    self.assertFalse(thumb.transparency_get(thumb_width // 2, thumb.height() // 2))
                    for left in (inset, width - inset - thumb_width):
                        for y in range(thumb.height()):
                            for x in range(thumb.width()):
                                if track.get(left + x, inset + y) != track_fill:
                                    self.assertTrue(thumb.transparency_get(x, y),
                                                    "Thumb erased the track's rounded focus outline")

    def test_palette_renderer_preserves_rounding_and_transparent_corners(self):
        for transparent in (False, True):
            original = gui.rounded_bitmap(self.window, 132, 34, "#50505b", "#0a84ff", 11,
                                          "#161618", transparent_corners=transparent)
            rendered = original.copy()
            gui.paint_surface(rendered, 11, "#50505b", "#0a84ff", "#161618", transparent)
            for y in range(34):
                for x in range(132):
                    self.assertEqual(original.get(x, y), rendered.get(x, y))
                    self.assertEqual(original.transparency_get(x, y), rendered.transparency_get(x, y))


@unittest.skipIf(gui is None, "Tkinter is not installed")
class UpdaterWorkerTests(unittest.TestCase):
    def test_worker_calls_bundled_api_and_emits_log_result_and_completion_events(self):
        worker = gui.UpdaterApp.__new__(gui.UpdaterApp)
        worker.events = queue.Queue()
        options = {"package_path": "arbitrary-location/Example.wbex", "dry_run": True,
                   "ansys_root": "custom-installation/v241"}
        expected = {"dry_run": True, "package": {"name": "示例"}}

        def update(**kwargs):
            self.assertEqual(options, {key: value for key, value in kwargs.items() if key != "notify"})
            kwargs["notify"]("Engine validation message")
            return expected

        with patch.object(gui, "update", side_effect=update) as update, patch.object(
                subprocess, "Popen", side_effect=AssertionError("external process launch")), patch.object(
                sys, "executable", "nonexistent-python.exe"):
            worker.update_worker(options)
        update.assert_called_once()
        self.assertEqual(("line", "Engine validation message\n"), worker.events.get_nowait())
        event, payload = worker.events.get_nowait()
        self.assertEqual("result", event)
        self.assertEqual(expected, payload)
        self.assertEqual(("done", 0), worker.events.get_nowait())
        self.assertTrue(worker.events.empty())

    def test_worker_queues_engine_error_for_ui_without_escaping_thread(self):
        worker = gui.UpdaterApp.__new__(gui.UpdaterApp)
        worker.events = queue.Queue()
        with patch.object(gui, "update", side_effect=engine.UpdateError("Package identity mismatch")):
            worker.update_worker({"package_path": "Example.wbex", "dry_run": False})
        self.assertEqual(("error", "UpdateError: Package identity mismatch"),
                         worker.events.get_nowait())
        self.assertTrue(worker.events.empty())

    def test_frozen_application_uses_executable_directory_for_adjacent_packages(self):
        try:
            with patch.object(sys, "frozen", True, create=True), patch.object(
                    sys, "executable", str(Path.cwd() / "standalone-copy/WBEX-Updater.exe")):
                importlib.reload(gui)
                self.assertEqual(Path(sys.executable).resolve().parent, gui.ROOT)
                self.assertEqual(gui.ROOT, gui.UpdaterApp.__init__.__defaults__[0])
        finally:
            importlib.reload(gui)


@unittest.skipIf(gui is None, "Tkinter is not installed")
class StandaloneUpdaterGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "LumiDyna.wbex"
        self.package.write_bytes(b"test package with a mocked update engine")
        try:
            self.window = tk.Tk()
            self.window.withdraw()
        except tk.TclError as error:
            self.skipTest("Tk cannot initialize: " + str(error))
        self.addCleanup(self.window.destroy)
        detection = patch.object(gui, "detect_ansys_installations", return_value=[])
        detection.start()
        self.addCleanup(detection.stop)
        messages = patch.object(gui.messagebox, "showerror")
        self.error_dialog = messages.start()
        self.addCleanup(messages.stop)
        info = patch.object(gui.messagebox, "showinfo")
        self.info_dialog = info.start()
        self.addCleanup(info.stop)
        warning = patch.object(gui.messagebox, "showwarning")
        self.warning_dialog = warning.start()
        self.addCleanup(warning.stop)

    def test_isolated_folder_auto_selects_only_package_and_starts_without_source_or_python(self):
        self.assertEqual([self.package], list(self.root.iterdir()))
        window_app = gui.UpdaterApp(self.window, root=self.root)
        self.assertEqual(str(self.package), window_app.package.get())
        window_app.ansys_root.set("custom-installation/v241")

        def update(**options):
            self.assertEqual(str(self.package.resolve()), options["package_path"])
            self.assertEqual("custom-installation/v241", options["ansys_root"])
            self.assertIs(True, options["dry_run"])
            options["notify"]("Bundled engine ran without a tools folder.")
            return {"dry_run": True}

        def immediate_thread(*, target, args, daemon):
            self.assertTrue(daemon)
            return Mock(start=lambda: target(*args))

        with patch.object(gui, "update", side_effect=update) as update, patch.object(
                gui.threading, "Thread", side_effect=immediate_thread), patch.object(
                subprocess, "Popen", side_effect=AssertionError("external process launch")), patch.object(
                sys, "executable", "no-python-installed.exe"):
            window_app.start(dry_run=True)
        self.assertTrue(window_app.busy)
        self.assertTrue(all(str(control.cget("state")) == "disabled" for control in window_app.controls))
        window_app.drain_events()
        update.assert_called_once()
        self.assertFalse(window_app.busy)
        self.assertTrue(all(str(control.cget("state")) == "normal" for control in window_app.controls))
        self.assertIn("本次未更改", window_app.status.get())
        self.assertEqual("检查成功", window_app.state_title.get())
        self.assertIn("Bundled engine ran without a tools folder.", "\n".join(window_app.details))
        self.assertNotIn("Bundled engine", window_app.log_text)
        self.error_dialog.assert_not_called()
        self.assertFalse((self.root / "tools").exists())

    def test_theme_defaults_dark_and_switch_preserves_inputs_busy_state_and_widgets(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.ansys_root.set("custom/v261")
        self.assertEqual("dark", window_app.theme_mode.get())
        self.assertEqual(gui.DARK_COLORS["background"], self.window.cget("background"))
        before = (window_app.package_entry, window_app.ansys_selector, window_app.drop_zone)
        with patch.object(gui.threading, "Thread"), patch.object(gui, "update") as update:
            window_app.start(dry_run=True)
            for mode in ("light", "dark"):
                window_app.theme_switch.select(mode, animate=False)
                self.assertEqual(mode, self.window._ld_theme_mode)
                self.assertEqual(gui.PALETTES[mode]["background"], self.window.cget("background"))
                self.assertTrue(window_app.busy)
                self.assertTrue(all(str(control.cget("state")) == "disabled" for control in window_app.controls))
                self.assertEqual(str(self.package), window_app.package.get())
                self.assertEqual("custom/v261", window_app.ansys_root.get())
                self.assertEqual(before, (window_app.package_entry, window_app.ansys_selector, window_app.drop_zone))
            update.assert_not_called()

    def test_theme_switch_updates_existing_details_and_dropdown_and_reuses_images(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.details.append("Keep this diagnostic text")
        window_app.show_details()
        text = window_app.details_text.get("1.0", "end")
        selector = window_app.ansys_selector
        selector.tk.call("ttk::combobox::PopdownWindow", str(selector))
        popup = str(selector) + ".popdown.f.l"
        window_app.theme_switch.select("light", animate=False)
        image_count = len(self.window._ld_theme_images)
        for mode in ("dark", "light", "dark", "light"):
            window_app.theme_switch.select(mode, animate=False)
            c = gui.PALETTES[mode]
            self.assertEqual(c["field"], window_app.details_text.cget("background"))
            self.assertEqual(c["text"], window_app.details_text.cget("foreground"))
            self.assertEqual(c["field"], selector.tk.call(popup, "cget", "-background"))
            self.assertEqual(c["text"], selector.tk.call(popup, "cget", "-foreground"))
            self.assertEqual(text, window_app.details_text.get("1.0", "end"))
            self.assertEqual(image_count, len(self.window._ld_theme_images))
        # Choosing Light affects this session; every fresh launch starts Dark.
        window_app.details_window.destroy()

    def test_theme_fade_has_intermediate_colors_and_reverses_from_live_brightness(self):
        with patch.object(gui, "system_motion_enabled", return_value=True):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.show_details()
        fade = window_app.theme_fade
        image_count = len(self.window._ld_theme_images)
        window_app.theme_switch.select("light")
        self.assertEqual(gui.DARK_COLORS["background"], self.window.cget("background"),
                         "Selecting Light must not flash the final palette")
        fade.cancel()
        with patch.object(gui.tk, "PhotoImage", side_effect=AssertionError("new fade bitmap")), patch.object(
                gui.ttk.Style, "theme_create", side_effect=AssertionError("new fade theme")):
            for amount in (0.1, 0.25, 0.5, 0.75):
                fade.render(amount)
                background = self.window.cget("background")
                self.assertNotIn(background, (gui.DARK_COLORS["background"], gui.LIGHT_COLORS["background"]))
                self.assertEqual(self.window._ld_palette["field"], window_app.details_text.cget("background"))
            fade.velocity = 0.4
            color = self.window.cget("background")
            window_app.theme_switch.select("dark")
            self.assertEqual(0.75, fade.alpha)
            self.assertEqual(0.4, fade.velocity)
            self.assertEqual(color, self.window.cget("background"))
        fade.to("light", animate=False)
        self.assertEqual(gui.LIGHT_COLORS["background"], self.window.cget("background"))
        fade.to("dark", animate=False)
        self.assertEqual(gui.DARK_COLORS["background"], self.window.cget("background"),
                         "The transition must not modify cached endpoint styles")
        self.assertEqual(image_count, len(self.window._ld_theme_images))
        window_app.details_window.destroy()

    def test_theme_slide_can_reverse_without_jumping_and_does_not_allocate_frames(self):
        with patch.object(gui, "system_motion_enabled", return_value=True):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        switch = window_app.theme_switch
        switch.select("light")
        self.assertEqual(0.0, switch.position)
        self.assertEqual(1.0, switch.target)
        switch.after_cancel(switch.timer_id)
        switch.timer_id = None
        switch.position, switch.velocity = gui.spring_step(0, 0, 1, 0.08)
        position, velocity = switch.position, switch.velocity
        self.assertTrue(0 < position < 1)
        self.assertGreater(velocity, 0)
        switch.select("dark")
        self.assertEqual(position, switch.position)
        self.assertEqual(velocity, switch.velocity, "Reversing must preserve the live spring velocity")
        self.assertEqual(0.0, switch.target)
        switch.after_cancel(switch.timer_id)
        switch.timer_id = None
        assets = dict(switch.assets)
        with patch.object(gui.tk, "PhotoImage", side_effect=AssertionError("per-frame bitmap allocation")):
            for _ in range(35):
                switch.last_time = gui.time.perf_counter() - 0.016
                switch._tick()
                if switch.timer_id is not None:
                    switch.after_cancel(switch.timer_id)
                    switch.timer_id = None
        self.assertEqual(0, switch.position)
        self.assertEqual(assets, switch.assets)

    def test_theme_slide_reduced_motion_keyboard_and_cancelled_click(self):
        with patch.object(gui, "system_motion_enabled", return_value=False):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        switch = window_app.theme_switch
        switch.select("light")
        self.assertEqual(1, switch.position)
        self.assertIsNone(switch.timer_id)
        switch.motion_enabled = True
        switch._key("dark")
        self.assertEqual("dark", window_app.theme_mode.get())
        self.assertEqual(0, switch.position)
        self.assertIsNone(switch.timer_id)
        switch._press(SimpleNamespace(x=switch.width - 10, y=10))
        self.assertEqual(1, switch.target)
        switch._release(SimpleNamespace(x=-10, y=10))
        self.assertEqual("dark", window_app.theme_mode.get())
        self.assertEqual(0, switch.target)

    def test_theme_slide_destroy_cancels_pending_timer(self):
        with patch.object(gui, "system_motion_enabled", return_value=True):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        switch = window_app.theme_switch
        switch.select("light")
        timer_id = switch.timer_id
        self.assertIsNotNone(timer_id)
        switch.destroy()
        self.assertIsNone(switch.timer_id)
        self.assertNotIn(timer_id, self.window.tk.call("after", "info"))

    def test_invalid_package_reports_error_without_starting_engine(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.package.set(str(self.root / "wrong-format.xml"))
        with patch.object(gui, "update") as update, patch.object(gui.threading, "Thread") as thread:
            window_app.start()
        self.error_dialog.assert_called_once()
        self.assertIn("未找到", window_app.status.get())
        self.assertIn("浏览", window_app.next_step.get())
        self.assertIn("文件不存在", window_app.package_hint.get())
        update.assert_not_called()
        thread.assert_not_called()
        self.assertFalse(window_app.busy)

    def test_multi_version_gui_prefers_v241_and_keeps_manual_selection(self):
        newest = self.root / "Ansys/v261"
        older = self.root / "Ansys/v241"
        with patch.object(gui, "detect_ansys_installations", return_value=[newest, older]):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        self.assertEqual(str(older), window_app.ansys_root.get())
        self.assertEqual((str(newest), str(older)), window_app.ansys_selector.cget("values"))
        self.assertIn("2024 R1 (v241)", window_app.version_hint.get())
        window_app.ansys_root.set(str(newest))
        self.assertIn("2026 R1 (v261)", window_app.version_hint.get())
        custom = self.root / "custom-installation/v262"
        window_app.ansys_root.set(str(custom))
        self.assertIn("2026 R2 (v262)", window_app.version_hint.get())
        with patch.object(gui.threading, "Thread") as thread:
            window_app.start(dry_run=True)
        self.assertEqual(str(custom), thread.call_args.kwargs["args"][0]["ansys_root"])

    def test_without_v241_gui_falls_back_to_latest_detected_version(self):
        latest = self.root / "Ansys/v261"
        other = self.root / "Ansys/v251"
        with patch.object(gui, "detect_ansys_installations", return_value=[latest, other]):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        self.assertEqual(str(latest), window_app.ansys_root.get())
        self.assertIn("2026 R1 (v261)", window_app.version_hint.get())

    def test_no_detected_version_leaves_path_empty_without_v241_fallback(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        self.assertEqual("", window_app.ansys_root.get())
        self.assertFalse(window_app.ansys_selector.cget("values"))
        self.assertIn("未检测到", window_app.version_hint.get())

    def test_deferred_startup_constructs_window_without_touching_discovery_paths(self):
        with patch.object(gui, "detect_ansys_installations", side_effect=AssertionError("blocking discovery")), \
                patch.object(Path, "glob", side_effect=AssertionError("blocking directory scan")):
            window_app = gui.UpdaterApp(self.window, root=self.root, defer_detection=True)
        self.assertTrue(window_app.startup_pending)
        self.assertEqual("", window_app.ansys_root.get())
        self.assertIn("后台检测", window_app.version_hint.get())
        window_app.record_window_ready()
        self.assertIn("Python 入口至界面就绪", "\n".join(window_app.details))
        self.assertNotIn("启动计时", window_app.log_text)

    def test_background_discovery_prefers_v241_and_preserves_user_changes(self):
        window_app = gui.UpdaterApp(self.window, root=self.root, defer_detection=True)
        roots = [self.root / "v261", self.root / "v241"]
        with patch.object(gui, "detect_ansys_installations", return_value=roots):
            window_app._startup_worker()
        window_app.drain_events()
        self.assertFalse(window_app.startup_pending)
        self.assertEqual(str(roots[1]), window_app.ansys_root.get())
        self.assertEqual(str(self.package), window_app.package.get())
        self.assertIn("Ansys 路径检测", "\n".join(window_app.details))
        window_app.ansys_root.set("custom/v262")
        window_app.package.set("manually-selected.wbex")
        with patch.object(gui, "detect_ansys_installations", return_value=roots):
            window_app._startup_worker()
        window_app.drain_events()
        self.assertEqual("custom/v262", window_app.ansys_root.get())
        self.assertEqual("manually-selected.wbex", window_app.package.get())

    def test_gui_worker_failure_restores_controls_and_displays_error(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.busy = True
        window_app.dry_run = False
        for control in window_app.controls:
            control.configure(state="disabled")
        with patch.object(gui, "update", side_effect=engine.UpdateError("Workbench is running")):
            window_app.update_worker({"package_path": str(self.package), "dry_run": False})
        window_app.drain_events()
        self.assertFalse(window_app.busy)
        self.assertTrue(all(str(control.cget("state")) == "normal" for control in window_app.controls))
        self.assertIn("仍在运行", window_app.status.get())
        self.assertEqual("更新失败", window_app.state_title.get())
        self.assertIn("仍在运行", window_app.log_text)
        self.assertIn("请保存工作并关闭", window_app.log_text)
        self.assertIn("Workbench is running", "\n".join(window_app.details))
        self.error_dialog.assert_called_once()
        self.assertIn("请保存工作并关闭", window_app.next_step.get())

    def test_user_consent_closes_hosts_then_retries_original_update(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        names = ("AnsysWBU.exe",)
        options = {"package_path": str(self.package), "ansys_root": "custom/v241", "dry_run": False}
        calls = []

        def update(**kwargs):
            calls.append("update")
            self.assertEqual("custom/v241", kwargs["ansys_root"])
            self.assertNotIn("_close_processes", kwargs)
            if len(calls) == 1:
                raise engine.AnsysProcessesRunning(names)
            return {"backup": "backup-path"}

        def immediate_thread(*, target, args, daemon):
            return Mock(start=lambda: target(*args))

        window_app.busy = True
        window_app.dry_run = False
        with patch.object(gui, "update", side_effect=update), \
                patch.object(gui, "close_ansys_processes", side_effect=lambda approved: calls.append("close")) as close, \
                patch.object(gui.messagebox, "askyesno", return_value=True) as confirm, \
                patch.object(gui.threading, "Thread", side_effect=immediate_thread):
            window_app.update_worker(options)
            confirm.assert_not_called()  # Worker only queues a request for the Tk thread.
            window_app.drain_events()
        self.assertEqual(["update", "close", "update"], calls)
        close.assert_called_once_with(names)
        self.assertIn("未保存", confirm.call_args.args[1])
        self.assertIn(names[0], confirm.call_args.args[1])
        self.assertEqual(gui.messagebox.NO, confirm.call_args.kwargs["default"])
        self.assertFalse(window_app.busy)
        self.assertEqual("更新成功", window_app.state_title.get())

    def test_declining_closure_cancels_without_closing_or_retrying(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.busy = True
        window_app.dry_run = False
        with patch.object(gui, "update", side_effect=engine.AnsysProcessesRunning(["SpaceClaim.exe"])) as update, \
                patch.object(gui, "close_ansys_processes") as close, \
                patch.object(gui.messagebox, "askyesno", return_value=False):
            window_app.update_worker({"package_path": str(self.package), "dry_run": False})
            window_app.drain_events()
        update.assert_called_once()
        close.assert_not_called()
        self.assertEqual("更新已取消", window_app.state_title.get())
        self.assertFalse(window_app.busy)
        self.assertTrue(all(str(control.cget("state")) == "normal" for control in window_app.controls))
        self.error_dialog.assert_not_called()

    def test_closure_failure_stops_before_retry_and_restores_controls(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.busy = True
        window_app.dry_run = False
        with patch.object(gui, "close_ansys_processes", side_effect=engine.UpdateError(
                "Cannot close Ansys processes: access denied")), patch.object(gui, "update") as update:
            window_app.update_worker({"package_path": str(self.package), "dry_run": False,
                                      "_close_processes": ("AnsysWBU.exe",)})
            window_app.drain_events()
        update.assert_not_called()
        self.assertFalse(window_app.busy)
        self.assertIn("无法强制关闭", window_app.status.get())
        self.error_dialog.assert_called_once()

    def test_check_only_never_closes_processes_or_requests_consent(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.dry_run = True
        with patch.object(gui, "update", return_value={"dry_run": True}), \
                patch.object(gui, "close_ansys_processes") as close, \
                patch.object(gui.messagebox, "askyesno") as confirm:
            window_app.update_worker({"package_path": str(self.package), "dry_run": True,
                                      "_close_processes": ("AnsysWBU.exe",)})
            window_app.drain_events()
        close.assert_not_called()
        confirm.assert_not_called()

    def test_update_success_shows_result_and_backup_without_json(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.events.put(("line", "Package: LumiDynaLite 1.9 / private-guid\n"))
        window_app.events.put(("line", "Target Ansys: v241 / C:/Ansys/v241\n"))
        window_app.events.put(("result", {"backup": "C:/backup", "load_as_default": True}))
        window_app.events.put(("done", 0))
        window_app.drain_events()
        log = window_app.log_text
        for expected in ("更新成功", "默认加载", "LumiDynaLite 1.9", "v241", "C:/backup"):
            self.assertIn(expected, log)
        self.assertNotIn("private-guid", log)
        self.assertNotIn('"load_as_default"', log)
        self.assertIn("private-guid", "\n".join(window_app.details))
        self.info_dialog.assert_called_once()
        title, message = self.info_dialog.call_args.args
        self.assertEqual("更新成功", title)
        self.assertIn("默认加载", message)
        self.assertIn("C:/backup", message)

    def test_failure_recovery_is_reported_only_when_confirmed_by_engine(self):
        for recovery, expected in (("previous installation restored.", "已恢复更新前"),
                                   ("rollback needs attention: locked", "未能完整恢复")):
            window_app = gui.UpdaterApp(self.window, root=self.root)
            window_app.events.put(("error", "PermissionError: denied\nUpdate failed; " + recovery +
                                   "\nRecovery files: C:/recovery"))
            window_app.drain_events()
            log = window_app.log_text
            self.assertIn(expected, log)
            self.assertIn("C:/recovery", log)
            self.assertNotIn("更新成功", log)
            self.assertIn(expected, self.error_dialog.call_args.args[1])
            self.assertIn("C:/recovery", self.error_dialog.call_args.args[1])

    def test_compact_window_has_drop_prompt_without_log_status_panel_or_gray_notes(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)

        def labels(widget):
            for child in widget.winfo_children():
                if isinstance(child, gui.ttk.Label):
                    yield child
                yield from labels(child)

        visible_labels = list(labels(self.window))
        text = [str(label.cget("text")) for label in visible_labels]
        self.assertIn("将 .wbex 文件拖到这里", text)
        for removed in ("运行记录", "准备检查", "保存日志…", "技术详情"):
            self.assertNotIn(removed, text)
        self.assertFalse(hasattr(window_app, "log"))
        self.assertFalse(hasattr(window_app, "state_label"))
        self.assertFalse(any("Muted" in str(label.cget("style")) or "Caption" in str(label.cget("style"))
                             for label in visible_labels))

    def test_check_success_is_reported_in_popup_without_changing_package(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.dry_run = True
        window_app.finish(0)
        self.assertEqual("检查成功", self.info_dialog.call_args.args[0])
        self.assertIn("本次未更改", self.info_dialog.call_args.args[1])
        self.assertEqual(str(self.package), window_app.package.get())

    def test_saved_log_contains_user_summary_and_original_error(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.events.put(("error", "UpdateError: unknown original diagnostic"))
        window_app.drain_events()
        destination = self.root / "saved.log"
        with patch.object(gui.filedialog, "asksaveasfilename", return_value=str(destination)):
            window_app.save_log()
        saved = destination.read_text(encoding="utf-8")
        self.assertIn("更新失败", saved)
        self.assertIn("unknown original diagnostic", saved)

    def test_editing_inputs_clears_stale_success_and_validates_suffix_without_io(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.finish(0)
        self.assertEqual("更新成功", window_app.state_title.get())
        with patch.object(Path, "is_file", side_effect=AssertionError("typing must not probe disks")):
            window_app.package.set("new-package.xml")
        self.assertNotIn("成功", window_app.state_title.get())
        self.assertIn("不能选择 XML", window_app.package_hint.get())
        window_app.package.set(str(self.package))
        self.assertEqual("", window_app.package_hint.get())
        window_app.finish(0)
        window_app.ansys_root.set("custom/v261")
        self.assertEqual("准备检查", window_app.state_title.get())

    def test_return_checks_only_from_path_input_and_skips_buttons(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        with patch.object(window_app, "start") as start, patch.object(
                self.window, "focus_get", return_value=window_app.package_entry):
            self.assertEqual("break", window_app.keyboard_check())
        start.assert_called_once_with(dry_run=True)
        with patch.object(window_app, "start") as start, patch.object(
                self.window, "focus_get", return_value=window_app.drop_title):
            window_app.keyboard_check()
        start.assert_not_called()

    def test_details_window_is_reused_and_follows_new_diagnostics(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.details.append("first diagnostic")
        window_app.show_details()
        dialog = window_app.details_window
        window_app.show_details()
        self.assertIs(dialog, window_app.details_window)
        self.assertIn("first diagnostic", window_app.details_text.get("1.0", "end"))
        window_app.events.put(("line", "new diagnostic"))
        window_app.drain_events()
        self.assertIn("new diagnostic", window_app.details_text.get("1.0", "end"))
        dialog.destroy()
        window_app.show_details()
        self.assertIsNot(dialog, window_app.details_window)

    def test_reduced_motion_keeps_operation_feedback_without_animated_progress(self):
        with patch.object(gui, "system_motion_enabled", return_value=False):
            window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.ansys_root.set("custom/v241")
        with patch.object(gui.threading, "Thread"), patch.object(window_app.progress, "start") as animate:
            window_app.start(dry_run=True)
        self.assertEqual("正在检查", window_app.state_title.get())
        self.assertIn("只检查", window_app.next_step.get())
        animate.assert_not_called()

    def test_pixel_layout_scales_with_fonts_without_reapplying_scale(self):
        for factor in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(factor=factor):
                # Each simulated DPI needs an independent Tcl interpreter/theme.
                window = tk.Tk()
                try:
                    window.withdraw()
                    window._ld_ui_scale = factor
                    window._ld_dpi = 96 * factor
                    window.tk.call("tk", "scaling", 96 * factor / 72)
                    ui = gui.UpdaterApp(window, root=self.root)
                    self.assertEqual((round(660 * factor), round(460 * factor)), window.minsize())
                    padding = tuple(map(str, window.winfo_children()[0].cget("padding")))
                    self.assertEqual(round(24 * factor), int(padding[0]))
                    gui.scale_widget_tree(window)
                    self.assertEqual(padding, tuple(map(str, window.winfo_children()[0].cget("padding"))))
                finally:
                    window.destroy()

    def test_source_entry_enables_dpi_before_tk_creation(self):
        import ctypes
        calls = []
        user32 = SimpleNamespace(SetProcessDPIAware=lambda: calls.append("dpi"))
        with patch.object(gui.sys, "platform", "win32"), patch.object(
                ctypes, "windll", SimpleNamespace(user32=user32), create=True), patch.object(
                gui.tk, "Tk", side_effect=lambda: calls.append("tk") or self.window), patch.object(
                gui, "initialize_scale", side_effect=lambda window: calls.append("scale")):
            self.assertIs(self.window, gui.create_window())
        self.assertEqual(["dpi", "tk", "scale"], calls)

    def test_check_button_gives_feedback_before_any_path_probe(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.package.set(r"\\offline-server\share\new.wbex")
        with patch.object(Path, "is_file", side_effect=AssertionError("UI stat")), patch.object(
                Path, "resolve", side_effect=AssertionError("UI resolve")), patch.object(
                gui.threading, "Thread") as thread:
            window_app.start(dry_run=True)
        self.assertTrue(window_app.busy)
        self.assertEqual("正在检查", window_app.state_title.get())
        self.assertEqual(r"\\offline-server\share\new.wbex", thread.call_args.kwargs["args"][0]["package_path"])

    def test_browse_does_not_probe_an_invalid_network_path(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.package.set(r"\\offline-server\share\new.wbex")
        with patch.object(Path, "is_dir", side_effect=AssertionError("UI directory probe")), patch.object(
                gui.filedialog, "askopenfilename", return_value=str(self.package)) as dialog:
            window_app.choose_package()
        self.assertEqual(str(self.root), dialog.call_args.kwargs["initialdir"])
        self.assertEqual(str(self.root), window_app.initial_directory(str(self.package)))

    def test_drop_selects_one_unicode_package_without_io_or_installing(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        dropped = str(self.root / "中文 发布 {测试}" / "新版 插件.WBEX")
        with patch.object(Path, "is_file", side_effect=AssertionError("drop path probe")), patch.object(
                Path, "resolve", side_effect=AssertionError("drop path resolve")), patch.object(
                gui, "update") as install:
            window_app.events.put(("drop", {"count": 1, "paths": [dropped], "busy": False}))
            window_app.drain_events()
        self.assertEqual(dropped, window_app.package.get())
        self.assertIn("已选择拖入", window_app.status.get())
        self.assertFalse(window_app.busy)
        install.assert_not_called()

    def test_invalid_or_multiple_drops_keep_previous_package(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        for payload in ({"count": 2, "paths": [], "busy": False},
                        {"count": 1, "paths": ["invalid.zip"], "busy": False}):
            window_app.accept_drop(payload)
            self.assertEqual(str(self.package), window_app.package.get())
            self.assertIn(".wbex", window_app.next_step.get())

    def test_busy_drop_snapshot_survives_operation_finishing_before_queue_drain(self):
        window_app = gui.UpdaterApp(self.window, root=self.root)
        window_app.events.put(("drop", {"count": 1, "paths": ["another.wbex"], "busy": True}))
        window_app.busy = False
        window_app.drain_events()
        self.assertEqual(str(self.package), window_app.package.get())
        self.assertIn("未更改安装包", window_app.log_text)

    def test_visible_repainting_does_not_starve_timers(self):
        # Isolate a real native-DPI event loop from the other hidden Tcl roots.
        script = """
import json, sys, time
from pathlib import Path
from tools import wbex_updater_gui as gui
window = gui.create_window()
ui = gui.UpdaterApp(window, root=Path(sys.argv[1]))
beats = []
previous = [time.perf_counter()]
def pulse():
    now = time.perf_counter()
    beats.append(now - previous[0])
    previous[0] = now
    window.after(10, pulse)
window.after(10, pulse)
window.after(120, lambda: ui.drop_title.configure(text='File drop ready'))
window.after(500, window.quit)
started = time.perf_counter()
window.mainloop()
if sys.platform == 'win32':
    assert ui.drop_target is not None
    assert ui.drop_target._user.GetParent(window.winfo_id()) in ui.drop_target._handles
print(json.dumps({'beats': len(beats), 'elapsed': time.perf_counter() - started, 'gap': max(beats)}))
window.destroy()
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        metrics = json.loads(result.stdout)
        self.assertGreater(metrics["beats"], 5)
        self.assertLess(metrics["elapsed"], 1.5, "Panel repaint blocked the event loop")
        self.assertLess(metrics["gap"], 0.75, "Tiny image tiles caused a long paint stall")

    def test_visible_theme_fade_displays_intermediate_brightness_without_blocking(self):
        script = """
import json, time, sys
from pathlib import Path
from tools import wbex_updater_gui as gui
window = gui.create_window()
ui = gui.UpdaterApp(window, root=Path(sys.argv[1]))
ui.motion_enabled = True
colors, gaps = [], []
last = [time.perf_counter()]
def sample():
    now = time.perf_counter()
    gaps.append(now - last[0]); last[0] = now
    colors.append(window.cget('background'))
    window.after(10, sample)
window.after(10, sample)
window.after(50, lambda: ui.theme_switch.select('light'))
deadline = time.perf_counter() + 2
def finish_when_ready():
    if (ui.theme_mode.get() == 'light' and ui.theme_fade.timer_id is None) or time.perf_counter() > deadline:
        colors.append(window.cget('background'))
        window.quit()
    else:
        window.after(20, finish_when_ready)
window.after(100, finish_when_ready)
window.mainloop()
print(json.dumps({'colors': colors, 'gap': max(gaps)}))
ui.close()
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        metrics = json.loads(result.stdout)
        colors = metrics["colors"]
        self.assertEqual(gui.DARK_COLORS["background"], colors[0])
        self.assertEqual(gui.LIGHT_COLORS["background"], colors[-1])
        self.assertGreater(len(set(colors)) - 2, 8, "The window must actually paint intermediate colors")
        self.assertEqual(sorted(int(color[1:3], 16) for color in colors),
                         [int(color[1:3], 16) for color in colors])
        self.assertLess(metrics["gap"], 0.15, "Palette updates blocked native input/timers")


@unittest.skipIf(gui is None, "Tkinter is not installed")
class FailureExplanationTests(unittest.TestCase):
    def test_common_failures_give_specific_action_and_unknown_stays_honest(self):
        cases = (("same GUID in Additional Extension Folders", "开发路径"),
                 ("Select an existing .wbex package: missing.wbex", "重新选择"),
                 ("Another update is active", "锁文件"),
                 ("Ansys installation must contain", "v241"),
                 ("WBEX resource validation failed", "重新获取"),
                 ("PermissionError: denied", "账户"),
                 ("[WinError 112]", "释放"),
                 ("mystery", "错误详情"))
        for raw, action in cases:
            with self.subTest(raw=raw):
                self.assertIn(action, " ".join(gui.explain_failure(raw)))


if __name__ == "__main__":
    unittest.main()
