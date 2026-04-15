from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import load_config
from .ipc import send_command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local voice input daemon")
    parser.add_argument(
        "--config",
        help="Path to config.toml (defaults to ~/.config/voice-input/config.toml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("daemon", help="Run the background daemon")
    subparsers.add_parser("toggle", help="Toggle listening")
    subparsers.add_parser("start", help="Start listening")
    subparsers.add_parser("stop", help="Stop listening")
    subparsers.add_parser("status", help="Show daemon status")
    return parser


async def _run_client(command: str, config_path: str | None) -> int:
    config = load_config(config_path)
    try:
        response = await send_command(config.service.socket_path, command)
    except FileNotFoundError:
        print("Daemon socket not found. Start `voice-input daemon` first.", file=sys.stderr)
        return 1
    except ConnectionRefusedError:
        print("Unable to connect to daemon.", file=sys.stderr)
        return 1
    except PermissionError:
        print(
            "Unable to access the daemon socket. Check that the daemon is running in your user session.",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"IPC error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "daemon":
        from .service import run_daemon

        asyncio.run(run_daemon(args.config))
        return 0

    return asyncio.run(_run_client(args.command, args.config))


if __name__ == "__main__":
    raise SystemExit(main())
