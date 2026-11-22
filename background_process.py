"""Windows-only child console defaults for the dedicated background TTS server."""
import functools
import os
import subprocess


def hide_child_consoles():
    """Cover third-party checks such as sox's os.popen without changing packages.

    Keep Popen a class, and honour explicit requests for a new/detached console.
    Only install in the dedicated server, never in the action executor.
    """
    original = subprocess.Popen.__init__
    if os.name != "nt" or getattr(original, "_jarvis_hidden", False):
        return

    @functools.wraps(original)
    def hidden(self, *args, **kwargs):
        if len(args) <= 13:
            flags = kwargs.get("creationflags", 0)
            if not flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
                kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    hidden._jarvis_hidden = True
    subprocess.Popen.__init__ = hidden
