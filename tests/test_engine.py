import time

import pytest

from voice_input import engine as engine_mod
from voice_input.config import AppConfig
from voice_input.history import History
from voice_input.typing_backends import FallbackSink, SinkSelection, TextSink


class FakeRecognizer:
    instances: list["FakeRecognizer"] = []

    def __init__(self, config, on_partial, on_final, on_level, on_state, on_error):
        self.on_partial, self.on_final, self.on_level = on_partial, on_final, on_level
        self.on_state, self.on_error = on_state, on_error
        self.active = False
        self.monitor = False
        self.ready = False
        FakeRecognizer.instances.append(self)

    def start(self):
        self.on_state("loading")
        self.ready = True
        self.on_state("ready")

    def set_active(self, active):
        self.active = active

    def set_monitor(self, monitor):
        self.monitor = monitor

    def close(self):
        pass


class Keyboard(TextSink):
    name = "fake"
    label = "Fake keyboard"

    def __init__(self):
        self.events = []

    def send_text(self, text):
        self.events.append(("text", text))

    def send_key(self, key, count=1):
        self.events.append(("key", key, count))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.sounds, "play", lambda name: None)
    keyboard = Keyboard()
    config = AppConfig()
    engine = engine_mod.VoiceEngine(
        config,
        History(tmp_path / "h.jsonl"),
        recognizer_factory=FakeRecognizer,
        sink_factory=lambda backend, on_switch=None: SinkSelection(FallbackSink([keyboard], on_switch), "test"),
    )
    events = []
    engine.subscribe(lambda e, p: events.append((e, p)))
    engine.start()
    yield engine, keyboard, events
    engine.close()


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_ready_after_start(setup):
    engine, _kb, _events = setup
    assert engine.state == "ready"


def test_dictation_types_polished_text_and_records_history(setup):
    engine, kb, events = setup
    engine.set_listening(True)
    assert engine.recognizer.active
    engine.recognizer.on_final("hello world period")
    assert wait_for(lambda: kb.events)
    assert kb.events == [("text", "Hello world. ")]
    assert wait_for(lambda: engine.history.entries())
    assert engine.history.entries()[0].text == "Hello world."
    assert ("typed", {"text": "Hello world.", "mode": "typed"}) in events


def test_toggle_reports_state(setup):
    engine, _kb, events = setup
    assert engine.toggle() is True
    assert engine.state == "listening"
    assert engine.toggle() is False
    assert engine.state == "ready"
    assert ("listening", {"active": True, "reason": ""}) in events


def test_voice_stop_command_turns_off_mic(setup):
    engine, _kb, _events = setup
    engine.set_listening(True)
    engine.recognizer.on_final("stop listening")
    assert wait_for(lambda: not engine.listening)


def test_auto_stop_after_silence(setup):
    engine, _kb, events = setup
    engine.config.behavior.auto_stop_seconds = 1
    engine.set_listening(True)
    engine._last_voice -= 2
    engine.recognizer.on_level(0.0)
    assert not engine.listening
    assert any(e == "notice" and "silence" in p["message"] for e, p in events)


def test_countdown_before_auto_stop(setup):
    engine, _kb, events = setup
    engine.config.behavior.auto_stop_seconds = 10
    engine.set_listening(True)
    engine._last_voice -= 7
    engine.recognizer.on_level(0.0)
    assert ("countdown", 3) in events
    engine.recognizer.on_level(0.9)  # speaking again resets it
    assert events[-1] == ("countdown", 0)


def test_preview_mode_does_not_type(setup):
    engine, kb, events = setup
    engine.preview = True
    engine.set_listening(True)
    engine.recognizer.on_final("just testing")
    assert wait_for(lambda: any(e == "typed" for e, _p in events))
    assert kb.events == []


def test_needs_model_blocks_listening(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.sounds, "play", lambda name: None)
    config = AppConfig()
    config.speech.model_path = str(tmp_path / "nope")
    engine = engine_mod.VoiceEngine(config, History(tmp_path / "h.jsonl"))
    engine.start()
    assert engine.state == "needs_model"
    assert engine.set_listening(True) is False
    engine.close()


def test_reload_restarts_recognizer_only_when_speech_changes(setup):
    engine, _kb, _events = setup
    first = engine.recognizer
    engine.config.text.auto_capitalize = False
    engine.reload()
    assert engine.recognizer is first
    engine.config.speech.device = 2
    engine.reload()
    assert engine.recognizer is not first
