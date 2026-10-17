from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from .. import config as config_module
from ..engine import models, tts
from ..languages import packs

JOBS = ("tracking", "commands", "vad", "scorer", "tts")


def choice(config: dict, job: str) -> str:
    engines = config["engines"]
    if job == "tracking":
        tracking = engines.get("tracking", "auto")
        return f"whisper:{engines.get('whisper_model', 'small.en')}" if tracking == "whisper" else tracking
    if job == "commands":
        return "on" if config["voice"].get("enabled", True) else "off"
    return engines.get(job, "auto")


def apply_choice(config: dict, job: str, value: str) -> None:
    engines = config["engines"]
    if job == "tracking":
        if value.startswith("whisper:"):
            engines["tracking"] = "whisper"
            engines["whisper_model"] = value.split(":", 1)[1]
        else:
            engines["tracking"] = value
    elif job == "commands":
        config["voice"]["enabled"] = value == "on"
    elif job in JOBS:
        engines[job] = value


def _model_row(spec: models.ModelSpec, value: str, extra_requirement: str = "") -> dict:
    missing = [name for name in spec.requires if not config_module.has_module(name)]
    if extra_requirement:
        missing.append(extra_requirement)
    detail = f"{spec.size_mb} MB  ·  {spec.license}"
    if missing:
        detail += "  ·  " + QCoreApplication.translate("Models", "needs %1").replace("%1", ", ".join(missing))
    return {
        "value": value, "title": spec.title, "detail": detail, "model": spec.id,
        "installed": spec.installed(), "available": not missing, "builtin": False,
    }


def _builtin(value: str, title: str, detail: str) -> dict:
    return {"value": value, "title": title, "detail": detail, "model": "", "installed": True, "available": True, "builtin": True}


def _uses(resolved: dict, job: str) -> str:
    if job == "tracking":
        if resolved["tracking"] == "whisper":
            return f"Whisper {resolved['whisper_model']}  ·  {'GPU' if resolved.get('whisper_device') == 'cuda' else 'CPU'}"
        return "Vosk  ·  CPU"
    if job == "commands":
        return QCoreApplication.translate("Models", "On") if resolved["commands"] else QCoreApplication.translate("Models", "Off")
    names = {"silero": "Silero VAD", "energy": QCoreApplication.translate("Models", "Energy"), "wav2vec2": "wav2vec2", "miscue": QCoreApplication.translate("Models", "Word check only"),
             "piper": "Piper", "espeak": "espeak-ng"}
    value = resolved[job]
    device = "  ·  GPU" if job == "scorer" and value == "wav2vec2" and resolved["device"] == "cuda" else ""
    return names.get(value, value) + device


def rows(config: dict, progress: dict[str, float] | None = None, check_gpu: bool = True) -> list[dict]:
    progress = progress or {}
    general = config["general"]
    script_pack = packs.get(general["script_language"])
    resolved = config_module.resolve_engines(config, check_gpu)
    automatic = _builtin("auto", QCoreApplication.translate("Models", "Automatic"), "")
    jobs: list[tuple[str, str, str, list[dict]]] = []

    tracking_model = models.REGISTRY.get(script_pack.models.get("tracking", ""))
    tracking = [dict(automatic, detail=QCoreApplication.translate("Models", "Whisper when an NVIDIA GPU is ready, otherwise Vosk"))]
    tracking += [_model_row(spec, "whisper:" + spec.id.removeprefix("whisper-")) for spec in models.REGISTRY.values() if spec.role == "whisper"]
    if tracking_model:
        tracking.append(_model_row(tracking_model, "vosk"))
    jobs.append(("tracking", QCoreApplication.translate("Models", "Voice following"), QCoreApplication.translate("Models", "Moves the prompter as you read and times every word"), tracking))

    commands_model = models.REGISTRY.get(script_pack.models.get("commands", ""))
    commands = [_model_row(commands_model, "on")] if commands_model else []
    commands.append(_builtin("off", QCoreApplication.translate("Models", "Off"), QCoreApplication.translate("Models", "Keyboard and pedal only")))
    jobs.append(("commands", QCoreApplication.translate("Models", "Voice commands"), QCoreApplication.translate("Models", "Listens for the wake word and a command"), commands))

    vad = [dict(automatic, detail=QCoreApplication.translate("Models", "Silero when PyTorch is installed")), _model_row(models.get("silero-vad-5"), "silero"),
           _builtin("energy", QCoreApplication.translate("Models", "Energy"), QCoreApplication.translate("Models", "Built in, no download; less reliable with background noise"))]
    jobs.append(("vad", QCoreApplication.translate("Models", "Speech detection"), QCoreApplication.translate("Models", "Tells speech from silence to end sentences and place cuts"), vad))

    scorer = [dict(automatic, detail=QCoreApplication.translate("Models", "wav2vec2 when installed")), _model_row(models.get("wav2vec2-espeak-cv"), "wav2vec2"),
              _builtin("miscue", QCoreApplication.translate("Models", "Word check only"), QCoreApplication.translate("Models", "Built in; checks words, not sounds"))]
    jobs.append(("scorer", QCoreApplication.translate("Models", "Pronunciation scoring"), QCoreApplication.translate("Models", "Rates how each word sounded"), scorer))

    voice = [dict(automatic, detail=QCoreApplication.translate("Models", "Piper when installed, otherwise espeak-ng")),
             _model_row(models.get("piper-en-us-ljspeech-medium"), "piper", "" if tts.piper_binary() else "piper"),
             _builtin("espeak", "espeak-ng", QCoreApplication.translate("Models", "Built in; robotic but clear"))]
    jobs.append(("tts", QCoreApplication.translate("Models", "Reference voice"), QCoreApplication.translate("Models", "Says a word or sentence so you can hear it"), voice))

    out = []
    for job, title, hint, options in jobs:
        selected = choice(config, job)
        uses = _uses(resolved, job)
        for option in options:
            out.append({
                **option, "job": job, "jobTitle": title, "jobHint": hint, "uses": uses,
                "selected": option["value"] == selected, "progress": progress.get(option["model"], -1.0),
            })
    return out
