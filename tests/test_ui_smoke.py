"""Builds every window offscreen to catch wiring mistakes in the UI."""

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from voice_input.config import load_config  # noqa: E402


class FakeRecognizer:
    def __init__(self, config, on_partial, on_final, on_level, on_state, on_error):
        self.on_state = on_state
        self.ready = False

    def start(self):
        self.ready = True
        self.on_state("ready")

    def set_active(self, active):
        pass

    def set_monitor(self, monitor):
        pass

    def close(self):
        pass


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(qapp, monkeypatch):
    from voice_input.engine import sounds
    from voice_input.ui import app as app_mod

    monkeypatch.setattr(sounds, "play", lambda name: None)
    config = load_config()
    config.app.onboarded = True
    ctl = app_mod.Controller(qapp, config)
    ctl.engine._recognizer_factory = FakeRecognizer
    ctl.boot(background=False)
    yield ctl
    ctl.shutdown()
    if ctl.window is not None:
        ctl.window.deleteLater()
    ctl.overlay.deleteLater()


def test_every_page_renders(controller, qapp):
    window = controller.window
    for key in window.pages:
        window.show_page(key)
        qapp.processEvents()
        assert window.current_page() == key
        assert not window.grab().isNull()


def test_listening_drives_overlay(controller, qapp):
    controller.engine.set_listening(True)
    qapp.processEvents()
    assert controller.overlay.mode == "listening"
    controller.overlay.on_typed({"text": "hello there", "mode": "typed"})
    controller.engine.set_listening(False)
    qapp.processEvents()
    assert controller.overlay.mode == "done"
    assert "2 words" in controller.overlay.text.text()


def test_theme_switch_rebuilds_window(controller, qapp):
    controller.window.show_page("settings")
    controller.config.appearance.theme = "light"
    controller.apply_theme()
    qapp.processEvents()
    assert controller.window.current_page() == "settings"


def test_onboarding_walks_through_all_steps(controller, qapp):
    from voice_input.ui.onboarding import Onboarding

    wizard = Onboarding(controller)
    for step in range(Onboarding.STEPS):
        wizard.go(step)
        qapp.processEvents()
    assert controller.engine.preview is False
    wizard.reject()
