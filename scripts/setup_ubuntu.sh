#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo apt update
sudo apt install -y python3-venv portaudio19-dev wl-clipboard wtype

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install -U pip
"$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR"

mkdir -p "$HOME/.config/voice-input"
if [[ ! -f "$HOME/.config/voice-input/config.toml" ]]; then
  cp "$PROJECT_DIR/config.example.toml" "$HOME/.config/voice-input/config.toml"
fi

cat <<EOF
Setup complete.

Next steps:
1. Download a Vosk model into ~/.local/share/vosk/
2. Update ~/.config/voice-input/config.toml
3. Start the daemon with:
   $PROJECT_DIR/.venv/bin/voice-input daemon
EOF
