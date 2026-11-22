import subprocess
import unittest
from unittest.mock import patch

from shelter_core import process_runtime


class BackgroundService(unittest.TestCase):
    @unittest.skipUnless(process_runtime.os.name == "nt", "Windows process flags")
    def test_hidden_console_is_inherited_by_service_children(self):
        options = process_runtime.service_options(breakaway=True)
        info = options["startupinfo"]
        self.assertTrue(info.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(info.wShowWindow, subprocess.SW_HIDE)
        flags = options["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NEW_CONSOLE)
        self.assertTrue(flags & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        self.assertFalse(flags & (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS))
        self.assertEqual(options["stdin"], subprocess.DEVNULL)

    def test_unix_has_no_windows_flags(self):
        with patch.object(process_runtime.os, "name", "posix"):
            self.assertEqual(process_runtime.service_options(), {})
