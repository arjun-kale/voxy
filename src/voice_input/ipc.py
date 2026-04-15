from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable


JsonDict = dict[str, object]
CommandHandler = Callable[[JsonDict], Awaitable[JsonDict]]


class CommandServer:
    def __init__(self, socket_path: str | Path, handler: CommandHandler) -> None:
        self.socket_path = Path(socket_path)
        self.handler = handler
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self.socket_path),
        )

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            payload = json.loads(raw.decode("utf-8"))
            response = await self.handler(payload)
        except Exception as exc:  # pragma: no cover - defensive IPC boundary
            response = {"ok": False, "error": str(exc)}

        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def send_command(socket_path: str | Path, action: str) -> JsonDict:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write((json.dumps({"action": action}) + "\n").encode("utf-8"))
    await writer.drain()
    response = json.loads((await reader.readline()).decode("utf-8"))
    writer.close()
    await writer.wait_closed()
    return response
