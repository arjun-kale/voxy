"""Catalogue and downloader for Vosk speech models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from typing import Callable

from .config import models_dir
from .speech import model_is_valid


BASE_URL = "https://alphacephei.com/vosk/models"


@dataclass(slots=True, frozen=True)
class ModelInfo:
    id: str
    language: str
    flag: str
    size_mb: int
    quality: str  # "fast" or "accurate"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.id}.zip"

    @property
    def path(self) -> Path:
        return models_dir() / self.id

    @property
    def installed(self) -> bool:
        return model_is_valid(self.path)


CATALOG: list[ModelInfo] = [
    ModelInfo("vosk-model-small-en-us-0.15", "English (US)", "🇺🇸", 40, "fast"),
    ModelInfo("vosk-model-en-us-0.22-lgraph", "English (US)", "🇺🇸", 128, "accurate"),
    ModelInfo("vosk-model-small-en-in-0.4", "English (India)", "🇮🇳", 36, "fast"),
    ModelInfo("vosk-model-small-hi-0.22", "हिन्दी Hindi", "🇮🇳", 42, "fast"),
    ModelInfo("vosk-model-small-es-0.42", "Español", "🇪🇸", 39, "fast"),
    ModelInfo("vosk-model-small-fr-0.22", "Français", "🇫🇷", 41, "fast"),
    ModelInfo("vosk-model-small-de-0.15", "Deutsch", "🇩🇪", 45, "fast"),
    ModelInfo("vosk-model-small-it-0.22", "Italiano", "🇮🇹", 48, "fast"),
    ModelInfo("vosk-model-small-pt-0.3", "Português", "🇧🇷", 31, "fast"),
    ModelInfo("vosk-model-small-nl-0.22", "Nederlands", "🇳🇱", 39, "fast"),
    ModelInfo("vosk-model-small-ru-0.22", "Русский", "🇷🇺", 45, "fast"),
    ModelInfo("vosk-model-small-uk-v3-small", "Українська", "🇺🇦", 133, "fast"),
    ModelInfo("vosk-model-small-tr-0.3", "Türkçe", "🇹🇷", 35, "fast"),
    ModelInfo("vosk-model-small-cn-0.22", "中文 Chinese", "🇨🇳", 42, "fast"),
    ModelInfo("vosk-model-small-ja-0.22", "日本語 Japanese", "🇯🇵", 48, "fast"),
    ModelInfo("vosk-model-small-ko-0.22", "한국어 Korean", "🇰🇷", 82, "fast"),
]


def find_model(model_id: str) -> ModelInfo | None:
    for info in CATALOG:
        if info.id == model_id:
            return info
    return None


def installed_models() -> list[Path]:
    root = models_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if model_is_valid(p))


def describe_model(path: str | Path) -> str:
    p = Path(path)
    info = find_model(p.name)
    if info is not None:
        return f"{info.language} · {info.quality}"
    return p.name


ProgressCallback = Callable[[int, int], None]


class DownloadCancelled(Exception):
    pass


def _find_model_root(extracted: Path) -> Path:
    if model_is_valid(extracted):
        return extracted
    for child in extracted.iterdir():
        if child.is_dir() and model_is_valid(child):
            return child
    raise RuntimeError("The download did not contain a Vosk model.")


def install_zip(archive: Path, target: Path) -> Path:
    """Extracts a model archive and moves it into place atomically."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".extract-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            root = tmp_path.resolve()
            for member in zf.namelist():
                # Refuse archives that try to write outside the extraction folder.
                if not (tmp_path / member).resolve().is_relative_to(root):
                    raise RuntimeError(f"Unsafe path in archive: {member}")
            zf.extractall(tmp_path)
        model_root = _find_model_root(tmp_path)
        if target.exists():
            shutil.rmtree(target)
        model_root.rename(target)
    return target


def download_model(
    info: ModelInfo,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    target = info.path
    if info.installed:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.parent / f".{info.id}.zip.part"

    request = urllib.request.Request(info.url, headers={"User-Agent": "Voxy"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as out:
            total = int(response.headers.get("Content-Length") or info.size_mb * 1024 * 1024)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                block = response.read(256 * 1024)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress is not None:
                    progress(done, total)
        return install_zip(partial, target)
    finally:
        partial.unlink(missing_ok=True)
