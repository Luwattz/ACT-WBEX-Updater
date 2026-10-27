"""Verify process closure with simulated Windows handles, never live Ansys."""
import ctypes
import os
import unittest
from unittest.mock import Mock, patch

from tools import update_wbex as engine


class ProcessClosureTests(unittest.TestCase):
    def test_only_approved_host_names_are_closed_and_new_hosts_need_consent(self):
        with patch.object(engine, "_ansys_process_entries", return_value=[
                (10, "AnsysWBU.exe"), (11, "SpaceClaim.exe"), (12, "unrelated.exe")]), \
                patch.object(engine, "_terminate_ansys_process") as terminate, \
                patch.object(engine, "active_ansys_processes", return_value=["SpaceClaim.exe"]):
            with self.assertRaises(engine.AnsysProcessesRunning) as raised:
                engine.close_ansys_processes(["AnsysWBU.exe"])
        terminate.assert_called_once_with(10, "AnsysWBU.exe")
        self.assertEqual(("SpaceClaim.exe",), raised.exception.names)

    def test_unapproved_names_never_reach_process_api(self):
        for names in ([], ["unrelated.exe"], ["AnsysWBU.exe", "unrelated.exe"]):
            with self.subTest(names=names), patch.object(engine, "_ansys_process_entries") as scan:
                with self.assertRaises(engine.UpdateError):
                    engine.close_ansys_processes(names)
                scan.assert_not_called()

    def test_already_closed_processes_are_not_an_error(self):
        with patch.object(engine, "_ansys_process_entries", return_value=[]), \
                patch.object(engine, "active_ansys_processes", return_value=[]), \
                patch.object(engine, "_terminate_ansys_process") as terminate:
            engine.close_ansys_processes(["AnsysWBU.exe"])
        terminate.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows process handles")
class NativeProcessClosureTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.kernel.OpenProcess.return_value = 123
        self.kernel.WaitForSingleObject.side_effect = [258, 0]
        self.kernel.TerminateProcess.return_value = True

        def query(handle, flags, image, length):
            image.value = r"C:\Ansys\AnsysWBU.exe"
            return True

        self.kernel.QueryFullProcessImageNameW.side_effect = query
        win_dll = patch.object(engine.ctypes, "WinDLL", return_value=self.kernel)
        win_dll.start()
        self.addCleanup(win_dll.stop)

    def test_verified_process_is_terminated_waited_for_and_handle_closed(self):
        engine._terminate_ansys_process(42, "AnsysWBU.exe")
        self.kernel.OpenProcess.assert_called_once_with(0x00101001, False, 42)
        self.kernel.TerminateProcess.assert_called_once_with(123, 1)
        self.assertEqual((123, 5000), self.kernel.WaitForSingleObject.call_args.args)
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_reused_pid_for_different_executable_is_not_terminated(self):
        def query(handle, flags, image, length):
            image.value = r"C:\Other\unrelated.exe"
            return True

        self.kernel.QueryFullProcessImageNameW.side_effect = query
        with self.assertRaisesRegex(engine.UpdateError, "identity changed"):
            engine._terminate_ansys_process(42, "AnsysWBU.exe")
        self.kernel.TerminateProcess.assert_not_called()
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_access_denied_is_reported_without_termination(self):
        self.kernel.OpenProcess.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=5):
            with self.assertRaisesRegex(engine.UpdateError, "Cannot close"):
                engine._terminate_ansys_process(42, "AnsysWBU.exe")
        self.kernel.TerminateProcess.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_timeout_does_not_allow_update_to_continue(self):
        self.kernel.WaitForSingleObject.side_effect = [258, 258]
        with self.assertRaisesRegex(engine.UpdateError, "timed out"):
            engine._terminate_ansys_process(42, "AnsysWBU.exe")
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_process_exiting_before_open_is_accepted(self):
        self.kernel.OpenProcess.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=87):
            engine._terminate_ansys_process(42, "AnsysWBU.exe")
        self.kernel.TerminateProcess.assert_not_called()
