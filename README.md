# Voice Input System for Linux PCs

`Voxy` is a local voice-to-text daemon for Linux desktops. It listens on demand, transcribes speech with Vosk, and types the result into the currently focused application.

The project is designed around a simple workflow: run the daemon in the background, bind `voice-input toggle` to a shortcut, speak, and toggle again to stop.

## Features

- local, offline speech recognition with `vosk`
- low-latency streaming transcription
- background daemon with `daemon`, `toggle`, `start`, `stop`, and `status` commands
- text injection with `wtype` on Wayland and `xdotool` on X11
- clipboard fallback when direct typing is unavailable
- audio capture through `sounddevice`, with `arecord` fallback

## Installation

Install system dependencies on Ubuntu:

```bash
sudo apt update
sudo apt install -y python3-venv portaudio19-dev wl-clipboard wtype
```

If you use X11, install `xdotool` instead of `wtype`.

Create a virtual environment and install the project:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

Download a Vosk model, for example `vosk-model-small-en-us-0.15`, and place it in a local directory such as:

```text
~/.local/share/vosk/vosk-model-small-en-us-0.15
```

Then create a config file:

```bash
mkdir -p ~/.config/voice-input
cp config.example.toml ~/.config/voice-input/config.toml
```

Update `model_path` in the config if needed.

## Usage

Start the daemon:

```bash
. .venv/bin/activate
voice-input daemon
```

Toggle listening:

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

## Shortcut Setup

Bind your desktop shortcut to:

```bash
voice-input toggle
```

This works well for a push-to-dictate workflow on Linux desktops.

## Systemd User Service

An example unit is included in `systemd/voice-input.service`.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/voice-input.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-input.service
```

## Notes

- recognition speed is prioritized over maximum accuracy
- punctuation support is basic unless spoken explicitly
- Wayland support is best when `wtype` is installed
- the project keeps hotkey management in the desktop environment instead of implementing global shortcuts itself
