#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! command -v apt-get >/dev/null; then
  echo 'Этот мастер рассчитан на Ubuntu 24.04 / Debian с Python 3.11+. См. docs/PLATFORMS.md.' >&2
  exit 1
fi
echo 'Устанавливаются системные инструменты звука, X11/Wayland, OCR и сборки окна.'
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev python3-gi libportaudio2 libsndfile1 \
  playerctl pulseaudio-utils wmctrl xdotool xclip x11-xserver-utils wl-clipboard \
  xdg-desktop-portal tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
  libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev build-essential
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install --upgrade pip
.venv-linux/bin/python -m pip install -r requirements.txt
echo 'Готово. Ядро: .venv-linux/bin/python main.py. Сборка окна описана в docs/PLATFORMS.md.'
