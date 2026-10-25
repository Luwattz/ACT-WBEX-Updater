# Copyright (c) 2026 Intelligent Efficiency Team. All rights reserved.
"""Load native-size window icons without Tk's ICO bitmap resampling."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk


class WindowsWindowIcons:
    """Own HICONs until all application windows have been destroyed."""

    def __init__(self, root, path):
        self.root = root
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                        wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.LoadImageW.restype = wintypes.HICON
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        self.user.SendMessageW.restype = ctypes.c_ssize_t
        self.user.DestroyIcon.argtypes = [wintypes.HICON]
        self.user.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.icons = {}
        self.sizes = {}
        self.closed = False
        metric = self.user.GetSystemMetrics
        if hasattr(self.user, "GetSystemMetricsForDpi") and hasattr(root, "_ld_dpi"):
            metric_dpi = self.user.GetSystemMetricsForDpi
            metric_dpi.argtypes = [ctypes.c_int, wintypes.UINT]
            metric = lambda index: metric_dpi(index, round(root._ld_dpi))
        try:
            # ICON_SMALL: title bar; ICON_BIG: taskbar and Alt+Tab.
            for kind, width_metric, height_metric in ((0, 49, 50), (1, 11, 12)):
                size = (metric(width_metric), metric(height_metric))
                handle = self.user.LoadImageW(None, str(path), 1, *size, 0x10)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.icons[kind] = handle
                self.sizes[kind] = size
        except Exception:
            self.close()
            raise
        root.bind_all("<Map>", self._on_map, add="+")
        root.bind("<Destroy>", self._on_destroy, add="+")
        self.apply(root)

    def apply(self, window):
        if self.closed or not window.winfo_exists():
            return
        # Tk replaces its native wrapper when the window is first mapped.
        hwnd = self.user.GetParent(window.winfo_id())
        if hwnd:
            for kind, handle in self.icons.items():
                self.user.SendMessageW(hwnd, 0x80, kind, handle)  # WM_SETICON

    def _on_map(self, event):
        if isinstance(event.widget, (tk.Tk, tk.Toplevel)):
            self.apply(event.widget)

    def _on_destroy(self, event):
        if event.widget is self.root:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        for handle in self.icons.values():
            self.user.DestroyIcon(handle)
        self.icons.clear()
