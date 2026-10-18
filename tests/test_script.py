from pathlib import Path

from retake.languages import packs
from retake.phonetics.guides import GuideBuilder, is_hard, visible
from retake.script.lexicon import Lexicon
from retake.script.normalize import cardinal, hypothesis_tokens, word_variants, year
from retake.script.parser import parse, parse_file
from retake.session import preflight

FIXTURE = Path(__file__).parent / "fixtures" / "sample.md"


def kinds(sentence):
    return [t.kind for t in sentence.tokens]


def test_parses_sections_cues_and_adlib():
    script = parse_file(FIXTURE, packs.get("en"))
    assert script.title == "Event Store Study Case"
    assert [s.title for s in script.sections] == ["Event Store Study Case", "Introduction"]
    first = script.sentences[0]
    assert kinds(first)[0] == "cue" and first.tokens[0].text == "On camera"
    assert script.sentences[1].words[2].emphasis
    assert any(t.kind == "cue" and t.text == "SMILE" for t in script.sentences[2].tokens)
    assert any(w.override_ipa == "kæʃ" for w in script.sentences[2].words)
    assert any(s.kind == "adlib" and "dashboard" in s.note for s in script.sentences)
    assert all("kubectl" not in s.text for s in script.sentences)


def test_notes_boneyard_and_lowercase_parentheticals():
    text = "Hello [[secret note]] world /* hidden */ (not a cue) here. Next one."
    script = parse(text, packs.get("en"))
    assert script.sentences[0].text == "Hello world (not a cue) here."
    assert script.sentences[1].text == "Next one."


def test_abbreviations_do_not_split_sentences():
    script = parse("We use e.g. caches and Mr. Smith agrees. Done.", packs.get("en"))
    assert len(script.sentences) == 2


def test_pauses_attach_and_cues_start_next_sentence():
    script = parse("First line. / (BREATHE) Second line.", packs.get("en"))
    assert kinds(script.sentences[0])[-1] == "pause"
    assert kinds(script.sentences[1])[0] == "cue"


def test_numbers_and_acronyms_have_spoken_variants():
    assert year(2026) == ["twenty", "twenty", "six"]
    assert year(2005) == ["two", "thousand", "five"]
    assert cardinal(1234) == ["one", "thousand", "two", "hundred", "thirty", "four"]
    assert ["ten", "k"] in word_variants("10k")
    assert ["a", "p", "i"] in word_variants("API")
    assert ["p", "ninety", "nine"] in word_variants("P99")
    assert hypothesis_tokens("It costs 50% in 2026") == ["it", "costs", "fifty", "percent", "in", "twenty", "twenty", "six"]


def test_guides_render_three_ways():
    builder = GuideBuilder(packs.get("en"), packs.get("pt-BR"))
    guide = builder.guide_for_text("aggregate")
    assert guide.ipa == "/ˈæɡrəɡət/"
    assert guide.respell == "AG-ruh-guht"
    assert guide.native == "ÉG-râ-gât"
    assert builder.guide_for_text("beach").native == "biitch"
    assert builder.guide_for_text("bitch").native == "bitch"
    assert builder.guide_for_text("giving").native.startswith("GUI")


def test_guide_scope_and_lexicon(tmp_path):
    script_file = tmp_path / "talk.md"
    script_file.write_text("We deploy Kubernetes clusters.")
    (tmp_path / "talk.lexicon.tsv").write_text("kubernetes\tkuːbərˈnɛtiːz\n")
    lexicon = Lexicon.for_script(script_file)
    lexicon.set_flag("deploy", True)
    reloaded = Lexicon.for_script(script_file)
    assert reloaded.is_flagged("deploy")
    script = parse_file(script_file, packs.get("en"))
    book = GuideBuilder(packs.get("en"), packs.get("pt-BR"), reloaded).build(script)
    kube = book.by_key["kubernetes"]
    assert kube.source == "lexicon" and is_hard(kube, False)
    deploy = book.by_key["deploy"]
    assert visible(deploy, "flagged", True) and not visible(deploy, "flagged", False)
    assert visible(book.by_key["we"], "all", False) and not visible(book.by_key["we"], "hard", False)


def test_preflight_flags_wake_word_and_unknown_words():
    script = parse("Say retake now. The zxqvly thing.", packs.get("en"))
    book = GuideBuilder(packs.get("en"), packs.get("pt-BR")).build(script)
    issues = preflight.check(script, book, packs.get("en"), "retake")
    found = {i.kind for i in issues}
    assert {"wake-word", "pronunciation"} <= found


def test_possessives_reuse_the_base_entry(tmp_path):
    script_file = tmp_path / "talk.md"
    script_file.write_text("Backblaze's price beats TiKV's.")
    (tmp_path / "talk.lexicon.tsv").write_text("backblaze\tˈbækbleɪz\t\tback blaze\ntikv\tˈtaɪkeɪvi\t\ttie kay vee\n")
    lexicon = Lexicon.for_script(script_file)
    script = parse_file(script_file, packs.get("en"), lexicon)
    book = GuideBuilder(packs.get("en"), packs.get("pt-BR"), lexicon).build(script)
    backblaze, tikv = script.words[0], script.words[3]
    assert ["back", "blaze's"] in backblaze.variants and ["tie", "kay", "vee", "s"] in tikv.variants
    assert book.for_word(backblaze).ipa.endswith("zɪz/") and book.for_word(tikv).source == "lexicon"


def test_preflight_trusts_lexicon_readings(tmp_path):
    script_file = tmp_path / "talk.md"
    script_file.write_text("I {read|rɛd} it. We read logs where events live.")
    (tmp_path / "talk.lexicon.tsv").write_text("live\tlɪv\t\t\n")
    lexicon = Lexicon.for_script(script_file)
    script = parse_file(script_file, packs.get("en"), lexicon)
    book = GuideBuilder(packs.get("en"), packs.get("pt-BR"), lexicon).build(script)
    flagged = {i.word for i in preflight.check(script, book, packs.get("en"), "retake") if i.kind == "heteronym"}
    assert "read" in flagged and "live" not in flagged


def test_plain_text_scripts_have_no_markup_but_use_the_lexicon(tmp_path):
    script_file = tmp_path / "notes.txt"
    script_file.write_text("# Not a heading. We read [this] and {that|x} too.\nStill the same paragraph // here.\n\nThe tikv cluster grew. Dr. Smith agreed!\n")
    (tmp_path / "notes.lexicon.tsv").write_text("tikv\t\t\ttie kay vee\n")
    script = parse_file(script_file, packs.get("en"))
    assert script.title == "notes" and script.sections == [] and len(script.paragraphs) == 2
    assert [s.text for s in script.sentences] == [
        "Not a heading.", "We read [this] and {that|x} too.", "Still the same paragraph here.", "The tikv cluster grew.", "Dr. Smith agreed!",
    ]
    assert script.sentences[0].tokens[0].text == "#" and script.sentences[0].tokens[0].kind == "text"
    tikv = next(w for w in script.words if w.display == "tikv")
    assert ["tie", "kay", "vee"] in tikv.variants
