import tomllib

from voice_input.config import dump_config, load_config, save_config


def test_defaults_when_file_missing(tmp_path):
    config = load_config(tmp_path / "missing.toml")
    assert config.input.backend == "auto"
    assert config.behavior.auto_stop_seconds == 20
    assert config.service.socket_path.endswith("voice-input.sock")


def test_round_trip_preserves_everything(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)
    config.speech.device = 3
    config.text.replacements = {"voxy": "Voxy", 'say "hi"': "Hi\\there"}
    config.text.snippets = {"sig": "Best,\nSam"}
    config.appearance.theme = "light"
    config.app.onboarded = True
    save_config(config)

    loaded = load_config(path)
    assert loaded.speech.device == 3
    assert loaded.text.replacements == config.text.replacements
    assert loaded.text.snippets == {"sig": "Best,\nSam"}
    assert loaded.appearance.theme == "light"
    assert loaded.app.onboarded is True


def test_dump_is_valid_toml(tmp_path):
    config = load_config(tmp_path / "x.toml")
    data = tomllib.loads(dump_config(config))
    assert data["speech"]["device"] == ""
    assert data["text"]["replacements"] == {}


def test_legacy_config_still_loads(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[speech]\nmodel_path = "~/models/en"\nsample_rate = 16000\nblocksize = 4000\ndevice = ""\n\n'
        '[input]\nbackend = "wtype"\nappend_space = true\n\n'
        '[service]\nsocket_path = ""\nnotifications = true\n'
    )
    config = load_config(path)
    assert config.speech.model_path.endswith("models/en")
    assert "~" not in config.speech.model_path
    assert config.speech.device is None
    assert config.input.backend == "wtype"
    assert config.service.socket_path.endswith("voice-input.sock")
