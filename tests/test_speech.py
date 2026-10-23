"""Drives the real recogniser thread with a fake Vosk and a fake microphone."""

import json
import sys
import time
import types

import pytest

from voice_input import speech
from voice_input.config import SpeechConfig


class FakeKaldi:
    def __init__(self, model, rate):
        self.words: list[str] = []

    def AcceptWaveform(self, chunk):
        self.words.append("word")
        return False

    def PartialResult(self):
        return json.dumps({"partial": " ".join(self.words)})

    def Result(self):
        return json.dumps({"text": ""})

    def FinalResult(self):
        text = " ".join(self.words)
        self.words = []
        return json.dumps({"text": text})


class FakeMic(speech._AudioSource):
    opened = 0
    closed = 0
    fail = False

    def __enter__(self):
        if FakeMic.fail:
            raise OSError("device busy")
        FakeMic.opened += 1
        return self

    def __exit__(self, *exc):
        FakeMic.closed += 1

    def read(self):
        time.sleep(0.01)
        return b"\x00\x10" * 160


@pytest.fixture
def recognizer(tmp_path, monkeypatch):
    model = tmp_path / "model"
    (model / "am").mkdir(parents=True)
    fake_vosk = types.SimpleNamespace(KaldiRecognizer=FakeKaldi, Model=lambda path: object(), SetLogLevel=lambda level: None)
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)
    monkeypatch.setattr(speech.StreamingSpeechRecognizer, "_build_audio_source", lambda self: FakeMic())
    FakeMic.opened = FakeMic.closed = 0
    FakeMic.fail = False

    finals, states, errors, levels = [], [], [], []
    rec = speech.StreamingSpeechRecognizer(
        SpeechConfig(model_path=str(model)),
        on_partial=lambda text: None,
        on_final=finals.append,
        on_level=levels.append,
        on_state=states.append,
        on_error=errors.append,
    )
    rec.start()
    yield rec, finals, states, errors, levels
    rec.close()


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_missing_model_raises(tmp_path):
    rec = speech.StreamingSpeechRecognizer(SpeechConfig(model_path=str(tmp_path / "none")), lambda t: None, lambda t: None)
    with pytest.raises(speech.ModelMissingError):
        rec.start()


def test_mic_opens_only_while_listening(recognizer):
    rec, _finals, states, _errors, _levels = recognizer
    assert wait_for(lambda: "ready" in states)
    time.sleep(0.1)
    assert FakeMic.opened == 0
    rec.set_active(True)
    assert wait_for(lambda: FakeMic.opened == 1)
    rec.set_active(False)
    assert wait_for(lambda: FakeMic.closed == 1)


def test_words_spoken_before_stop_are_kept(recognizer):
    rec, finals, states, _errors, levels = recognizer
    assert wait_for(lambda: "ready" in states)
    rec.set_active(True)
    assert wait_for(lambda: len(levels) > 3)
    rec.set_active(False)
    assert wait_for(lambda: finals)
    assert finals[0].startswith("word")


def test_monitor_reports_levels_without_transcribing(recognizer):
    rec, finals, states, _errors, levels = recognizer
    assert wait_for(lambda: "ready" in states)
    rec.set_monitor(True)
    assert wait_for(lambda: len(levels) > 3)
    rec.set_monitor(False)
    time.sleep(0.1)
    assert finals == []


def test_recovers_and_gives_up_after_repeated_mic_failures(recognizer):
    rec, _finals, states, errors, _levels = recognizer
    assert wait_for(lambda: "ready" in states)
    FakeMic.fail = True
    rec.set_active(True)
    assert wait_for(lambda: "mic_failed" in states, timeout=6)
    assert len(errors) == 3
    assert "device busy" in errors[0]
