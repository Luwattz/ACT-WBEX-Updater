# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
"""Native Windows file drops, without an additional Tcl/Tk or Python runtime."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


class _FormatEtc(ctypes.Structure):
    _fields_ = [("format", wintypes.WORD), ("device", ctypes.c_void_p),
                ("aspect", wintypes.DWORD), ("index", wintypes.LONG), ("medium", wintypes.DWORD)]


class _StorageMedium(ctypes.Structure):
    _fields_ = [("medium", wintypes.DWORD), ("data", ctypes.c_void_p), ("owner", ctypes.c_void_p)]


class WindowsFileDrop:
    WM_DROPFILES = 0x0233
    WM_NCDESTROY = 0x0082

    def __init__(self, window, events, busy, extra_windows=(), hover_window=None):
        if sys.platform != "win32":
            raise OSError("Native file drops require Windows.")
        self.events, self.busy = events, busy
        self.window, self.extra_windows = window, extra_windows
        self._handles = set()
        self._ole_handles = set()
        self._ole_initialized = False
        self._hover = False
        self._paths = []
        self.hover_window = hover_window
        self._hover_bounds = None
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
            self._initialize_ole()
            self.refresh()
        except Exception:
            self.close()
            raise
        # A Windows callback must not be garbage-collected while its HWND lives.
        window._ld_file_drop = self
        window.bind("<Configure>", self._layout_changed, add="+")
        window.bind("<Unmap>", self._unmapped, add="+")
        window.bind("<Destroy>", self._destroyed, add="+")

    def update_hover_bounds(self):
        """Cache Tk geometry on the UI thread; COM callbacks never call Tk."""
        widget = self.hover_window
        if widget is not None and widget.winfo_ismapped():
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            self._hover_bounds = (x, y, x + widget.winfo_width(), y + widget.winfo_height())
        else:
            self._hover_bounds = None

    def _layout_changed(self, event):
        if event.widget in (self.window, self.hover_window):
            self.update_hover_bounds()

    def _unmapped(self, event):
        if event.widget is self.window:
            self._hover_bounds = None
            self._set_hover(False)

    def _destroyed(self, event):
        if event.widget is self.window:
            self.close()

    def _set_hover(self, active):
        active = bool(active)
        if active != self._hover:
            self._hover = active
            self.events.put(("drag_hover", active))

    def _initialize_ole(self):
        """Expose a minimal IDropTarget for real Explorer enter/over/leave events."""
        self._ole = ctypes.WinDLL("ole32", use_last_error=True)
        self._ole.OleInitialize.argtypes = [ctypes.c_void_p]
        self._ole.OleInitialize.restype = wintypes.LONG
        self._ole.OleUninitialize.argtypes = []
        self._ole.OleUninitialize.restype = None
        self._ole.RegisterDragDrop.argtypes = [wintypes.HWND, ctypes.c_void_p]
        self._ole.RegisterDragDrop.restype = wintypes.LONG
        self._ole.RevokeDragDrop.argtypes = [wintypes.HWND]
        self._ole.RevokeDragDrop.restype = wintypes.LONG
        self._ole.ReleaseStgMedium.argtypes = [ctypes.POINTER(_StorageMedium)]
        self._ole.ReleaseStgMedium.restype = None
        result = self._ole.OleInitialize(None)
        if result < 0:
            raise OSError("Cannot initialize Windows OLE file drops: " + hex(result & 0xFFFFFFFF))
        self._ole_initialized = True
        self._references = 1
        ptr, dword = ctypes.c_void_p, wintypes.DWORD
        effect = ctypes.POINTER(dword)
        callback = ctypes.WINFUNCTYPE
        self._ole_callbacks = (
            callback(wintypes.LONG, ptr, ptr, ctypes.POINTER(ptr))(self._query_interface),
            callback(wintypes.ULONG, ptr)(self._add_reference),
            callback(wintypes.ULONG, ptr)(self._release_reference),
            callback(wintypes.LONG, ptr, ptr, dword, wintypes.POINT, effect)(self._drag_enter),
            callback(wintypes.LONG, ptr, dword, wintypes.POINT, effect)(self._drag_over),
            callback(wintypes.LONG, ptr)(self._drag_leave),
            callback(wintypes.LONG, ptr, ptr, dword, wintypes.POINT, effect)(self._drop),
        )
        self._ole_vtable = (ptr * 7)(*(ctypes.cast(item, ptr).value for item in self._ole_callbacks))
        self._ole_interface = (ptr * 1)(ctypes.addressof(self._ole_vtable))
        self._ole_pointer = ctypes.addressof(self._ole_interface)

    def _query_interface(self, this, iid, output):
        # IUnknown / IDropTarget, in GUID's Windows little-endian layout.
        if not output:
            return -2147467261  # E_POINTER
        output[0] = None
        if iid and ctypes.string_at(iid, 16) in (
                bytes.fromhex("0000000000000000c000000000000046"),
                bytes.fromhex("2201000000000000c000000000000046")):
            output[0] = this
            self._add_reference(this)
            return 0
        return -2147467262  # E_NOINTERFACE

    def _add_reference(self, this):
        self._references += 1
        return self._references

    def _release_reference(self, this):
        self._references = max(0, self._references - 1)
        return self._references

    def _read_paths(self, handle):
        count = self._shell.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        if count != 1:
            return count, []
        length = self._shell.DragQueryFileW(handle, 0, None, 0)
        if not 0 < length <= 32767:
            raise ValueError("The dropped file path cannot be read.")
        buffer = ctypes.create_unicode_buffer(length + 1)
        if self._shell.DragQueryFileW(handle, 0, buffer, length + 1) != length:
            raise ValueError("The dropped file path is incomplete.")
        return count, [buffer.value]

    def _read_ole_paths(self, data):
        if not data:
            return []
        vtable = ctypes.cast(data, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_data = ctypes.WINFUNCTYPE(wintypes.LONG, ctypes.c_void_p,
                                     ctypes.POINTER(_FormatEtc), ctypes.POINTER(_StorageMedium))(vtable[3])
        request = _FormatEtc(15, None, 1, -1, 1)  # CF_HDROP, DVASPECT_CONTENT, TYMED_HGLOBAL
        medium = _StorageMedium()
        if get_data(data, ctypes.byref(request), ctypes.byref(medium)) < 0:
            return []
        try:
            if medium.medium != 1 or not medium.data:
                return []
            _, paths = self._read_paths(medium.data)
            return paths if paths and paths[0].lower().endswith(".wbex") else []
        finally:
            self._ole.ReleaseStgMedium(ctypes.byref(medium))

    def _drag_over(self, this, keys, point, effect):
        accepted = bool(self._paths) and not self.busy() and bool(effect[0] & 1)
        bounds = self._hover_bounds
        inside = bounds and bounds[0] <= point.x < bounds[2] and bounds[1] <= point.y < bounds[3]
        self._set_hover(accepted and inside)
        effect[0] = 1 if accepted else 0  # DROPEFFECT_COPY / NONE
        return 0

    def _drag_enter(self, this, data, keys, point, effect):
        try:
            self._paths = [] if self.busy() else self._read_ole_paths(data)
            return self._drag_over(this, keys, point, effect)
        except Exception:
            self._paths = []
            self._set_hover(False)
            effect[0] = 0
            return 0  # Unsupported data is rejected without disturbing the drag source.

    def _drag_leave(self, this):
        self._paths = []
        self._set_hover(False)
        return 0

    def _drop(self, this, data, keys, point, effect):
        try:
            # Read the final payload again rather than trusting the initial preview.
            paths = [] if self.busy() else self._read_ole_paths(data)
            accepted = bool(paths) and bool(effect[0] & 1)
            effect[0] = 1 if accepted else 0
            self._set_hover(False)
            if accepted:
                self.events.put(("drop", {"count": 1, "paths": paths, "busy": False}))
        except Exception as error:
            effect[0] = 0
            self.events.put(("drop_error", str(error)))
        finally:
            self._drag_leave(this)
        return 0

    def refresh(self):
        """Tk may replace its native wrapper when first mapping the window."""
        self.update_hover_bounds()
        client = self.window.winfo_id()
        handles = {client, self._user.GetParent(client)}
        handles.update(item.winfo_id() for item in self.extra_windows)
        desired = handles - {None, 0}
        for handle in self._handles - desired:
            if handle in self._ole_handles:
                self._ole.RevokeDragDrop(handle)
                self._ole_handles.discard(handle)
            self._shell.DragAcceptFiles(handle, False)
            self._controls.RemoveWindowSubclass(handle, self._callback, self._id)
            self._handles.discard(handle)
        for handle in desired - self._handles:
            if not self._controls.SetWindowSubclass(handle, self._callback, self._id, 0):
                raise OSError("Cannot register the native file drop handler.")
            self._handles.add(handle)
        for handle in desired:
            self._shell.DragAcceptFiles(handle, True)
            if handle not in self._ole_handles:
                result = self._ole.RegisterDragDrop(handle, self._ole_pointer)
                if result < 0:
                    raise OSError("Cannot register Windows OLE file drops: " + hex(result & 0xFFFFFFFF))
                self._ole_handles.add(handle)

    def _message(self, hwnd, message, wparam, lparam, subclass_id, reference):
        if message == self.WM_DROPFILES:
            try:
                self._set_hover(False)
                count = self._shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                payload = {"count": count, "paths": [], "busy": bool(self.busy())}
                if count == 1 and not payload["busy"]:
                    _, payload["paths"] = self._read_paths(wparam)
                # Do not call Tk or touch the disk from a Windows message hook.
                self.events.put(("drop", payload))
            except Exception as error:
                self.events.put(("drop_error", str(error)))
            finally:
                self._shell.DragFinish(wparam)
            return 0
        if message == self.WM_NCDESTROY:
            if hwnd in self._ole_handles:
                self._ole.RevokeDragDrop(hwnd)
                self._ole_handles.discard(hwnd)
            self._controls.RemoveWindowSubclass(hwnd, self._callback, self._id)
            self._handles.discard(hwnd)
        return self._controls.DefSubclassProc(hwnd, message, wparam, lparam)

    def close(self):
        """Unregister on the Tk UI thread, retaining the callback during removal."""
        self._drag_leave(None)
        for handle in tuple(self._ole_handles):
            self._ole.RevokeDragDrop(handle)
            self._ole_handles.discard(handle)
        for handle in tuple(self._handles):
            self._shell.DragAcceptFiles(handle, False)
            self._controls.RemoveWindowSubclass(handle, self._callback, self._id)
            self._handles.discard(handle)
        if self._ole_initialized:
            self._ole.OleUninitialize()
            self._ole_initialized = False
