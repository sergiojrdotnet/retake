from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path

from .. import paths
from ..phonetics.respell import RespellingTable

COMMAND_ACTIONS = (
    "again", "next", "back", "pause", "resume", "mark", "stop", "listen",
    "camera_full", "camera_corner", "camera_off", "skip", "uncoach", "drill",
)


@dataclass(frozen=True)
class L1Error:
    id: str
    title: str
    description: str
    expected: tuple[str, ...] = ()
    heard: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    before_final: tuple[str, ...] = ()
    position: str | None = None
    missing: bool = False


@dataclass
class LanguagePack:
    code: str
    name: str
    espeak_voice: str
    whisper_language: str
    piper_voice: str | None = None
    lexicon: str | None = None
    numbers: str | None = None
    segmenter: str = "space"
    abbreviations: tuple[str, ...] = ()
    fillers: tuple[str, ...] = ()
    heteronyms: frozenset[str] = frozenset()
    function_words: frozenset[str] = frozenset()
    models: dict[str, str] = field(default_factory=dict)
    wake_word: str = ""
    commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    say_prefixes: tuple[str, ...] = ()
    wake_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    respelling: RespellingTable | None = None
    l1_errors: tuple[L1Error, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> LanguagePack:
        commands = dict(data.get("commands", {}))
        wake_word = commands.pop("wake_word", "")
        say = tuple(commands.pop("say", ()))
        return cls(
            code=data["code"],
            name=data["name"],
            espeak_voice=data["espeak_voice"],
            whisper_language=data.get("whisper_language", data["code"].split("-")[0]),
            piper_voice=data.get("piper_voice"),
            lexicon=data.get("lexicon"),
            numbers=data.get("numbers"),
            segmenter=data.get("segmenter", "space"),
            abbreviations=tuple(a.lower() for a in data.get("abbreviations", ())),
            fillers=tuple(f.lower() for f in data.get("fillers", ())),
            heteronyms=frozenset(w.lower() for w in data.get("heteronyms", ())),
            function_words=frozenset(w.lower() for w in data.get("function_words", ())),
            models=dict(data.get("models", {})),
            wake_word=wake_word,
            commands={k: tuple(v) for k, v in commands.items()},
            say_prefixes=say,
            wake_aliases={k.lower(): tuple(a.lower() for a in v) for k, v in data.get("wake_aliases", {}).items()},
            respelling=RespellingTable.from_dict(data["respelling"]) if "respelling" in data else None,
            l1_errors=tuple(
                L1Error(
                    id=e["id"],
                    title=e["title"],
                    description=e["description"],
                    expected=tuple(e.get("expected", ())),
                    heard=tuple(e.get("heard", ())),
                    extra=tuple(e.get("extra", ())),
                    before_final=tuple(e.get("before_final", ())),
                    position=e.get("position"),
                    missing=e.get("missing", False),
                )
                for e in data.get("l1_errors", ())
            ),
        )


def _builtin_files() -> dict[str, str]:
    files = {}
    for entry in resources.files("retake.languages").iterdir():
        if entry.name.endswith(".toml"):
            files[entry.name.removesuffix(".toml")] = entry.read_text(encoding="utf-8")
    return files


def _user_files() -> dict[str, str]:
    directory = paths.user_languages_dir()
    if not directory.is_dir():
        return {}
    return {p.stem: p.read_text(encoding="utf-8") for p in directory.glob("*.toml")}


@cache
def all_packs() -> dict[str, LanguagePack]:
    packs = {}
    for code, text in {**_builtin_files(), **_user_files()}.items():
        pack = LanguagePack.from_dict(tomllib.loads(text))
        packs[pack.code] = pack
    return packs


def get(code: str) -> LanguagePack:
    packs = all_packs()
    if code in packs:
        return packs[code]
    base = code.split("-")[0]
    for pack_code, pack in packs.items():
        if pack_code.split("-")[0] == base:
            return pack
    raise KeyError(f"no language pack for {code}")


def load_file(path: Path) -> LanguagePack:
    return LanguagePack.from_dict(tomllib.loads(path.read_text(encoding="utf-8")))
