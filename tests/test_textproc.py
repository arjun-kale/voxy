from voice_input.config import TextConfig
from voice_input.textproc import Control, PressKey, TextProcessor, TypeText


def make(**overrides) -> TextProcessor:
    config = TextConfig(**overrides)
    return TextProcessor(config, append_space=True)


def typed(result) -> str:
    return "".join(a.text for a in result.actions if isinstance(a, TypeText))


def test_capitalises_first_word_and_pronoun_i():
    p = make()
    assert typed(p.process("hello there i think so")) == "Hello there I think so "


def test_spoken_punctuation_and_sentence_capitals():
    p = make()
    out = typed(p.process("hello comma world period how are you question mark"))
    assert out == "Hello, world. How are you? "


def test_capitalisation_carries_across_phrases():
    p = make()
    assert typed(p.process("first sentence period")) == "First sentence. "
    assert typed(p.process("second one")) == "Second one "
    assert typed(p.process("still going")) == "still going "


def test_lone_punctuation_pulls_back_trailing_space():
    p = make()
    p.process("that is all")
    result = p.process("period")
    assert result.actions == [PressKey("BackSpace", 1), TypeText(". ")]


def test_new_line_and_paragraph():
    p = make()
    assert typed(p.process("dear sam new paragraph thanks")) == "Dear sam\n\nThanks "


def test_quotes_and_brackets_glue_correctly():
    p = make()
    out = typed(p.process("she said open quote hi close quote open bracket twice close bracket"))
    assert out == "She said “hi” (twice) "


def test_hyphen_joins_words():
    p = make()
    assert typed(p.process("a well hyphen known fact")) == "A well-known fact "


def test_filler_words_removed():
    p = make()
    assert typed(p.process("um so uh we should go")) == "So we should go "


def test_fillers_kept_when_disabled():
    p = make(remove_fillers=False)
    assert typed(p.process("um yes")) == "Um yes "


def test_noise_only_utterance_ignored():
    p = make()
    assert p.process("the").actions == []
    assert p.process("   ").actions == []


def test_scratch_that_deletes_last_phrase():
    p = make()
    p.process("keep this")
    p.process("oops wrong words")
    result = p.process("scratch that")
    assert result.actions == [PressKey("BackSpace", len("oops wrong words "))]
    assert result.command == "scratch"


def test_scratch_that_with_nothing_to_delete():
    p = make()
    assert p.process("scratch that").actions == []


def test_press_enter_command_and_suffix():
    p = make()
    assert p.process("press enter").actions == [PressKey("Return")]
    result = p.process("see you soon send it")
    assert result.actions == [TypeText("See you soon "), PressKey("Return")]


def test_stop_listening_command():
    p = make()
    result = p.process("stop listening")
    assert result.actions == [Control("stop")]
    assert result.command == "stop"


def test_commands_typed_literally_when_disabled():
    p = make(voice_commands=False)
    assert typed(p.process("press enter")) == "Press enter "


def test_replacements_are_case_insensitive_whole_words():
    p = make(replacements={"voxy": "Voxy", "github": "GitHub"})
    assert typed(p.process("i love voxy and github but not voxyish")) == "I love Voxy and GitHub but not voxyish "


def test_snippets_insert_verbatim():
    p = make(snippets={"my email": "sam@example.com"})
    result = p.process("insert my email")
    assert result.actions == [TypeText("sam@example.com ")]


def test_unknown_snippet_is_typed_as_words():
    p = make(snippets={"my email": "sam@example.com"})
    assert typed(p.process("insert coin")) == "Insert coin "


def test_reset_restores_sentence_start():
    p = make()
    p.process("hello")
    p.reset()
    assert typed(p.process("again")) == "Again "


def test_no_trailing_space_when_disabled():
    p = TextProcessor(TextConfig(), append_space=False)
    assert typed(p.process("hello")) == "Hello"
