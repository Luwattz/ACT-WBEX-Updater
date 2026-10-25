"""Exercise real Windows HDROP messages and callback cleanup in an isolated UI."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows Shell file drops")
class WindowsFileDropTests(unittest.TestCase):
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
