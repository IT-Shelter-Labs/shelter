"""Locations shared by development checkouts and packaged installations."""

from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent
ROOT_DIR = str(ROOT_PATH)
