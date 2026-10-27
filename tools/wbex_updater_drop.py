# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: Apache-2.0
"""Native Windows file drops, without an additional Tcl/Tk or Python runtime."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


class WindowsFileDrop:
    WM_DROPFILES = 0x0233
    WM_NCDESTROY = 0x0082

    def __init__(self, window, events, busy, extra_windows=()):
        if sys.platform != "win32":
            raise OSError("Native file drops require Windows.")
        self.events, self.busy = events, busy
        self.window, self.extra_windows = window, extra_windows
        self._handles = set()
        self._shell = ctypes.WinDLL("shell32", use_last_error=True)
        self._controls = ctypes.WinDLL("comctl32", use_last_error=True)
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self._callback = self._callback_type(self._message)
        self._id = id(self)
        self._user.GetParent.argtypes = [wintypes.HWND]
        self._user.GetParent.restype = wintypes.HWND
        self._shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self._shell.DragAcceptFiles.restype = None
        self._shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        self._shell.DragQueryFileW.restype = wintypes.UINT
        self._shell.DragFinish.argtypes = [wintypes.HANDLE]
        self._shell.DragFinish.restype = None
        self._controls.SetWindowSubclass.argtypes = [
            wintypes.HWND, self._callback_type, ctypes.c_size_t, ctypes.c_size_t]
        self._controls.SetWindowSubclass.restype = wintypes.BOOL
        self._controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, self._callback_type, ctypes.c_size_t]
        self._controls.RemoveWindowSubclass.restype = wintypes.BOOL
        self._controls.DefSubclassProc.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._controls.DefSubclassProc.restype = ctypes.c_ssize_t

        try:
            self.refresh()
        except Exception:
            self.close()
            raise
        # A Windows callback must not be garbage-collected while its HWND lives.
        window._ld_file_drop = self

    def refresh(self):
        """Tk may replace its native wrapper when first mapping the window."""
        client = self.window.winfo_id()
        handles = {client, self._user.GetParent(client)}
        handles.update(item.winfo_id() for item in self.extra_windows)
        desired = handles - {None, 0}
        for handle in self._handles - desired:
            self._shell.DragAcceptFiles(handle, False)
            self._controls.RemoveWindowSubclass(handle, self._callback, self._id)
            self._handles.discard(handle)
        for handle in desired - self._handles:
            if not self._controls.SetWindowSubclass(handle, self._callback, self._id, 0):
                raise OSError("Cannot register the native file drop handler.")
            self._handles.add(handle)
        for handle in desired:
            self._shell.DragAcceptFiles(handle, True)

    def _message(self, hwnd, message, wparam, lparam, subclass_id, reference):
        if message == self.WM_DROPFILES:
            try:
                count = self._shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                payload = {"count": count, "paths": [], "busy": bool(self.busy())}
                if count == 1 and not payload["busy"]:
                    length = self._shell.DragQueryFileW(wparam, 0, None, 0)
                    if not 0 < length <= 32767:
                        raise ValueError("The dropped file path cannot be read.")
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    if self._shell.DragQueryFileW(wparam, 0, buffer, length + 1) != length:
                        raise ValueError("The dropped file path is incomplete.")
                    payload["paths"] = [buffer.value]
                # Do not call Tk or touch the disk from a Windows message hook.
                self.events.put(("drop", payload))
            except Exception as error:
                self.events.put(("drop_error", str(error)))
            finally:
                self._shell.DragFinish(wparam)
            return 0
        if message == self.WM_NCDESTROY:
            self._controls.RemoveWindowSubclass(hwnd, self._callback, self._id)
            self._handles.discard(hwnd)
        return self._controls.DefSubclassProc(hwnd, message, wparam, lparam)

    def close(self):
        """Unregister on the Tk UI thread, retaining the callback during removal."""
        for handle in tuple(self._handles):
            self._shell.DragAcceptFiles(handle, False)
            self._controls.RemoveWindowSubclass(handle, self._callback, self._id)
            self._handles.discard(handle)
