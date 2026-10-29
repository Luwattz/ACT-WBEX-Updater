"""Exercise real Windows HDROP messages and callback cleanup in an isolated UI."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows Shell file drops")
class WindowsFileDropTests(unittest.TestCase):
    def test_ole_hover_validates_payload_bounds_busy_state_and_cleans_up(self):
        script = r'''
import ctypes, json, queue, struct, tkinter as tk
from ctypes import wintypes
from tools.wbex_updater_drop import WindowsFileDrop, _FormatEtc, _StorageMedium

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel.GlobalAlloc.restype = wintypes.HGLOBAL
kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel.GlobalLock.restype = ctypes.c_void_p
kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel.GlobalFlags.argtypes = [wintypes.HGLOBAL]
kernel.GlobalFlags.restype = wintypes.UINT
window = tk.Tk()
window.geometry('400x250+80+80')
zone = tk.Frame(window, width=300, height=150)
zone.pack()
window.update()
events, busy = queue.Queue(), [False]
target = WindowsFileDrop(window, events, lambda: busy[0], extra_windows=(zone,), hover_window=zone)
assert target._ole_handles == target._handles
references = target._references
output = ctypes.c_void_p()
iid = ctypes.create_string_buffer(bytes.fromhex('2201000000000000c000000000000046'))
assert target._ole_callbacks[0](target._ole_pointer, iid, ctypes.byref(output)) == 0
assert output.value == target._ole_pointer and target._references == references + 1
target._ole_callbacks[2](target._ole_pointer)
assert target._references == references
allocated = []
retained = []

def data_object(names, result=0):
    def get_data(this, request, medium):
        if result:
            return result
        assert request.contents.format == 15 and request.contents.medium == 1
        payload = struct.pack('<IiiII', 20, 0, 0, 0, 1) + ('\0'.join(names) + '\0\0').encode('utf-16-le')
        handle = kernel.GlobalAlloc(0x42, len(payload))
        pointer = kernel.GlobalLock(handle)
        ctypes.memmove(pointer, payload, len(payload))
        kernel.GlobalUnlock(handle)
        allocated.append(handle)
        medium.contents.medium = 1
        medium.contents.data = handle
        medium.contents.owner = None
        return 0
    callback = ctypes.WINFUNCTYPE(wintypes.LONG, ctypes.c_void_p,
        ctypes.POINTER(_FormatEtc), ctypes.POINTER(_StorageMedium))(get_data)
    table = (ctypes.c_void_p * 4)(None, None, None, ctypes.cast(callback, ctypes.c_void_p).value)
    obj = (ctypes.c_void_p * 1)(ctypes.addressof(table))
    retained.append((callback, table, obj))
    return ctypes.addressof(obj)

def queued():
    output = []
    while not events.empty():
        output.append(events.get_nowait())
    return output

left, top, right, bottom = target._hover_bounds
inside = wintypes.POINT(left + 20, top + 20)
outside = wintypes.POINT(right + 20, bottom + 20)
effect = wintypes.DWORD(1)
valid = data_object([r'C:\发布 文件\新插件 {测试}.WBEX'])
enter, over, leave, drop = target._ole_callbacks[3:]
assert enter(target._ole_pointer, valid, 0, inside, ctypes.byref(effect)) == 0
assert effect.value == 1 and queued() == [('drag_hover', True)]
over(target._ole_pointer, 0, inside, ctypes.byref(effect))
assert queued() == [], 'Repeated DragOver must not flood the event queue'
over(target._ole_pointer, 0, outside, ctypes.byref(effect))
assert queued() == [('drag_hover', False)]
over(target._ole_pointer, 0, inside, ctypes.byref(effect))
assert queued() == [('drag_hover', True)]
leave(target._ole_pointer)
assert queued() == [('drag_hover', False)]

for invalid in (data_object([r'C:\wrong.xml']), data_object([r'C:\a.wbex', r'C:\b.wbex']),
                data_object([], -2147221404)):
    effect.value = 1
    enter(target._ole_pointer, invalid, 0, inside, ctypes.byref(effect))
    assert effect.value == 0 and queued() == []
busy[0] = True
effect.value = 1
enter(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
assert effect.value == 0 and queued() == []
busy[0] = False
effect.value = 1
enter(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
queued()
busy[0] = True
drop(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
assert effect.value == 0 and queued() == [('drag_hover', False)]
busy[0] = False
effect.value = 1
enter(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
queued()
drop(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
assert queued() == [('drag_hover', False), ('drop', {
    'count': 1, 'paths': [r'C:\发布 文件\新插件 {测试}.WBEX'], 'busy': False})]
assert all(kernel.GlobalFlags(handle) == 0x8000 for handle in allocated), 'OLE medium leaked'
effect.value = 1
enter(target._ole_pointer, valid, 0, inside, ctypes.byref(effect))
queued()
window.destroy()
assert not target._handles and not target._ole_handles and not target._ole_initialized
assert queued() == [('drag_hover', False)]
target.close()
print(json.dumps({'ok': True, 'hover': True, 'ole_cleanup': True}))
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                text=True, cwd=Path(__file__).resolve().parents[1], timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_unicode_shell_messages_busy_rejection_and_native_teardown(self):
        script = r'''
import ctypes, json, queue, struct, tkinter as tk
from ctypes import wintypes
from tools.wbex_updater_drop import WindowsFileDrop

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
user = ctypes.WinDLL('user32', use_last_error=True)
kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel.GlobalAlloc.restype = wintypes.HGLOBAL
kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel.GlobalLock.restype = ctypes.c_void_p
kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel.GlobalUnlock.restype = wintypes.BOOL
kernel.GlobalFlags.argtypes = [wintypes.HGLOBAL]
kernel.GlobalFlags.restype = wintypes.UINT
user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.SendMessageW.restype = ctypes.c_ssize_t
user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user.GetWindowLongW.restype = wintypes.LONG

window = tk.Tk()
window.withdraw()
entry = tk.Entry(window)
entry.pack()
events = queue.Queue()
busy = [False]
target = WindowsFileDrop(window, events, lambda: busy[0], extra_windows=(entry,))
assert len(target._handles) >= 2
paths = [r'C:\发布 文件\新插件 {测试}.wbex', r'C:\发布 文件\另一个.wbex']

def send(hwnd, names):
    data = struct.pack('<IiiII', 20, 0, 0, 0, 1) + ('\0'.join(names) + '\0\0').encode('utf-16-le')
    handle = kernel.GlobalAlloc(0x42, len(data))
    assert handle
    pointer = kernel.GlobalLock(handle)
    assert pointer
    ctypes.memmove(pointer, data, len(data))
    kernel.GlobalUnlock(handle)
    assert user.SendMessageW(hwnd, 0x233, handle, 0) == 0
    assert kernel.GlobalFlags(handle) == 0x8000, 'DragFinish did not free HDROP'
    return events.get_nowait()

for hwnd in target._handles:
    assert user.GetWindowLongW(hwnd, -20) & 0x10, 'WS_EX_ACCEPTFILES is missing'
    event, payload = send(hwnd, paths[:1])
    assert event == 'drop' and payload == {'count': 1, 'paths': paths[:1], 'busy': False}, payload
window.deiconify()
window.update()
target.refresh()
wrapper = target._user.GetParent(window.winfo_id())
assert wrapper in target._handles and user.GetWindowLongW(wrapper, -20) & 0x10
event, payload = send(wrapper, paths[:1])
assert payload['paths'] == paths[:1]
event, payload = send(entry.winfo_id(), paths)
assert payload['count'] == 2 and payload['paths'] == []
busy[0] = True
event, payload = send(entry.winfo_id(), paths[:1])
busy[0] = False
assert payload['busy'] is True and payload['paths'] == []
window.destroy()
assert not target._handles, 'Native window hooks survived destruction'
target.close()
print(json.dumps({'ok': True, 'unicode': True, 'freed_handles': True}))
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                text=True, cwd=Path(__file__).resolve().parents[1], timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
