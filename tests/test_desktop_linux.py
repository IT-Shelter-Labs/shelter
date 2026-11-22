import os
import subprocess
import unittest
from unittest.mock import patch

from shelter_core import desktop_linux as desktop


class LinuxDesktopTests(unittest.TestCase):
    def test_wayland_does_not_advertise_xwayland_as_full_support(self):
        with patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}, clear=True), patch("shutil.which", return_value="/usr/bin/tool"):
            caps = desktop.capabilities()
            self.assertFalse(caps["windows"])
            self.assertFalse(caps["keys"])
            self.assertTrue(caps["clipboard"])
            with self.assertRaisesRegex(RuntimeError, "Wayland"):
                desktop.send_keys("ctrl+c")

    def test_monitors_keep_negative_coordinates_and_primary_order(self):
        listing = "Monitors: 2\n 0: +DP-1 1920/500x1080/300-1920+0 DP-1\n 1: +*HDMI-1 2560/600x1440/350+0-200 HDMI-1\n"
        with patch.object(desktop, "_require"), patch.object(desktop, "_run", return_value=listing):
            screens = desktop.monitors()
        self.assertEqual(screens[0]["work"], (0, -200, 2560, 1440))
        self.assertEqual(screens[1]["work"], (-1920, 0, 1920, 1080))

    def test_utf8_uses_stdin_without_interpreting_shell(self):
        text = "Привет $HOME `touch /tmp/nope`\nвторая строка"
        with patch.object(desktop, "_require"), patch.object(desktop, "_run") as run:
            self.assertTrue(desktop.type_text(text))
        self.assertEqual(run.call_args.kwargs["data"], text.encode("utf-8"))
        self.assertNotIn(text, run.call_args.args)

    def test_window_no_longer_exists_does_not_receive_text(self):
        with patch.object(desktop, "_require"), patch.object(desktop, "windows", return_value=[]), patch.object(desktop, "type_text") as write:
            with self.assertRaisesRegex(RuntimeError, "закрыто"):
                desktop.apply_text({"hwnd": 123, "process": "editor"}, "result")
            write.assert_not_called()

    def test_focus_rejected_does_not_receive_text(self):
        with patch.object(desktop, "_require"), patch.object(desktop, "windows", return_value=[(123, "Title", "editor")]), \
             patch.object(desktop, "focus"), patch.object(desktop, "foreground", return_value={"hwnd": 456}), patch.object(desktop, "type_text") as write:
            with self.assertRaisesRegex(RuntimeError, "фокус"):
                desktop.apply_text({"hwnd": 123, "process": "editor"}, "result")
            write.assert_not_called()

    def test_clipboard_restored_even_when_copy_has_no_result(self):
        marker = ""
        def read():
            return marker
        def write(text):
            nonlocal marker
            marker = text
        with patch.object(desktop, "_require"), patch.object(desktop, "foreground", return_value={"hwnd": 123}), \
             patch.object(desktop, "clipboard_text", side_effect=read), patch.object(desktop, "set_clipboard", side_effect=write), \
             patch.object(desktop, "send_keys"), patch.object(desktop.time, "monotonic", side_effect=[0, 1]):
            with self.assertRaisesRegex(RuntimeError, "выделение"):
                desktop.capture_selection()
        self.assertEqual(marker, "")

    def test_runtime_capabilities_are_shared_by_plan_and_editor(self):
        from shelter_core import scenarios
        with patch.object(scenarios, "PLATFORM", "linux"), patch.object(desktop, "capabilities", return_value={"keys": True}):
            self.assertTrue(scenarios.supported("keys", scenarios.ACTIONS["keys"]))
            registry = scenarios.registry_for_platform(scenarios.ACTIONS)
            self.assertIn("linux", registry["keys"]["platforms"])
            self.assertNotIn("linux", registry["window"]["platforms"])
        self.assertEqual(scenarios.ACTIONS["keys"]["platforms"], ["windows"])
