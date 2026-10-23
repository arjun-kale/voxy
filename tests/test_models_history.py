import time
import zipfile

import pytest

from voice_input.history import History
from voice_input.models import install_zip
from voice_input.speech import rms_level


def _model_zip(path, prefix="vosk-model-test/"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(prefix + "am/final.mdl", "x")
        zf.writestr(prefix + "conf/model.conf", "x")
    return path


def test_install_zip_moves_model_into_place(tmp_path):
    archive = _model_zip(tmp_path / "m.zip")
    target = tmp_path / "models" / "vosk-model-test"
    install_zip(archive, target)
    assert (target / "am" / "final.mdl").exists()
    assert not any(p.name.startswith(".extract-") for p in target.parent.iterdir())


def test_install_zip_rejects_path_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    with pytest.raises(RuntimeError):
        install_zip(archive, tmp_path / "models" / "x")
    assert not (tmp_path / "evil.txt").exists()


def test_install_zip_requires_a_model(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(RuntimeError):
        install_zip(archive, tmp_path / "models" / "x")


def test_history_persists_and_counts(tmp_path):
    path = tmp_path / "history.jsonl"
    history = History(path)
    history.add("one two three")
    history.add("four")
    reloaded = History(path)
    assert [e.text for e in reloaded.entries()] == ["four", "one two three"]
    stats = reloaded.stats()
    assert stats.total_words == 4
    assert stats.today_words == 4
    assert stats.minutes_saved > 0


def test_history_respects_limit_and_disable(tmp_path):
    history = History(tmp_path / "h.jsonl", limit=5)
    for i in range(20):
        history.add(f"entry {i}")
    assert len(History(tmp_path / "h.jsonl", limit=5).entries()) <= 6
    history.enabled = False
    assert history.add("secret") is None


def test_history_remove_and_clear(tmp_path):
    history = History(tmp_path / "h.jsonl")
    entry = history.add("remove me")
    history.add("keep me")
    time.sleep(0.001)
    history.remove(entry.ts)
    assert [e.text for e in history.entries()] == ["keep me"]
    history.clear()
    assert history.entries() == []


def test_rms_level_range():
    silence = b"\x00\x00" * 1600
    loud = (b"\xff\x7f" + b"\x01\x80") * 800
    assert rms_level(silence) == 0.0
    assert rms_level(loud) == pytest.approx(1.0, abs=0.01)
    assert rms_level(b"\x01") == 0.0
