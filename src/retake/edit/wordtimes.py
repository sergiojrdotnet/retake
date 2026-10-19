from __future__ import annotations

from typing import Callable

import numpy as np

from . import media
from .edl import Edit

RATE = 16000


def load_aligner(language: str):
    """The coach's phoneme model, or None where it isn't installed."""
    from .. import config as config_module
    from ..engine import models
    from ..languages import packs

    resolved = config_module.resolve_engines(config_module.load())
    if resolved["scorer"] != "wav2vec2":
        return None
    from ..engine.scorer import PhonemeScorer

    pack = packs.get(language)
    device = "cuda" if resolved["device"] == "cuda" else "cpu"
    return PhonemeScorer(models.get("wav2vec2-espeak-cv").path(), pack.espeak_voice, device=device, half=device == "cuda",
                         threads=resolved["threads"], function_words=pack.function_words, use_cmudict=pack.lexicon == "cmudict")


def _release(scorer) -> None:
    torch = scorer.torch
    del scorer.model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def align(script, log, edit: Edit, parts: list, language: str = "en", lexicon=None, scorer=None,
          progress: Callable[[float], None] = lambda fraction: None) -> dict[int, list[dict]]:
    """Every script word of each sentence in the cut, timed in the audio its clips play. The recognizer
    that follows the reading drops words, often a sentence's first, so its timings leave gaps.
    Empty without the phoneme model."""
    takes = {t.id: t for t in log.takes}
    clips_of: dict[int, list] = {}
    played, elapsed = {}, 0.0
    for clip in edit.timeline():
        played[clip.id] = elapsed
        elapsed += clip.duration
        take = takes.get(clip.take)
        if take is not None and take.sentence is not None and clip.sentence == take.sentence:
            clips_of.setdefault(clip.sentence, []).append(clip)
    own = scorer is None
    if own:
        try:
            scorer = load_aligner(language)
        except Exception:
            scorer = None
        if scorer is None:
            return {}
    try:
        aligned = {}
        for done, (index, clips) in enumerate(sorted(clips_of.items())):
            rows = _sentence(scorer, script.sentences[index].words, clips, played, parts, lexicon) if script.sentences[index].words else []
            if rows:
                aligned[index] = rows
            progress((done + 1) / len(clips_of))
        return aligned
    finally:
        if own:
            _release(scorer)


def _sentence(scorer, words: list, clips: list, played: dict[int, float], parts: list, lexicon) -> list[dict]:
    pieces = []
    for clip in clips:
        part = next((p for p in parts if p.start <= clip.start < p.start + p.duration), None)
        if part is None:
            continue
        end = min(clip.end, part.start + part.duration)
        pieces.append((played[clip.id], clip.start, end, media.decode_mono(part.audio, RATE, clip.start - part.start, end - clip.start)))
    if not pieces:
        return []
    audio = np.concatenate([samples for *_, samples in pieces]) * 32768.0
    request = []
    for word in words:
        override = word.override_ipa or (lexicon.word_ipa(word.key) if lexicon is not None else None)
        say = [" ".join(v) for v in word.variants] if len(word.variants) > 1 and not override else []
        request.append({"text": (word.spoken or word.display).strip(".,;:!?\"'()[]"), "override": override, "say": say})
    results = scorer.score(audio, request)

    def placed(t: float) -> tuple[float, float]:
        elapsed = 0.0
        for i, (output, start, end, samples) in enumerate(pieces):
            length = len(samples) / RATE
            if t <= elapsed + length or i == len(pieces) - 1:
                local = min(max(t - elapsed, 0.0), end - start)
                return start + local, output + local
            elapsed += length
        raise AssertionError("no pieces")

    rows = []
    previous = 0.0
    for word, result in zip(words, results):
        start, end = result.get("start"), result.get("end")
        if start is None or end is None:
            start = end = previous
        previous = end
        source_start, output_start = placed(start)
        source_end, output_end = placed(end)
        rows.append({"word": word.index, "text": word.display, "source_start": source_start, "source_end": source_end,
                     "output_start": output_start, "output_end": output_end})
    return rows
