"""Check actual DWM caption colors against the palette painted by Tk."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import wbex_updater_gui as gui


@unittest.skipUnless(sys.platform == "win32", "Windows native title bar")
class NativeTitlebarTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.window = gui.create_window()
        self.addCleanup(self.window.destroy)
        with patch.object(gui, "detect_ansys_installations", return_value=[]):
            self.app = gui.UpdaterApp(self.window, root=Path(temporary.name))
        self.app.show_details()
        self.window.update()

    def test_native_caption_and_text_follow_each_intermediate_client_color(self):
        if sys.getwindowsversion().build < 22000:
            self.skipTest("Caption color attributes require Windows 11")
        user, dwm = gui.titlebar_api()
        native_setter, accepted = dwm.DwmSetWindowAttribute, {}

        def capture(hwnd, attribute, data, size):
            # Caption colors are documented for Set, not Get. Check values
            # accepted by the real native setter instead of an unsupported getter.
            result = native_setter(hwnd, attribute, data, size)
            if attribute in (35, 36):
                self.assertEqual(0, result)
                accepted[hwnd, attribute] = ctypes.cast(data, ctypes.POINTER(wintypes.DWORD)).contents.value
            return result

        for window in (self.window, self.app.details_window):
            window._ld_titlebar_state = None
        with patch.object(dwm, "DwmSetWindowAttribute", side_effect=capture):
            for amount in (0, 0.2, 0.5, 0.8, 1, 0.6, 0.3, 0):
                with self.subTest(amount=amount):
                    self.app.theme_fade.render(amount)
                    palette = self.window._ld_palette
                    for window in (self.window, self.app.details_window):
                        hwnd = user.GetParent(window.winfo_id())
                        self.assertEqual(palette["background"], window.cget("background"))
                        self.assertEqual(gui.colorref(palette["background"]), accepted[hwnd, 35])
                        self.assertEqual(gui.colorref(palette["text"]), accepted[hwnd, 36])

    def test_older_system_fallback_does_not_retry_unsupported_colors_each_frame(self):
        setter = Mock(side_effect=lambda hwnd, attribute, data, size: 0 if attribute == 20 else -2147024809)
        api = (SimpleNamespace(GetParent=Mock(return_value=123)), SimpleNamespace(DwmSetWindowAttribute=setter))
        self.window._ld_titlebar_state = None
        with patch.object(gui, "titlebar_api", return_value=api):
            gui.apply_titlebar_theme(self.window, gui.DARK_COLORS)
            self.assertFalse(self.window._ld_caption_colors_supported)
            gui.apply_titlebar_theme(self.window, gui.LIGHT_COLORS)
            self.assertEqual([20, 35, 36, 20], [call.args[1] for call in setter.call_args_list])


if __name__ == "__main__":
    unittest.main()
