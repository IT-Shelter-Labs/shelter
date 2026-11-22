"""Invisible console for a background service and its console descendants.

CREATE_NO_WINDOW | DETACHED_PROCESS is invalid for this purpose: Windows
ignores CREATE_NO_WINDOW, and a runner may allocate a visible console later.
An attached, initially hidden console lets ordinary child processes inherit it.
"""
import os
import subprocess


def service_options(breakaway=False):
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    flags = subprocess.CREATE_NEW_CONSOLE
    if breakaway:
        flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
    return {"startupinfo": startup, "creationflags": flags, "stdin": subprocess.DEVNULL}
