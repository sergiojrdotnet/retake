---
name: retake-script
description: The script format of Retake, the voice-following teleprompter and recorder. Use when writing, editing, reviewing or converting a script (a Markdown or plain-text screenplay, talk or course episode) that will be read and recorded with Retake, or its pronunciation lexicon (NAME.lexicon.tsv), and when deciding how a change to an already recorded script affects its takes.
---

# Writing a Retake script

Retake shows a script on a teleprompter, follows the reader's voice word by word, records each
sentence as a *take*, scores pronunciation, and cuts the best takes together. The script is plain
Markdown with a few conventions. Everything here is what the parser in
`src/retake/script/parser.py` actually supports; anything else is read as words.

## Files

- `NAME.md`: the script, UTF-8 Markdown, with everything below.
- `NAME.txt`: a plain-text script for simple cases. **No markup at all**: blank lines separate
  paragraphs, sentences end as described in [Sentences](#sentences-the-unit-of-recording), and
  every word is read (`#`, `[…]`, `{…}`, `//` are just text; a lone symbol is shown, not read).
  No sections, so no chapters. Numbers are still matched as spoken.
- `NAME.lexicon.tsv` (optional, same folder, same stem, for either kind): pronunciations and
  spoken forms for words of that script. See [Lexicon](#lexicon). In a `.txt` script it's the
  only way to give a pronunciation or a spoken form.

Pick `.txt` for a short read with nothing to annotate; anything with sections, directions, pauses
or per-occurrence pronunciations needs `.md`.

Check a script before handing it over: `retake check NAME.md` prints the sections, sentence count,
an estimated duration (140 words a minute) and every problem (words with no known pronunciation,
the wake word appearing in the text). `retake check NAME.md --guides` also lists the guides for
hard words.

## Structure

| Markdown | What Retake does |
|---|---|
| Front matter `---\ntitle: …\n---` | Sets the title (optional). |
| `# Heading` (the first one) | The script's title, also a section. |
| `#` … `######` headings | **Sections.** Shown as dividers, never read. Each section is a **chapter**: the top lane of the studio timeline and the chapters of every export start at its first kept sentence. |
| Blank line | Ends a paragraph. The prompter keeps paragraphs together. |
| List items (`-`, `*`, `1.`) | Each item is its own paragraph; the marker isn't read. |
| `> quote` | The `>` is dropped; the text is read. |
| Tables, fenced code blocks, horizontal rules, images | Ignored (never shown, never read). |
| `[text](url)` | Only `text` is shown and read. |

## Sentences: the unit of recording

A sentence ends at `.`, `!`, `?` or `…` (closing quotes or brackets may follow). Known
abbreviations don't end one (`e.g.`, `i.e.`, `etc.`, `vs.`, `Dr.`, `St.`, `a.m.`, `U.S.`, … in
English) and neither does a single initial (`J.`).

**Each sentence is one take.** The reader stumbles, says "retake, again" (or presses `R`), and
reads *that sentence* again; the studio's timeline is the script, sentence after sentence, each
from its newest good take. So:

- Keep sentences short enough to redo comfortably: about 8 to 25 words. A 50-word sentence
  means 50 words again for one slip.
- Put a sentence break where a natural cut would sound right.
- Don't glue lines with `;` or long dash chains when two sentences would do.

## What is read and what isn't

| Markup | Meaning |
|---|---|
| Plain words | Read, followed, scored. |
| `[Cold open, on camera]` | **Stage direction**: anything in square brackets is shown dimmed and never read. |
| `(SMILE)`, `(BEAT)` | Stage direction too: parentheses whose letters are all capitals. |
| `(as we saw earlier)` | Lowercase parentheses are **read** normally. |
| `/` and `//` (standing alone) | Short and long pause marks, shown, never read. |
| `**word**`, `*word*` | Emphasis, shown. |
| `{word\|IPA}` | Pronunciation override for this occurrence, e.g. `{cache\|kæʃ}`, `{read\|rɛd}`. |
| `{written\|=spoken}` | Spoken form: show the written text, follow and coach the words actually said, e.g. `{US$ 1,180\|=eleven hundred eighty dollars}`, `{GKE\|=g k e}`. |
| `(AD-LIB)` … `(/AD-LIB)` | Intentional improvisation: shown as a note, never treated as off-script speech. |
| `[[note]]`, `<!-- … -->`, `/* … */` | Hidden from the prompter (notes for yourself). |
| `→`, `≈`, `US$`, `R$`, `€`, `£` and other symbols | Shown, never read. Write the words if they should be said, or use a spoken form. |

`(SCENE: …)` and `(CAMERA: …)` are not special: with lowercase letters they would be **read**.
Use square brackets for any direction.

## Numbers, acronyms and units (English)

Written numbers are matched the way people say them, so write them naturally:

| Written | Matches |
|---|---|
| `2026` | "twenty twenty-six" (and "two thousand twenty-six") |
| `300` / `1,180` | "three hundred" / "one thousand one hundred eighty" or "eleven eighty" |
| `3.5` / `40%` | "three point five" / "forty percent" |
| `1st`, `22nd` | "first", "twenty-second" |
| `10k` / `5m` | "ten k" or "ten thousand" / "five m" or "five million" |
| `P99` (letters, then digits) | "p ninety-nine" |
| `GKE`, `API` (2 to 6 capitals) | The word, or the letters one by one |
| `007` | "seven" or "zero zero seven" |

Anything else (`k8s`, "eleven hundred eighty", a symbol that must be read) needs a spoken form
`{…|=…}` or a lexicon `spoken` entry. Number rules only apply to English scripts.

## Metadata for the exports

Notes in double brackets can carry metadata into `out/sentences.json` (sentence timing for other
pipelines):

| Note | Where | Meaning |
|---|---|---|
| `[[id: cover]]` | Right under a heading, before its first sentence | Stable id of that section (`section_id` on its sentences). |
| `[[b3]]` | Before sentences | Beat `b3` for the following sentences of the section, until the next beat. |
| `[[key: value]]` | Under a heading: section metadata; elsewhere: for the following sentences of the section | Any key, carried into the exports. |

Metadata resets at each heading.

## Lexicon

`NAME.lexicon.tsv`, tab-separated, one word per line, `#` starts a comment line:

```
# word	ipa	flagged	spoken	coach
kubernetes	kuːbərˈnɛtiːz
tikv	ˈtaɪˌkeɪˈviː		tie kay vee|tee kay vee
gib			gibibytes|gigabytes
cache		yes
read	riːd
sergio				off
```

| Column | Meaning |
|---|---|
| `word` | Lowercase key. Possessives reuse it (`tikv's` needs no row). |
| `ipa` | Replaces the dictionary for every occurrence in this script: guide, pronunciation score and reference voice. Use it for the usual reading of a heteronym, then mark exceptions inline (`{read\|rɛd}`). |
| `flagged` | `yes` always shows the pronunciation guide for this word. |
| `spoken` | How the word may be said, alternatives separated by `\|` (each alternative is words separated by spaces). |
| `coach` | `off` for names and words never to score, drill or guide. |

## Things to avoid

- **The wake word in the text**: `retake` in English scripts, `diretor` in Portuguese ones. Voice
  commands are "retake, again", "retake, skip it"…; the word in the script can trigger them.
- Symbols, units or abbreviations that are read differently from how they're written, without a
  spoken form.
- Words the dictionary won't know (product names, jargon) without a lexicon IPA or spoken form;
  `retake check` lists them.
- Very long sentences and paragraphs of one sentence per line with no blank lines between ideas.

## Changing a script that was already recorded

Takes point at sentences by position; Retake keeps a snapshot of the text they were recorded
against and re-points them when the script changes (on reopening the script, starting a
recording, or *Re-import from the original file*):

| Change | Its takes |
|---|---|
| Unchanged sentence (even moved) | Kept, following it to its new place. |
| Reworded, at least half its words kept | Kept, marked stale; *Re-record changed* in the studio redoes exactly those. |
| Removed, or rewritten beyond half its words | Set aside (out of the edit, restorable). |
| New sentence | None yet. |

Case and punctuation changes don't count. Splitting or merging sentences makes one stale and the
other new. A project keeps its own copy of the script (`scripts/NAME.md` in the project folder):
edits to the original file reach it only through *Re-import from the original file*.

## Example

```markdown
# Episode 1 · The problem
[[episode: ep1]]

## Choosing an Event Store
[[id: cover]]

[Cold open, on camera]
[[b1]] What does it take to choose where a billion events will live for the next ten years?
[[b2]] And what happens when that choice is wrong?

[[b3]] We measured six engines, from a classic relational database to one that lives in a bucket. /
Thirty-two configurations, {300M|=three hundred million} events per engine, all driven from GKE.

(AD-LIB)
Mention the dashboard you're showing.
(/AD-LIB)

## A Brazilian e-invoicing SaaS
[[id: company]]

(SMILE) Our platform issues fiscal documents for thousands of companies. // Every one of them matters.
```
