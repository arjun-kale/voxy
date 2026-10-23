import pytest

from voice_input import typing_backends as tb


class Recorder(tb.TextSink):
    def __init__(self, name: str, fail: bool = False, direct: bool = True):
        self.name = name
        self.label = name
        self.fail = fail
        self.types_directly = direct
        self.sent: list[str] = []

    def send_text(self, text: str) -> None:
        if self.fail:
            raise tb.SinkError(f"{self.name} broke")
        self.sent.append(text)


def test_fallback_moves_to_next_sink_and_sticks():
    switches = []
    first, second = Recorder("first", fail=True), Recorder("second")
    sink = tb.FallbackSink([first, second], on_switch=lambda s, r: switches.append((s.name, r)))
    sink.send_text("hello")
    sink.send_text("again")
    assert second.sent == ["hello", "again"]
    assert sink.name == "second"
    assert switches == [("second", "first broke")]


def test_fallback_raises_when_everything_fails():
    sink = tb.FallbackSink([Recorder("a", fail=True), Recorder("b", fail=True)])
    with pytest.raises(tb.SinkError):
        sink.send_text("x")


def test_keys_unsupported_does_not_trigger_fallback():
    clip = Recorder("clip", direct=False)
    sink = tb.FallbackSink([clip])
    with pytest.raises(tb.KeysUnsupported):
        sink.send_key("Return")
    assert sink.index == 0


def test_gnome_wayland_skips_wtype(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.setattr(tb, "_command_exists", lambda name: True)
    assert tb.candidate_backends() == ["ydotool", "clipboard"]


def test_sway_prefers_wtype(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setattr(tb, "_command_exists", lambda name: True)
    assert tb.candidate_backends()[0] == "wtype"


def test_x11_prefers_xdotool(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(tb, "_command_exists", lambda name: name == "xdotool")
    assert tb.candidate_backends() == ["xdotool", "clipboard"]


def test_wtype_key_combo_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(tb, "_run", lambda args, stdin=None: calls.append(args))
    tb.WtypeSink().send_key("ctrl+z")
    tb.WtypeSink().send_key("BackSpace", 2)
    assert calls[0] == ["wtype", "-M", "ctrl", "-k", "z", "-m", "ctrl"]
    assert calls[1] == ["wtype", "-k", "BackSpace", "-k", "BackSpace"]


def test_ydotool_key_codes(monkeypatch):
    calls = []
    monkeypatch.setattr(tb, "_run", lambda args, stdin=None: calls.append(args))
    tb.YdotoolSink().send_key("ctrl+a")
    assert calls[0] == ["ydotool", "key", "29:1", "30:1", "30:0", "29:0"]


def test_text_is_passed_on_stdin_not_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(tb, "_run", lambda args, stdin=None: calls.append((args, stdin)))
    tb.WtypeSink().send_text("-dash first")
    tb.XdotoolSink().send_text("--help")
    assert calls[0] == (["wtype", "-"], "-dash first")
    assert calls[1] == (["xdotool", "type", "--delay", "1", "--file", "-"], "--help")


def test_unknown_backend_rejected():
    with pytest.raises(tb.SinkError):
        tb.build_sink("telepathy")
