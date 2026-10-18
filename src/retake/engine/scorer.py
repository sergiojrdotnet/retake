from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..phonetics import espeak
from ..phonetics.arpabet import Phone
from ..phonetics.cmudict import cmudict
from ..phonetics.ipa import normalize as normalize_ipa

_STRIP = set("ˈˌ.‿ -_|")

# Units the multilingual vocabulary has for other languages, which the model writes as their parts when it
# hears English: aligned whole, a word said perfectly scores near zero on them ("it's" as ɪ + ts).
_FOREIGN = {
    "ts": ("t", "s"), "ju": ("j", "uː"), "ɛɹ": ("ɛ", "ɹ"), "ɪɹ": ("ɪ", "ɹ"), "ʊɹ": ("ʊ", "ɹ"),
    "iə": ("i", "ə"), "r": ("ɹ",), "ʔ": ("t",), "n̩": ("ə", "n"), "l̩": ("ə", "l"),
}
_DECOMPOSE = {
    **_FOREIGN, "ɑːɹ": ("ɑː", "ɹ"), "ɔːɹ": ("ɔː", "ɹ"), "oːɹ": ("oː", "ɹ"), "əl": ("ə", "l"),
    "aɪɚ": ("aɪ", "ɚ"), "aɪə": ("aɪ", "ə"), "ɫ": ("l",),
}
# Symbols the model keeps apart that are one sound to a listener: its multilingual vocabulary writes
# the vowel of "choice" as oɪ as often as ɔɪ, and length marks come and go. Each variant is heard and
# scored as the first symbol of its pair, so saying it isn't a miss.
_SAME = (
    ("ɔɪ", "oɪ"), ("aɪ", "ai"), ("aʊ", "au"), ("oʊ", "əʊ"), ("iː", "i"), ("uː", "u"),
    ("ɑː", "ɑ"), ("ɔː", "ɔ"), ("ɜː", "ɜ"), ("ə", "ɐ"),
)
_CANONICAL = {variant: symbol for symbol, variant in _SAME}
_NEAR = [
    ({"ə", "ʌ", "ᵻ", "ɪ", "ɚ"}, 0.3),
    ({"ɚ", "ɜː", "ɝ"}, 0.2),
    ({"ɔː", "ɑː", "ɒ"}, 0.3),
    ({"ɾ", "t", "d"}, 0.2),
    ({"oʊ", "o", "oː"}, 0.1),
    ({"eɪ", "e", "eː"}, 0.1),
]
_ESPEAKISH = {
    "AA": "ɑː", "AE": "æ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "EY": "eɪ",
    "IH": "ɪ", "IY": "iː", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "uː", "B": "b",
    "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k",
    "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def phones_to_espeakish(phones: list[Phone]) -> str:
    out = []
    for phone in phones:
        if phone.symbol == "AH":
            out.append("ʌ" if phone.stress else "ə")
        elif phone.symbol == "ER":
            out.append("ɜː" if phone.stress else "ɚ")
        else:
            out.append(_ESPEAKISH[phone.symbol])
    return "".join(out)


def english_units(symbols: list[str]) -> list[str]:
    return [part for symbol in symbols for part in _FOREIGN.get(symbol, (symbol,))]


def decompose(symbols: list[str]) -> list[str]:
    out: list[str] = []
    for symbol in symbols:
        out.extend(_CANONICAL.get(part, part) for part in _DECOMPOSE.get(symbol, (symbol,)))
    return out


def _substitution_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    for group, cost in _NEAR:
        if a in group and b in group:
            return cost
    return 1.0


def phone_similarity(expected: list[str], heard: list[str]) -> float:
    if not expected:
        return 0.0
    rows, cols = len(expected) + 1, len(heard) + 1
    table = [[0.0] * cols for _ in range(rows)]
    for i in range(rows):
        table[i][0] = float(i)
    for j in range(cols):
        table[0][j] = float(j)
    for i in range(1, rows):
        for j in range(1, cols):
            table[i][j] = min(
                table[i - 1][j] + 1.0,
                table[i][j - 1] + 1.0,
                table[i - 1][j - 1] + _substitution_cost(expected[i - 1], heard[j - 1]),
            )
    return max(0.0, 1.0 - table[-1][-1] / max(len(expected), len(heard)))


def tokenize_symbols(ipa: str, vocab: dict[str, int]) -> list[str]:
    inverse = {v: k for k, v in vocab.items()}
    return [inverse[i] for i in tokenize_ipa(ipa, vocab)]


def tokenize_ipa(ipa: str, vocab: dict[str, int]) -> list[int]:
    text = "".join(ch for ch in normalize_ipa(ipa) if ch not in _STRIP)
    longest = max(len(k) for k in vocab)
    ids = []
    i = 0
    while i < len(text):
        for size in range(min(longest, len(text) - i), 0, -1):
            token = text[i:i + size]
            if token in vocab and not token.startswith("<"):
                ids.append(vocab[token])
                i += size
                break
        else:
            i += 1
    return ids


def ctc_align(log_probs: np.ndarray, tokens: list[int], blank: int = 0) -> list[tuple[int, int]]:
    frames = log_probs.shape[0]
    if not tokens or frames == 0:
        return []
    states = [blank]
    for token in tokens:
        states.extend([token, blank])
    count = len(states)
    neg = -1e30
    score = np.full((frames, count), neg, dtype=np.float64)
    back = np.zeros((frames, count), dtype=np.int32)
    score[0, 0] = log_probs[0, states[0]]
    if count > 1:
        score[0, 1] = log_probs[0, states[1]]
    allowed = np.array([s >= 2 and states[s] != blank and states[s] != states[s - 2] for s in range(count)])
    for t in range(1, frames):
        previous = score[t - 1]
        stay = previous
        step = np.concatenate([[neg], previous[:-1]])
        skip = np.concatenate([[neg, neg], previous[:-2]])
        skip = np.where(allowed, skip, neg)
        stacked = np.stack([stay, step, skip])
        choice = np.argmax(stacked, axis=0)
        score[t] = stacked[choice, np.arange(count)] + log_probs[t, states]
        back[t] = choice
    end = count - 1 if score[-1, count - 1] >= score[-1, count - 2] else count - 2
    path = np.zeros(frames, dtype=np.int32)
    state = end
    for t in range(frames - 1, -1, -1):
        path[t] = state
        state -= back[t, state]
    spans: list[list[int]] = [[-1, -1] for _ in tokens]
    for t, s in enumerate(path):
        if s % 2 == 1:
            index = s // 2
            if spans[index][0] < 0:
                spans[index][0] = t
            spans[index][1] = t + 1
    for i, span in enumerate(spans):
        if span[0] < 0:
            neighbour = spans[i - 1][1] if i > 0 and spans[i - 1][1] >= 0 else 0
            spans[i] = [neighbour, neighbour + 1]
    return [tuple(span) for span in spans]


@dataclass
class ExpectedWord:
    text: str
    ipa: str
    tokens: list[int]
    alternatives: list[list[str]]
    scored: bool


class PhonemeScorer:
    name = "wav2vec2"

    def __init__(
        self,
        model_dir: Path,
        voice: str,
        device: str = "cpu",
        half: bool = False,
        threads: int = 4,
        function_words: frozenset[str] = frozenset(),
        use_cmudict: bool = True,
    ):
        import torch

        from . import wav2vec2

        self.torch = torch
        if device == "cpu":
            torch.set_num_threads(threads)
        self.device = device
        self.half = half and device != "cpu"
        self.model, self.vocab = wav2vec2.load(model_dir, device, self.half)
        self.same = [(self.vocab[a], self.vocab[b]) for a, b in _SAME if a in self.vocab and b in self.vocab]
        self.canonical = {variant: token for token, variant in self.same}
        self.inverse = {v: k for k, v in self.vocab.items()}
        self.blank = self.vocab.get("<pad>", 0)
        self.voice = voice
        self.function_words = function_words
        self.dictionary = cmudict() if use_cmudict else None
        self.last_seconds = 0.0

    def _phonemize(self, texts: list[str]) -> list[str]:
        sentence = espeak.ipa(" ".join(texts), self.voice).split()
        if len(sentence) == len(texts):
            return sentence
        return espeak.ipa_batch(texts, self.voice)

    def expected(self, words: list[dict]) -> list[ExpectedWord]:
        texts = [w["text"] for w in words]
        ipas = self._phonemize(texts) if texts else []
        result = []
        for word, ipa in zip(words, ipas):
            ipa = word.get("override") or ipa
            symbols = tokenize_symbols(ipa, self.vocab)
            alternatives = [decompose(symbols)]
            if self.dictionary is not None and not word.get("override"):
                for variant in self.dictionary.lookup(word["text"].lower()):
                    alt = decompose(tokenize_symbols(phones_to_espeakish(variant), self.vocab))
                    if alt not in alternatives:
                        alternatives.append(alt)
            scored = word["text"].lower() not in self.function_words
            tokens = [self.canonical.get(self.vocab[part], self.vocab[part]) for part in english_units(symbols) if part in self.vocab]
            result.append(ExpectedWord(word["text"], ipa, tokens, alternatives, scored))
        return result

    def emissions(self, audio: np.ndarray) -> np.ndarray:
        torch = self.torch
        samples = audio.astype(np.float32) / 32768.0
        samples = (samples - samples.mean()) / (samples.std() + 1e-7)
        tensor = torch.from_numpy(samples)[None].to(self.device)
        if self.half:
            tensor = tensor.half()
        with torch.inference_mode():
            probabilities = torch.softmax(self.model(tensor)[0].float(), dim=-1).cpu().numpy()
        for token, variant in self.same:
            probabilities[:, token] += probabilities[:, variant]
            probabilities[:, variant] = 0.0
        return np.log(np.maximum(probabilities, 1e-12))

    def score(self, audio: np.ndarray, words: list[dict]) -> list[dict]:
        started = time.perf_counter()
        expected = self.expected(words)
        log_probs = self.emissions(audio)
        sequence = [tok for word in expected for tok in word.tokens]
        spans = ctc_align(log_probs, sequence, self.blank)
        probabilities = np.exp(log_probs)
        no_blank = probabilities.copy()
        no_blank[:, self.blank] = 0
        no_blank /= no_blank.sum(axis=1, keepdims=True) + 1e-9
        frame = self.model.frame_seconds
        results = []
        cursor = 0
        for word in expected:
            count = len(word.tokens)
            word_spans = spans[cursor:cursor + count]
            cursor += count
            if not word_spans:
                results.append({"score": None, "expected": word.ipa, "heard": "", "start": None, "end": None, "scored": False})
                continue
            phone_scores = [float(no_blank[a:b, token].mean()) if b > a else 0.0 for token, (a, b) in zip(word.tokens, word_spans)]
            first, last = word_spans[0][0], word_spans[-1][1]
            pad = 2
            heard_symbols = self._greedy_symbols(log_probs[max(0, first - pad):last + pad])
            heard = decompose(heard_symbols)
            similarity = max(phone_similarity(alt, heard) for alt in word.alternatives)
            posterior = 0.6 * float(np.mean(phone_scores)) + 0.4 * float(np.min(phone_scores))
            value = 100.0 * (0.5 * posterior + 0.5 * similarity)
            results.append({
                "score": round(value, 1) if word.scored else None,
                "scored": word.scored,
                "expected": word.ipa,
                "heard": "".join(heard_symbols),
                "similarity": round(similarity * 100, 1),
                "phones": [round(p * 100, 1) for p in phone_scores],
                "start": first * frame,
                "end": last * frame,
            })
        self.last_seconds = time.perf_counter() - started
        return results

    def _greedy_symbols(self, log_probs: np.ndarray) -> list[str]:
        ids = log_probs.argmax(axis=1)
        out = []
        previous = None
        for token in ids:
            if token != previous and token != self.blank:
                symbol = self.inverse.get(int(token), "")
                if not symbol.startswith("<"):
                    out.append(symbol)
            previous = token
        return out

    def transcribe(self, audio: np.ndarray) -> str:
        return "".join(self._greedy_symbols(self.emissions(audio)))
