#!/usr/bin/env bash
# Installs Voxy for the current user.
# Usage: ./scripts/install.sh [--no-system]   (--no-system skips distro packages)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$DATA_HOME/voxy/venv"
BIN_DIR="$HOME/.local/bin"
SYSTEM=1
[[ "${1:-}" == "--no-system" ]] && SYSTEM=0

step() { printf '\n==> %s\n' "$*"; }

if [[ $SYSTEM == 1 ]]; then
  step "Installing system packages"
  if command -v apt-get >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv libportaudio2 libxcb-cursor0 \
      wl-clipboard xclip xdotool wtype pulseaudio-utils
  elif command -v dnf >/dev/null; then
    sudo dnf install -y -q python3 portaudio xcb-util-cursor wl-clipboard xclip xdotool wtype
  elif command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm python portaudio xcb-util-cursor wl-clipboard xclip xdotool wtype
  else
    echo "Unknown package manager; install PortAudio, wl-clipboard/xclip and xdotool/wtype manually."
  fi
fi

step "Installing Voxy"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q "$PROJECT_DIR"
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/voxy" "$BIN_DIR/voxy"
ln -sf "$VENV/bin/voice-input" "$BIN_DIR/voice-input"

step "Adding desktop entry"
"$VENV/bin/voxy" install-desktop >/dev/null

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: $BIN_DIR is not on your PATH." ;;
esac

step "Starting Voxy"
nohup "$VENV/bin/voxy" app >/dev/null 2>&1 &
