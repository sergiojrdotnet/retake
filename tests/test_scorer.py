from retake.engine.scorer import decompose, english_units, in_context, phone_similarity, tokenize_symbols


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


def test_words_take_their_reading_in_the_sentence_only_where_it_lines_up():
    # espeak read "In the" as one piece and "PostgreSQL" as two: by position, "campaign" got "postgr".
    alone = ["ˈɪn", "ðˈə", "kæmpˈeɪn", "pˈoʊstɡɚɹ ˌɛskjˌuːˈɛl", "ɐ", "jˈuːzd"]
    sentence = ["ɪnðə", "kæmpˈeɪn", "pˈoʊstɡɚɹ", "ˌɛskjˌuːˈɛl", "ɐ", "jˈuːzd"]
    read = in_context(alone, sentence)
    assert read[2] == "kæmpˈeɪn" and read[3] == "pˈoʊstɡɚɹ ˌɛskjˌuːˈɛl"
    assert read[:2] == alone[:2] and read[4:] == ["ɐ", "jˈuːzd"]
