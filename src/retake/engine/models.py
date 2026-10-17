from __future__ import annotations

import json
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import paths

HF = "https://huggingface.co"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    title: str
    role: str
    license: str
    size_mb: int
    ram_mb: int
    vram_mb: int = 0
    requires: tuple[str, ...] = ()
    files: tuple[tuple[str, str], ...] = ()
    archive: str | None = None
    directory: str = ""
    repo: str = ""
    note: str = ""

    def path(self) -> Path:
        return paths.models_dir() / self.directory

    def cached_snapshot(self) -> Path | None:
        """A copy faster-whisper downloaded itself, in the Hugging Face cache layout."""
        if not self.repo:
            return None
        cache = self.path().parent / ("models--" + self.repo.replace("/", "--")) / "snapshots"
        return next((s for s in sorted(cache.glob("*")) if (s / "model.bin").exists()), None)

    def installed(self) -> bool:
        target = self.path()
        if self.repo:
            return (target / "model.bin").exists() or self.cached_snapshot() is not None
        if self.archive:
            return target.is_dir() and any(target.iterdir())
        return all((target / name).exists() for name, _ in self.files)


def _vosk(model_id: str, name: str, title: str, size: int, ram: int, license: str = "Apache-2.0") -> ModelSpec:
    return ModelSpec(
        id=model_id,
        title=title,
        role="vosk",
        license=license,
        size_mb=size,
        ram_mb=ram,
        requires=("vosk",),
        archive=f"https://alphacephei.com/vosk/models/{name}.zip",
        directory=f"vosk/{name}",
    )


WHISPER_FILES = re.compile(r"^(config\.json|preprocessor_config\.json|model\.bin|tokenizer\.json|vocabulary\.\w+)$")


def _whisper(name: str, size: int, vram: int, repo: str) -> ModelSpec:
    return ModelSpec(
        id=f"whisper-{name}",
        title=f"Whisper {name} (faster-whisper)",
        role="whisper",
        license="MIT",
        size_mb=size,
        ram_mb=size * 2,
        vram_mb=vram,
        requires=("faster_whisper",),
        directory=f"whisper/{name}",
        repo=repo,
    )


REGISTRY: dict[str, ModelSpec] = {
    spec.id: spec
    for spec in (
        _vosk("vosk-en-us-small-0.15", "vosk-model-small-en-us-0.15", "Vosk English (small)", 40, 300),
        _vosk("vosk-en-us-0.22-lgraph", "vosk-model-en-us-0.22-lgraph", "Vosk English (lgraph)", 128, 900),
        _vosk("vosk-pt-small-0.3", "vosk-model-small-pt-0.3", "Vosk Portuguese (small)", 31, 300),
        ModelSpec(
            id="silero-vad-5",
            title="Silero VAD v5",
            role="vad",
            license="MIT",
            size_mb=2,
            ram_mb=60,
            requires=("torch",),
            files=(("silero_vad.jit", "https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.jit"),),
            directory="silero",
        ),
        ModelSpec(
            id="wav2vec2-espeak-cv",
            title="wav2vec2 phoneme recognizer (lv-60 espeak)",
            role="scorer",
            license="Apache-2.0",
            size_mb=1264,
            ram_mb=1500,
            vram_mb=750,
            requires=("torch",),
            files=tuple(
                (name, f"{HF}/facebook/wav2vec2-lv-60-espeak-cv-ft/resolve/main/{name}")
                for name in ("config.json", "vocab.json", "pytorch_model.bin")
            ),
            directory="wav2vec2-lv-60-espeak-cv-ft",
        ),
        ModelSpec(
            id="piper-en-us-ljspeech-medium",
            title="Piper voice: LJSpeech (US English)",
            role="piper",
            license="Public domain (dataset), MIT (Piper)",
            size_mb=63,
            ram_mb=200,
            files=tuple(
                (name, f"{HF}/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/medium/{name}")
                for name in ("en_US-ljspeech-medium.onnx", "en_US-ljspeech-medium.onnx.json")
            ),
            directory="piper",
        ),
        _whisper("small.en", 480, 600, "Systran/faster-whisper-small.en"),
        _whisper("small", 480, 600, "Systran/faster-whisper-small"),
        _whisper("medium.en", 1500, 1600, "Systran/faster-whisper-medium.en"),
        _whisper("large-v3-turbo", 1600, 1800, "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
        _whisper("distil-large-v3", 1500, 1600, "Systran/faster-distil-whisper-large-v3"),
    )
}


def get(model_id: str) -> ModelSpec:
    return REGISTRY[model_id]


@dataclass
class Download:
    spec: ModelSpec
    progress: Callable[[int, int], None] = field(default=lambda done, total: None)
    cancelled: bool = False

    def run(self) -> Path:
        target = self.spec.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.spec.repo:
            return self._fetch_repo(target)
        if self.spec.archive:
            archive = target.parent / (target.name + ".zip")
            self._fetch(self.spec.archive, archive)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target.parent)
            archive.unlink(missing_ok=True)
            return target
        target.mkdir(parents=True, exist_ok=True)
        for name, url in self.spec.files:
            if not (target / name).exists():
                self._fetch(url, target / name)
        return target

    def _fetch_repo(self, target: Path) -> Path:
        listing = urllib.request.Request(f"{HF}/api/models/{self.spec.repo}/tree/main", headers={"User-Agent": "retake"})
        with urllib.request.urlopen(listing, timeout=30) as response:
            files = [(f["path"], int(f.get("size", 0))) for f in json.load(response) if WHISPER_FILES.match(f.get("path", ""))]
        total = sum(size for _, size in files)
        target.mkdir(parents=True, exist_ok=True)
        done = 0
        for name, size in sorted(files, key=lambda item: item[0] == "model.bin"):
            if not (target / name).exists():
                offset = done
                self._fetch(f"{HF}/{self.spec.repo}/resolve/main/{name}", target / name, lambda got, _, offset=offset: self.progress(offset + got, total))
            done += size
        return target

    def _fetch(self, url: str, destination: Path, report: Callable[[int, int], None] | None = None) -> None:
        report = report or self.progress
        partial = destination.with_name(destination.name + ".part")
        done = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={"User-Agent": "retake"})
        if done:
            request.add_header("Range", f"bytes={done}-")
        with urllib.request.urlopen(request, timeout=30) as response:
            if done and response.status != 206:
                done = 0
            total = int(response.headers.get("Content-Length", 0)) + done
            mode = "ab" if done else "wb"
            with open(partial, mode) as handle:
                while True:
                    if self.cancelled:
                        raise InterruptedError("download cancelled")
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    report(done, total)
        partial.rename(destination)


def remove(model_id: str) -> None:
    spec = get(model_id)
    target = spec.path()
    if target.is_dir():
        shutil.rmtree(target)
    snapshot = spec.cached_snapshot()
    if snapshot is not None:
        for link in snapshot.iterdir():
            if link.is_symlink():
                link.resolve().unlink(missing_ok=True)
        shutil.rmtree(snapshot.parent.parent)
