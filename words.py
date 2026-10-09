"""
Words of a sentence, for the clickable sentence and the word card (« dictionary »).

    segment(tokens) → [[text, lemma], …]   the texts put end to end give the sentence back
                                           lemma = the dictionary form to look up, "" = not a word to look up
                                           (particles, punctuation…)

A verb or adjective keeps its endings in one piece: 食べ + させ + られ + た → [« 食べさせられた », « 食べる »],
so a click on the conjugated word opens the word itself. Made from the SudachiPy tokens (bank.db), stored in
the exercise (« words ») so an app without SudachiPy (phone, Raspberry Pi) can show it too.
"""

import json
import re

LOOKUP_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "代名詞", "連体詞", "接続詞", "感動詞"}
CONJUGATED = {"動詞", "形容詞", "形状詞"}
KANA_ONLY_SKIP = {"する", "いる", "ある", "なる", "くる", "いく", "おる", "こと", "もの", "の", "ん"}
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿々]")


def _ending(tok: list) -> bool:
    """What sticks to the verb / adjective before it: た, ない, ます, られ, させ, て (+ いる / しまう…)."""
    return tok[1] == "助動詞" or (tok[1] == "接尾辞" and tok[2] in ("形容詞的", "動詞的"))


def segment(tokens: list) -> list:
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        text, pos, lemma = tok[0], tok[1], tok[4] if len(tok) > 4 else tok[0]
        j = i + 1
        if pos in CONJUGATED:
            while j < len(tokens) and _ending(tokens[j]):
                j += 1
            text = "".join(t[0] for t in tokens[i:j])
        clickable = pos in LOOKUP_POS and JAPANESE.search(tok[0]) and not tok[2] == "数詞" \
            and not (lemma in KANA_ONLY_SKIP and not re.search(r"[㐀-鿿]", tok[0]))
        if pos == "名詞" and tok[2] == "固有名詞" and not re.search(r"[㐀-鿿]", tok[0]):
            clickable = False   # katakana names: nothing to learn in a dictionary
        out.append([text, lemma if clickable else ""])
        i = j
    # glue the pieces that are not words to their neighbour, to keep the list short
    merged = []
    for text, lemma in out:
        if merged and not lemma and not merged[-1][1]:
            merged[-1][0] += text
        else:
            merged.append([text, lemma])
    return merged


def from_bank(bank, source_key: str) -> list:
    """The words of an exercise's sentence, from the Tatoeba bank (None if not found)."""
    parts = (source_key or "").split(":")
    if len(parts) < 2 or parts[0] != "tatoeba" or bank is None:
        return None
    row = bank.execute("SELECT tokens FROM sentences WHERE id = ?", (parts[1],)).fetchone()
    return segment(json.loads(row[0])) if row else None


def matches(words: list, sentence: str) -> bool:
    return bool(words) and "".join(w[0] for w in words) == sentence
