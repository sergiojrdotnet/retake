from retake.engine.scorer import decompose, english_units, phone_similarity, tokenize_symbols


def test_symbols_the_model_writes_apart_for_one_sound_match():
    choice = decompose(["tʃ", "ɔɪ", "s"])
    assert phone_similarity(choice, decompose(["tʃ", "oɪ", "s"])) == 1.0
    assert phone_similarity(choice, decompose(["tʃ", "oʊ", "s"])) < 0.7, "chose isn't choice"
    assert decompose(["iə", "ɐ"]) == ["iː", "ə", "ə"]


def test_units_of_other_languages_are_aligned_as_their_english_parts():
    vocab = {k: i for i, k in enumerate(["<pad>", "f", "j", "ju", "uː", "ɪ", "t", "s", "ts", "r", "ɹ", "iː", "d", "ɪɹ"])}
    assert english_units(tokenize_symbols("fjuː", vocab)) == ["f", "j", "uː"]
    assert english_units(tokenize_symbols("ɪts", vocab)) == ["ɪ", "t", "s"]
    assert english_units(tokenize_symbols("riːd", vocab)) == ["ɹ", "iː", "d"]
    assert english_units(tokenize_symbols("tɪɹ", vocab)) == ["t", "ɪ", "ɹ"]
