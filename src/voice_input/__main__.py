from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import load_config, save_config
from .ipc import send_command


CLIENT_COMMANDS = {
    "toggle": "Start or stop dictation",
    "start": "Start dictation",
    "stop": "Stop dictation",
    "status": "Show daemon status",
    "show": "Open the Voxy window",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxy",
        description="Voxy: private, offline voice typing for Linux. Run without a command to open the app.",
    )
    parser.add_argument("--config", help="Path to config.toml (defaults to ~/.config/voice-input/config.toml)")

    sub = parser.add_subparsers(dest="command")
    app = sub.add_parser("app", help="Open the desktop app (tray, floating bar, settings)")
    app.add_argument("--background", action="store_true", help="Start hidden in the tray")
    sub.add_parser("daemon", help="Run headless in the background (no windows)")
    for name, help_text in CLIENT_COMMANDS.items():
        sub.add_parser(name, help=help_text)
    sub.add_parser("doctor", help="Check that everything Voxy needs is in place")
    sub.add_parser("install-desktop", help="Add Voxy to the app menu")

    models = sub.add_parser("models", help="List or download speech models")
    models_sub = models.add_subparsers(dest="models_command")
    models_sub.add_parser("list", help="Show available languages")
    download = models_sub.add_parser("download", help="Download a model and start using it")
    download.add_argument("model", nargs="?", help="Model id from `models list` (default: English US)")
    return parser


async def _run_client(command: str, config_path: str | None) -> int:
    config = load_config(config_path)
    try:
        response = await send_command(config.service.socket_path, command)
    except FileNotFoundError:
        print("Voxy isn't running. Start it with `voxy` (app) or `voxy daemon`.", file=sys.stderr)
        return 1
    except ConnectionRefusedError:
        print("Unable to connect to Voxy. Try restarting it.", file=sys.stderr)
        return 1
    except PermissionError:
        print("Unable to access the Voxy socket. Is it running in your user session?", file=sys.stderr)
        return 1
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"IPC error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def _doctor(config_path: str | None) -> int:
    from .doctor import FAIL, OK, WARN, run_checks

    marks = {OK: "\033[32m✓\033[0m", WARN: "\033[33m!\033[0m", FAIL: "\033[31m✗\033[0m"}
    checks = run_checks(load_config(config_path))
    for check in checks:
        print(f" {marks[check.status]} {check.title}: {check.detail}")
        if check.fix:
            print(f"     → {check.fix}")
    return 1 if any(c.status == FAIL for c in checks) else 0


def _models(args: argparse.Namespace) -> int:
    from .models import CATALOG, download_model, find_model

    if args.models_command in (None, "list"):
        config = load_config(args.config)
        for info in CATALOG:
            mark = "●" if config.speech.model_path == str(info.path) else "✓" if info.installed else " "
            print(f" {mark} {info.id:36} {info.language:18} {info.size_mb:>4} MB  {info.quality}")
        print("\n ● in use   ✓ installed")
        return 0

    model_id = args.model or CATALOG[0].id
    info = find_model(model_id)
    if info is None:
        print(f"Unknown model {model_id!r}. See `voxy models list`.", file=sys.stderr)
        return 1

    def progress(done: int, total: int) -> None:
        width = 32
        filled = int(width * done / max(total, 1))
        sys.stdout.write(f"\r {info.language} [{'█' * filled}{'·' * (width - filled)}] {done / 1e6:5.1f}/{total / 1e6:.0f} MB")
        sys.stdout.flush()

    try:
        path = download_model(info, progress=progress)
    except Exception as exc:
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        return 1
    config = load_config(args.config)
    config.speech.model_path = str(path)
    save_config(config)
    print(f"\n ✓ Installed to {path} and set as the active model.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "app"

    if command == "app":
        from .ui.app import run_app

        return run_app(args.config, background=getattr(args, "background", False))

    if command == "daemon":
        from .service import run_daemon

        asyncio.run(run_daemon(args.config))
        return 0

    if command == "doctor":
        return _doctor(args.config)

    if command == "models":
        return _models(args)

    if command == "install-desktop":
        from .desktop import install_launcher

        print(f"Added Voxy to your app menu ({install_launcher()}).")
        return 0

    return asyncio.run(_run_client(command, args.config))


if __name__ == "__main__":
    raise SystemExit(main())
