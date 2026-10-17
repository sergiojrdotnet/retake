from __future__ import annotations

from .. import config as config_module
from .. import paths
from ..languages import packs
from . import models


def whisper_source(name: str) -> str:
    spec = models.REGISTRY.get(f"whisper-{name}")
    if spec is None:
        return name
    if (spec.path() / "model.bin").exists():
        return str(spec.path())
    snapshot = spec.cached_snapshot()
    return str(snapshot) if snapshot else name


def build(config: dict, check_gpu: bool = True) -> dict:
    resolved = config_module.resolve_engines(config, check_gpu)
    general = config["general"]
    script_pack = packs.get(general["script_language"])
    ui_language = general.get("ui_language", "auto")
    commands_language = script_pack.code if ui_language in ("auto", "") else ui_language
    try:
        commands_pack = packs.get(commands_language)
    except KeyError:
        commands_pack = script_pack
    tracking_model = models.get(script_pack.models.get("tracking", "vosk-en-us-small-0.15"))
    if not tracking_model.installed():
        fallback = models.get(script_pack.models.get("commands", "vosk-en-us-small-0.15"))
        tracking_model = fallback if fallback.installed() else tracking_model
    commands_model = models.get(commands_pack.models.get("commands", "vosk-en-us-small-0.15"))
    wake_word = config["voice"].get("wake_word") or commands_pack.wake_word
    wake_aliases = list(commands_pack.wake_aliases.get(wake_word.lower(), ()))
    try:
        native_pack = packs.get(general.get("native_language", ""))
        wake_aliases += [a for a in native_pack.wake_aliases.get(wake_word.lower(), ()) if a not in wake_aliases]
    except KeyError:
        pass
    whisper = resolved["whisper_model"]
    if script_pack.code != "en" and whisper.endswith(".en"):
        whisper = whisper.removesuffix(".en")
    return {
        **resolved,
        "script_language": script_pack.code,
        "silero_model": models.get("silero-vad-5").path() / "silero_vad.jit",
        "tracking_model": tracking_model.path(),
        "tracking_installed": tracking_model.installed(),
        "whisper_model": whisper,
        "whisper_root": paths.models_dir() / "whisper",
        "whisper_source": whisper_source(whisper),
        "whisper_language": script_pack.whisper_language,
        "commands": resolved["commands"] and commands_model.installed(),
        "commands_model": commands_model.path(),
        "commands_language": commands_pack.code,
        "wake_word": wake_word,
        "wake_aliases": wake_aliases,
        "scorer_model": models.get("wav2vec2-espeak-cv").path(),
        "piper_model": models.get("piper-en-us-ljspeech-medium").path() / "en_US-ljspeech-medium.onnx",
    }


def missing_models(config: dict) -> list[str]:
    general = config["general"]
    script_pack = packs.get(general["script_language"])
    wanted = [script_pack.models.get("tracking"), script_pack.models.get("commands")]
    return [m for m in wanted if m and m in models.REGISTRY and not models.get(m).installed()]
