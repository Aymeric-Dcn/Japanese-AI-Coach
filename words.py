"""
Words of a sentence, for the clickable sentence and the word card (« dictionary »).

    segment(tokens) → [[text, lemma, reading], …]   the texts put end to end give the sentence back
                                           lemma = the dictionary form to look up, "" = not a word to look up
                                           (particles, punctuation…); reading = kana of the text when it has
                                           kanji, else "" (shown as furigana)

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
KANJI = re.compile(r"[㐀-鿿々]")


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
        out.append([text, lemma if clickable else "", "".join(t[3] for t in tokens[i:j])])
        i = j
    # glue the pieces that are not words to their neighbour, to keep the list short
    merged = []
    for text, lemma, reading in out:
        if merged and not lemma and not merged[-1][1]:
            merged[-1][0] += text
            merged[-1][2] += reading
        else:
            merged.append([text, lemma, reading])
    for m in merged:
        if not KANJI.search(m[0]) or m[2] == m[0] or re.search(r"[0-9０-９]", m[0]):
            m[2] = ""   # no kanji, or a number (13歳 is read « いちさんさい » by the analyzer)
    return merged


def has_readings(words: list) -> bool:
    """True when every word has its reading (words stored before had only two items)."""
    return bool(words) and all(len(w) > 2 for w in words)


def from_bank(bank, source_key: str) -> list:
    """The words of an exercise's sentence, from the Tatoeba bank (None if not found)."""
    parts = (source_key or "").split(":")
    if len(parts) < 2 or parts[0] != "tatoeba" or bank is None:
        return None
    row = bank.execute("SELECT tokens FROM sentences WHERE id = ?", (parts[1],)).fetchone()
    return segment(json.loads(row[0])) if row else None


def matches(words: list, sentence: str) -> bool:
    return bool(words) and "".join(w[0] for w in words) == sentence


def exam_furigana(words: list, level: str, kanji_levels: dict) -> list:
    """Indexes of the words that get their reading in a JLPT question, as in the real test: a word with a
    kanji of a harder level than the test's (or of no level) is given in kana above it."""
    test = int(level[1]) if level[:1] == "N" and level[1:].isdigit() else 5
    marked = []
    for i, w in enumerate(words or []):
        if len(w) < 3 or not w[2]:
            continue
        levels = [kanji_levels.get(c, {}).get("j") for c in w[0] if KANJI.match(c)]
        if any(not lv or lv < test for lv in levels):
            marked.append(i)
    return marked


def choice_readings(choices: list, answer: str, answer_reading: str, lookup) -> list:
    """Kana of each choice of a question, shown after answering. lookup(word) → reading or "".
    A choice sharing the answer's kanji (座った / 座って) takes the reading of the answer's kanji part."""
    out = []
    head = len(answer) - len(re.match(r".*?([぀-ゟ]*)$", answer).group(1))   # 座って → 座 (kanji part)
    stem = answer[:head]
    stem_reading = answer_reading[:len(answer_reading) - (len(answer) - head)] if answer_reading else ""
    for c in choices:
        if not KANJI.search(c):
            out.append("")
        elif c == answer and answer_reading:
            out.append(answer_reading)
        elif stem and stem_reading and c.startswith(stem) and not KANJI.search(c[len(stem):]):
            out.append(stem_reading + c[len(stem):])
        else:
            out.append(lookup(c) or "")
    return out


def reading_in(words: list, sentence: str, text: str) -> str:
    """Kana of a piece of the sentence (筋道が → すじみちが), from the readings of its words; "" if the piece
    cuts a word with kanji in two, or is not in the sentence."""
    start = sentence.find(text) if text else -1
    if start < 0 or not has_readings(words):
        return ""
    end, pos, out = start + len(text), 0, ""
    for w, _lemma, reading in words:
        a, b = pos, pos + len(w)
        pos = b
        if b <= start or a >= end:
            continue
        if a >= start and b <= end:
            out += reading or w
        elif KANJI.search(w[max(0, start - a):len(w) - max(0, b - end)]):
            return ""
        else:
            out += w[max(0, start - a):len(w) - max(0, b - end)]
    return out
