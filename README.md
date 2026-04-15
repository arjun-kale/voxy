# Voice Input

`voice-input` is a local speech-to-text input daemon for Linux desktops. It is built for the "Windows speech typing" workflow:

- keep everything local
- keep latency low
- toggle listening with a desktop shortcut
- type recognized text into the currently focused app

This first version is optimized for Linux and especially Wayland, where global hotkeys are compositor-specific. Instead of trying to own the keyboard globally, the project runs as a daemon and exposes a small `toggle` command that you bind to a shortcut such as `Super+Space`.

## What It Does

- uses a local `vosk` model for fast streaming speech recognition
- captures microphone audio in real time
- finalizes text phrase by phrase and sends it to the active app
- works as a background daemon with `toggle`, `start`, `stop`, and `status` commands
- uses `sounddevice` when PortAudio is available and falls back to `arecord` when it is not
- prefers `wtype` on Wayland and `xdotool` on X11
- falls back to clipboard mode if direct text injection is unavailable

## Current Tradeoffs

- `vosk` is chosen for speed and streaming latency, not maximum accuracy
- punctuation is basic unless you speak explicit commands like `comma` or `new line`
- on Wayland, direct typing usually requires `wtype`
- true global hotkeys are intentionally delegated to your desktop environment because that is the reliable Linux path

## Install

### 1. System packages

Ubuntu example:

```bash
sudo apt update
sudo apt install -y python3-venv portaudio19-dev wl-clipboard wtype
```

If you are on X11 instead of Wayland, install `xdotool` instead of `wtype`.
If PortAudio is unavailable, the daemon can still capture audio via `arecord` if `alsa-utils` is already installed.
If you cannot or do not want to use `sudo`, you can extract the `wtype` package into `~/.local/bin` and ensure the user service includes that directory in `PATH`.

### 2. Virtual environment

```bash
cd ~/dev/Personal/voice
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

### 3. Download a local Vosk model

Recommended fast English model:

- `vosk-model-small-en-us-0.15`

Place it at:

```text
~/.local/share/vosk/vosk-model-small-en-us-0.15
```

You can use a larger or different-language model later by changing the config.

### 4. Create config

```bash
mkdir -p ~/.config/voice-input
cp ~/dev/Personal/voice/config.example.toml ~/.config/voice-input/config.toml
```

Update `model_path` if needed.

## Run

Start the daemon:

```bash
cd ~/dev/Personal/voice
. .venv/bin/activate
voice-input daemon
```

In another terminal, or from a desktop shortcut:

```bash
voice-input toggle
```

Available commands:

```bash
voice-input daemon
voice-input toggle
voice-input start
voice-input stop
voice-input status
```

## Desktop Shortcut

Bind your desktop shortcut to:

```bash
/home/arjun/dev/Personal/voice/.venv/bin/voice-input toggle
```

Suggested shortcut:

- `Super+Space`

That gives you the same basic workflow as Windows speech typing:

1. Press `Super+Space`
2. Speak
3. Press `Super+Space` again to stop

## Clipboard Fallback

If direct typing is not available, the daemon falls back to clipboard mode:

- transcript is copied to the clipboard
- a desktop notification tells you what happened
- you can paste with `Ctrl+V`

For a real input-system feel on Wayland, install `wtype`.

## Systemd User Service

Example unit is included in [systemd/voice-input.service](/home/arjun/dev/Personal/voice/systemd/voice-input.service).

Install it like this:

```bash
mkdir -p ~/.config/systemd/user
cp ~/dev/Personal/voice/systemd/voice-input.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-input.service
```

## Config

Example config file:

```toml
[speech]
model_path = "/home/arjun/.local/share/vosk/vosk-model-small-en-us-0.15"
sample_rate = 16000
blocksize = 4000

[input]
backend = "auto"
append_space = true

[service]
socket_path = "/run/user/1000/voice-input.sock"
notifications = true
```

## Notes

- `backend = "auto"` tries `wtype`, then `xdotool`, then clipboard
- audio capture prefers PortAudio and falls back to `arecord`
- `comma`, `period`, `question mark`, `exclamation mark`, and `new line` are converted into punctuation
- if you want better recognition later, keep the same daemon design and swap the recognizer backend
