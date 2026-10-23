import asyncio
import os
import stat

import pytest

from voice_input import desktop
from voice_input.ipc import AlreadyRunningError, CommandServer, send_command


def test_shortcut_conversions():
    assert desktop.qt_to_gtk("Ctrl+Alt+Space") == "<Control><Alt>space"
    assert desktop.qt_to_gtk("Meta+Shift+V") == "<Super><Shift>v"
    assert desktop.shortcut_label("<Control><Alt>space") == "Ctrl + Alt + Space"
    assert desktop.shortcut_label("<Super>h") == "Super + H"


def test_autostart_toggle(isolated_home):
    desktop.set_autostart(True)
    entry = desktop.autostart_path()
    assert entry.exists()
    assert "app --background" in entry.read_text()
    desktop.set_autostart(False)
    assert not entry.exists()


def test_install_launcher_writes_entry_and_icon(isolated_home):
    entry = desktop.install_launcher()
    assert "Name=Voxy" in entry.read_text()
    assert desktop.icon_path().read_text().startswith("<svg")


def test_ipc_round_trip_and_single_instance(tmp_path):
    socket_path = tmp_path / "voxy.sock"

    async def handler(payload):
        return {"ok": True, "echo": payload["action"]}

    async def scenario():
        server = CommandServer(socket_path, handler)
        await server.start()
        mode = stat.S_IMODE(os.stat(socket_path).st_mode)
        response = await send_command(socket_path, "toggle")
        second = CommandServer(socket_path, handler)
        with pytest.raises(AlreadyRunningError):
            await second.start()
        await server.close()
        return mode, response

    mode, response = asyncio.run(scenario())
    assert mode == 0o600
    assert response == {"ok": True, "echo": "toggle"}


def test_stale_socket_is_replaced(tmp_path):
    socket_path = tmp_path / "voxy.sock"
    socket_path.write_text("left over from a crash")

    async def handler(payload):
        return {"ok": True}

    async def scenario():
        server = CommandServer(socket_path, handler)
        await server.start()
        response = await send_command(socket_path, "status")
        await server.close()
        return response

    assert asyncio.run(scenario()) == {"ok": True}
