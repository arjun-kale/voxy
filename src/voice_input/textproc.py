"""Converts raw transcripts into formatted text and key actions."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .config import TextConfig


@dataclass(slots=True, frozen=True)
class TypeText:
    text: str


@dataclass(slots=True, frozen=True)
class PressKey:
    key: str
    count: int = 1


@dataclass(slots=True, frozen=True)
class Control:
    name: str


Action = TypeText | PressKey | Control


@dataclass(slots=True)
class Result:
    actions: list[Action] = field(default_factory=list)
    display: str = ""
    command: str | None = None


# Punctuation kinds decide how a symbol glues to its neighbours.
_LEFT = "left"  # attaches to the previous word: "hello," "done."
_RIGHT = "right"  # attaches to the next word: "(note" "“quote"
_BOTH = "both"  # attaches to both: "well-known"
_BREAK = "break"  # line breaks

_PUNCTUATION: list[tuple[tuple[str, ...], str, str]] = [
    (("new", "paragraph"), "\n\n", _BREAK),
    (("new", "line"), "\n", _BREAK),
    (("next", "line"), "\n", _BREAK),
    (("question", "mark"), "?", _LEFT),
    (("exclamation", "mark"), "!", _LEFT),
    (("exclamation", "point"), "!", _LEFT),
    (("full", "stop"), ".", _LEFT),
    (("dot", "dot", "dot"), "…", _LEFT),
    (("open", "quote"), "“", _RIGHT),
    (("close", "quote"), "”", _LEFT),
    (("end", "quote"), "”", _LEFT),
    (("open", "bracket"), "(", _RIGHT),
    (("open", "paren"), "(", _RIGHT),
    (("close", "bracket"), ")", _LEFT),
    (("close", "paren"), ")", _LEFT),
    (("smiley", "face"), ":)", _LEFT),
    (("period",), ".", _LEFT),
    (("comma",), ",", _LEFT),
    (("colon",), ":", _LEFT),
    (("semicolon",), ";", _LEFT),
    (("ellipsis",), "…", _LEFT),
    (("hyphen",), "-", _BOTH),
    (("dash",), " — ", _BOTH),
]

_FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "hmm", "mm", "mhm"}

# Vosk's small models hallucinate these lone words from breathing or room noise.
_NOISE_UTTERANCES = {"the", "huh", "a", "uh", "um", "hmm", "mm"}

_PRONOUN_I = {"i": "I", "i'm": "I'm", "i'll": "I'll", "i've": "I've", "i'd": "I'd"}

_SENTENCE_END = (".", "?", "!", "…", "\n")

_COMMANDS: dict[str, str] = {
    "scratch that": "scratch",
    "delete that": "scratch",
    "undo that": "scratch",
    "stop listening": "stop",
    "stop dictation": "stop",
    "press enter": "enter",
    "press return": "enter",
    "send it": "enter",
    "press tab": "tab",
    "press escape": "escape",
    "undo": "undo",
    "redo": "redo",
    "select all": "select_all",
}

# Commands that may also end a longer utterance: "thanks press enter".
_SUFFIX_COMMANDS = ("press enter", "press return", "send it", "press tab", "stop listening")

_COMMAND_KEYS: dict[str, PressKey] = {
    "enter": PressKey("Return"),
    "tab": PressKey("Tab"),
    "escape": PressKey("Escape"),
    "undo": PressKey("ctrl+z"),
    "redo": PressKey("ctrl+shift+z"),
    "select_all": PressKey("ctrl+a"),
}

COMMAND_HELP: list[tuple[str, str]] = [
    ("“period”, “comma”, “question mark”", "Punctuation"),
    ("“new line”, “new paragraph”", "Line breaks"),
    ("“open quote” … “close quote”", "Quotes and brackets"),
    ("“scratch that”", "Delete what you just said"),
    ("“press enter”, “press tab”", "Press keys"),
    ("“undo”, “redo”, “select all”", "Editing shortcuts"),
    ("“insert <snippet>”", "Expand one of your snippets"),
    ("“stop listening”", "Turn off the microphone"),
]


class TextProcessor:
    def __init__(self, config: TextConfig, append_space: bool = True) -> None:
        self.config = config
        self.append_space = append_space
        self._insertions: list[int] = []
        self._sentence_start = True
        self._trailing_space = False

    def reset(self) -> None:
        """Called whenever a new dictation session starts."""
        self._insertions.clear()
        self._sentence_start = True
        self._trailing_space = False


    def process(self, raw: str) -> Result:
        words = raw.lower().split()
        if not words:
            return Result()
        if len(words) == 1 and words[0] in _NOISE_UTTERANCES:
            return Result()

        phrase = " ".join(words)

        if self.config.voice_commands:
            command = _COMMANDS.get(phrase)
            if command is not None:
                return self._run_command(command)

            snippet = self._match_snippet(phrase)
            if snippet is not None:
                return self._type(snippet, verbatim=True)

            for suffix in _SUFFIX_COMMANDS:
                if phrase.endswith(" " + suffix):
                    head = phrase[: -len(suffix) - 1]
                    typed = self._type_words(head.split())
                    tail = self._run_command(_COMMANDS[suffix])
                    return Result(
                        actions=typed.actions + tail.actions,
                        display=typed.display,
                        command=tail.command,
                    )

        return self._type_words(words)


    def _run_command(self, command: str) -> Result:
        if command == "scratch":
            if not self._insertions:
                return Result(command="scratch")
            count = self._insertions.pop()
            self._sentence_start = not self._insertions
            self._trailing_space = False
            return Result(actions=[PressKey("BackSpace", count)], command="scratch")
        if command == "stop":
            return Result(actions=[Control("stop")], command="stop")

        key = _COMMAND_KEYS[command]
        if command == "enter":
            self._sentence_start = True
            self._trailing_space = False
        return Result(actions=[key], command=command)

    def _match_snippet(self, phrase: str) -> str | None:
        if not self.config.snippets:
            return None
        for prefix in ("insert ", "paste ", "snippet "):
            if phrase.startswith(prefix):
                wanted = phrase[len(prefix):].strip()
                for name, body in self.config.snippets.items():
                    if name.strip().lower() == wanted:
                        return body
        return None

    def _type_words(self, words: list[str]) -> Result:
        if self.config.remove_fillers:
            words = [w for w in words if w not in _FILLERS]
        if not words:
            return Result()

        tokens = self._tokenize(words)
        text = self._assemble(tokens)
        text = self._apply_replacements(text)
        return self._type(text)

    def _tokenize(self, words: list[str]) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        i = 0
        while i < len(words):
            matched = False
            if self.config.spoken_punctuation:
                for pattern, symbol, kind in _PUNCTUATION:
                    size = len(pattern)
                    if tuple(words[i : i + size]) == pattern:
                        tokens.append((kind, symbol))
                        i += size
                        matched = True
                        break
            if not matched:
                tokens.append(("word", words[i]))
                i += 1
        return tokens

    def _assemble(self, tokens: list[tuple[str, str]]) -> str:
        out = ""
        capitalize = self._sentence_start
        glue_next = False

        for kind, value in tokens:
            if kind == "word":
                word = _PRONOUN_I.get(value, value)
                if capitalize and self.config.auto_capitalize:
                    word = word[:1].upper() + word[1:]
                capitalize = False
                if out and not glue_next and not out.endswith((" ", "\n")):
                    out += " "
                out += word
                glue_next = False
            elif kind == _LEFT:
                out = out.rstrip(" ") + value
                if value in _SENTENCE_END:
                    capitalize = True
                glue_next = False
            elif kind == _RIGHT:
                if out and not out.endswith((" ", "\n")):
                    out += " "
                out += value
                glue_next = True
            elif kind == _BOTH:
                out = out.rstrip(" ") + value
                glue_next = True
            elif kind == _BREAK:
                out = out.rstrip(" ") + value
                capitalize = True
                glue_next = True
        return out

    def _apply_replacements(self, text: str) -> str:
        for spoken, written in self.config.replacements.items():
            spoken = spoken.strip()
            if not spoken:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(spoken)}(?!\w)", re.IGNORECASE)
            text = pattern.sub(lambda _m, w=written: w, text)
        return text

    def _type(self, text: str, verbatim: bool = False) -> Result:
        if not text:
            return Result()

        actions: list[Action] = []
        removed = 0
        # "comma" said on its own after a previous phrase: pull it onto that phrase.
        if not verbatim and self._trailing_space and text[0] in ",.?!:;…)”":
            actions.append(PressKey("BackSpace", 1))
            removed = 1

        if self.append_space and not text.endswith(("\n", " ", "(", "“")):
            text += " "

        actions.append(TypeText(text))
        self._insertions.append(len(text))
        if removed and len(self._insertions) > 1:
            self._insertions[-2] -= removed

        stripped = text.rstrip(" ")
        self._sentence_start = stripped.endswith(_SENTENCE_END) or not stripped
        self._trailing_space = text.endswith(" ")
        return Result(actions=actions, display=text.strip())
