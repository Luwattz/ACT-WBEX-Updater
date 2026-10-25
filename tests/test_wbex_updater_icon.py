"""Check the pixels Windows receives, rather than only the ICO's dimensions."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import sys
import tkinter as tk
import unittest

from tools.wbex_updater_gui import create_window
from tools.wbex_updater_icon import WindowsWindowIcons


class IconInfo(ctypes.Structure):
    _fields_ = [("icon", w.BOOL), ("x", w.DWORD), ("y", w.DWORD),
                ("mask", w.HBITMAP), ("color", w.HBITMAP)]


class Bitmap(ctypes.Structure):
    _fields_ = [("type", w.LONG), ("width", w.LONG), ("height", w.LONG),
                ("stride", w.LONG), ("planes", w.WORD), ("bits", w.WORD),
                ("data", ctypes.c_void_p)]


@unittest.skipUnless(sys.platform == "win32", "Windows native window icons")
class NativeIconTests(unittest.TestCase):
    def setUp(self):
        self.root = create_window()
        self.addCleanup(self.destroy_root)
        self.user = self.root._ld_window_icons.user
        self.user.GetIconInfo.argtypes = [w.HICON, ctypes.POINTER(IconInfo)]
        self.gdi = ctypes.WinDLL("gdi32")
        self.gdi.GetObjectW.argtypes = [w.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
        self.gdi.GetBitmapBits.argtypes = [w.HBITMAP, w.LONG, ctypes.c_void_p]
        self.gdi.DeleteObject.argtypes = [w.HGDIOBJ]

    def destroy_root(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None

    def pixels(self, handle):
        info, bitmap = IconInfo(), Bitmap()
        self.assertTrue(self.user.GetIconInfo(handle, ctypes.byref(info)))
        try:
            self.gdi.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
            buffer = ctypes.create_string_buffer(bitmap.stride * bitmap.height)
            self.gdi.GetBitmapBits(info.color, len(buffer), buffer)
            return bitmap.width, bitmap.height, buffer.raw
        finally:
            self.gdi.DeleteObject(info.color)
            self.gdi.DeleteObject(info.mask)

    def test_mapped_root_and_dialog_receive_exact_native_frame_pixels(self):
        icon_path = Path(__file__).resolve().parents[1] / "tools/assets/wbex-updater/updater.ico"
        controller = self.root._ld_window_icons
        for dpi in (96, 144, 192):
            with self.subTest(dpi=dpi):
                self.root._ld_dpi = dpi
                self.root.withdraw()
                controller.close()
                controller = WindowsWindowIcons(self.root, icon_path)
                self.root._ld_window_icons = controller
                self.root.deiconify()
                dialog = tk.Toplevel(self.root)
                self.root.update()
                try:
                    for window in (self.root, dialog):
                        hwnd = self.user.GetParent(window.winfo_id())
                        for kind, size in controller.sizes.items():
                            # A large-enough destination alone is insufficient: Tk's
                            # class icon has these dimensions but blurred pixels.
                            actual = self.user.SendMessageW(hwnd, 0x7f, kind, 0)
                            reference = self.user.LoadImageW(None, str(icon_path), 1, *size, 0x10)
                            try:
                                self.assertEqual(size, self.pixels(actual)[:2])
                                self.assertEqual(self.pixels(reference), self.pixels(actual))
                            finally:
                                self.user.DestroyIcon(reference)
                finally:
                    dialog.destroy()
        owned = list(controller.icons.values())
        self.destroy_root()
        self.assertTrue(controller.closed)
        for handle in owned:
            self.assertFalse(self.user.GetIconInfo(handle, ctypes.byref(IconInfo())))


if __name__ == "__main__":
    unittest.main()
