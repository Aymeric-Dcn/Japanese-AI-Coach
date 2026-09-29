"""
« Put the sentence back in order »: the translation is shown, the sentence is cut into pieces (a word with
its particles: 東京で, この本を, 買った) and shuffled; the student puts them back in order.

Japanese word order is free for the parts of the sentence that carry their particle: 昨日東京で本を買った
and 東京で昨日本を買った are both right. So an answer is right when:
  - the predicate (verb, adjective or noun + です) comes last;
  - a conjunction or an interjection that opens the sentence (でも, はい) stays first;
  - the other pieces are in any order.
To keep that rule true, only simple sentences are used: one predicate, at the end, and pieces that can
move (arguments with a particle, time words, adverbs). What describes a noun (私の, この, 大きい) is glued
to that noun, since it cannot leave it. Sentences with a relative clause (昨日買った本) are left out: in
them, 昨日 belongs to 買った and would change meaning if moved.

    python word_order.py --count 10        # prints examples, adds nothing
"""

import json
import random
import re
import sqlite3
import sys

import jlpt_questions as jq
import make_exercises as mx

MIN_TILES, MAX_TILES = 3, 6
PUNCT = "。！？!?"
KANJI = re.compile(r"[㐀-鿿々]")


def _is_punct(t: list) -> bool:
    return t[1] in ("補助記号", "空白")


def glue_modifiers(pieces: list) -> list:
    """Glues what describes a noun (私の, この, 大きい, 静かな) to the piece of that noun.
    Returns None when a modifier is a clause (買った本, 背が高い人): the sentence is not simple."""
    kinds = jq.modifier_kinds(pieces, None)
    out = []
    pending = []
    for piece, kind in zip(pieces, kinds):
        if kind:
            verbs = [t for t in piece if t[1] == "動詞" or (t[1] == "助動詞" and t[0] in ("た", "だ", "ない"))]
            if verbs:
                return None                       # a relative clause: 昨日買った本
            if piece[0][1] in ("形容詞", "形状詞") and out and out[-1][-1][0] in ("が", "の") and not pending:
                return None                       # 背が高い人: 背が belongs to 高い
            pending += piece
            continue
        out.append(pending + piece)
        pending = []
    if pending:
        return None
    return out


DEGREE = {"とても", "とっても", "大変", "たいへん", "少し", "すこし", "もっと", "一番", "いちばん", "かなり", "ちょっと",
          "非常", "最も", "もっとも", "ずっと", "すごく", "なんて", "こんなに", "そんなに", "あんなに", "どんなに", "十分"}
# 手に取る, 目を通す, 気にする: a body word + particle right before the verb is a set phrase, one piece with it.
SET_PHRASE_NOUNS = {"手", "目", "耳", "足", "口", "気", "頭", "心", "腹", "顔", "首", "腰", "胸", "地", "身", "声", "力"}
GLUE_NEXT = {"ほとんど", "ほぼ", "約", "およそ"}      # ほとんど毎日: about the next word, not the verb
INSIDE_PREDICATE = {"ない", "無い", "なる", "成る", "する", "為る", "見える", "聞こえる", "感じる"}
MOVE_VERBS = {"行く", "いく", "来る", "くる", "帰る", "出かける", "出掛ける", "戻る"}


def glue_adverbs(pieces: list) -> list:
    """Glues what belongs to the next piece: a degree adverb (とても + 早く), もう + すぐ, ほとんど + 毎日,
    and an adverbial -く that is part of the predicate (小さく + 見える, 恐く + ない).
    Returns None when a degree adverb does not qualify the next word (とても + 朝 + 早く)."""
    out, carry = [], []
    for i, piece in enumerate(pieces):
        piece = carry + piece
        carry = []
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        words = [t[0] for t in piece if t[1] not in ("補助記号",)]
        last_is_pred = i + 1 == len(pieces) - 1
        if nxt and len(piece) == 1 and piece[0][0] in DEGREE:
            if nxt[0][1] not in ("形容詞", "形状詞", "副詞") and not nxt[0][0].endswith("く"):
                return None
            carry = piece
            continue
        if nxt and ((words == ["もう"] and nxt[0][0] == "すぐ") or (len(piece) == 1 and piece[0][0] in GLUE_NEXT)):
            carry = piece
            continue
        if nxt and last_is_pred and piece[-1][1] in ("形容詞", "副詞") and piece[-1][0].endswith("く") \
                and nxt[0][4] in INSIDE_PREDICATE:
            carry = piece
            continue
        if last_is_pred and len(piece) == 2 and piece[0][0] in SET_PHRASE_NOUNS and piece[1][1] == "助詞":
            carry = piece
            continue
        out.append(piece)
    return out


def tile_role(piece: list) -> str:
    """'first' (でも, はい: opens the sentence), 'free' (can move), or '' (not allowed in a simple sentence)."""
    first = piece[0]
    if first[1] in ("接続詞", "感動詞") and len(piece) == 1:
        return "first"
    content = [t for t in piece if t[1] not in ("助詞", "接尾辞", "接頭辞", "補助記号")]
    if any(t[1] in ("動詞", "助動詞") for t in piece):
        return ""                                 # a verb before the end: two clauses
    if any(t[1] == "形容詞" for t in content) and not (len(content) == 1 and content[0][0].endswith("く")):
        return ""                                 # 高い / 高かった before the end (only よく, 早く as adverbs)
    last = piece[-1]
    if last[1] == "助詞":
        if last[2] == "接続助詞":
            return ""                             # から / けど after a clause
        return "free"                             # 東京で, 本を, 私は, 何か
    if first[1] in ("副詞",) or (len(first) > 5 and first[5] == "副詞可能" and len(content) == 1):
        return "free"                             # もう, 毎朝, 今日, 昨日
    if len(content) == 1 and content[0][2] == "数詞" or (len(piece) == 2 and piece[1][2] == "助数詞"):
        return "quantity"                         # 三つ, 二人: free only after 本を / 学生が (see build)
    if first[1] == "形状詞" and last[0] == "に":
        return "free"                             # 静かに
    if len(content) == 1 and content[0][0].endswith("く") and content[0][1] == "形容詞":
        return "free"                             # よく, 早く
    return ""


def build(id_: int, jp: str, fr: str, en: str, tokens: list) -> dict:
    """The exercise for one sentence, or None when the sentence is not a simple one."""
    if not jp or jp[-1] not in PUNCT + "」" or any(c in jp for c in "、「」『』（）()…・"):
        return None
    ending = jp[-1] if jp[-1] in PUNCT else ""
    body = [t for t in tokens if not _is_punct(t)]
    if len(body) != len(tokens) - (1 if ending else 0):
        return None                               # punctuation inside the sentence
    if any(t[1] == "感動詞" and t[2] == "フィラー" for t in body):
        return None
    if "なんて" in jp or "同じ" in jp:
        return None                               # exclamations, comparisons: the pieces lean on each other
    pieces = glue_modifiers(jq.chunk_tokens(body))
    pieces = glue_adverbs(pieces) if pieces else None
    if not pieces or not (MIN_TILES <= len(pieces) <= MAX_TILES):
        return None
    predicate = pieces[-1]
    if not any(t[1] in ("動詞", "形容詞", "助動詞", "形状詞") for t in predicate):
        return None                               # no predicate at the end (an inverted or cut sentence)
    main_verb = next((t for t in predicate if t[1] == "動詞"), None)
    endings = [p[-1][0] if p[-1][1] == "助詞" else "" for p in pieces[:-1]]
    if main_verb and main_verb[4] in MOVE_VERBS and "を" in endings:
        return None                               # 妻を見舞いに行く: を belongs to 見舞い, not to 行く
    if main_verb and main_verb[4] in ("する", "為る") and len(predicate) <= 3 and "に" in endings:
        return None                               # 耳にする, 気にする: set phrases with に
    if any(a == b == "か" for a, b in zip(endings, endings[1:])):
        return None                               # 一か八か: a set phrase
    roles = [tile_role(p) for p in pieces[:-1]]
    for i, r in enumerate(roles):
        if r == "quantity":                       # 本を一冊: floats with its noun; 六ヶ月に一度: does not
            roles[i] = "free" if i and endings[i - 1] in ("を", "が") else ""
    if "" in roles or roles[1:].count("first") or roles.count("free") < 2:
        return None
    tiles = ["".join(t[0] for t in p) for p in pieces]
    if len(set(tiles)) != len(tiles):
        return None                               # two identical pieces: ambiguous to place
    fixed_first = 1 if roles[0] == "first" else 0
    notes = explain(pieces, tiles, fixed_first)
    return {
        "tiles": tiles,
        "fixed_first": fixed_first,
        "ending": ending,
        "sentence": jp,
        "full_sentence": jp,
        "answers": [jp],
        "reading": "".join(t[3] for t in tokens),
        "translation": fr or en or "",
        "translation_en": en or "",
        "show_translation": True,
        **notes,
        "source": f"Tatoeba #{id_}",
        "source_url": f"https://tatoeba.org/fr/sentences/show/{id_}",
        "new_words": [],
        "key": f"tatoeba:{id_}:order:{len(tiles)}",
    }


def explain(pieces: list, tiles: list, fixed_first: int) -> dict:
    """Hint and explanation written by rules (the answer is the original sentence: nothing to invent)."""
    pred = tiles[-1]
    topic = next((tiles[i] for i, p in enumerate(pieces[:-1]) if p[-1][0] in ("は", "も") and p[-1][1] == "助詞"), "")
    glued = [tiles[i] for i, p in enumerate(pieces[:-1])
             if len([t for t in p if t[1] not in ("助詞", "補助記号")]) > 1 and any(t[0] == "の" for t in p)]
    fr = [f"Le prédicat « {pred} » va toujours à la fin."]
    en = [f"The predicate « {pred} » always comes last."]
    if fixed_first:
        fr.append(f"« {tiles[0]} » ouvre la phrase.")
        en.append(f"« {tiles[0]} » opens the sentence.")
    fr.append("Les autres groupes gardent leur particule, qui dit leur rôle : leur ordre est libre. "
              "L'ordre le plus courant : le thème (は) d'abord, puis le moment, le lieu, et l'objet (を) juste avant le verbe.")
    en.append("The other groups keep their particle, which tells their role: their order is free. "
              "The most usual order: the topic (は) first, then time, place, and the object (を) right before the verb.")
    if glued:
        fr.append(f"« {glued[0]} » reste d'un seul morceau : ce qui précise un nom se place juste devant lui.")
        en.append(f"« {glued[0]} » stays in one piece: what describes a noun comes right before it.")
    if topic:
        hint = ("Le verbe (ou l'adjectif, ou です) va à la fin, et le thème en は vient en général en premier.",
                "The verb (or adjective, or です) goes last, and the topic with は usually comes first.")
    else:
        hint = ("Le verbe (ou l'adjectif, ou です) va à la fin.", "The verb (or adjective, or です) goes last.")
    return {"hint": hint[0], "hint_en": hint[1], "explanation": " ".join(fr), "explanation_en": " ".join(en)}


def find(count: int, known: dict = None, max_unknown: int = 1, skip_keys=frozenset(), seed=None,
         min_words: int = 4, max_words: int = 10) -> list:
    """Up to `count` exercises from the sentence bank (both translations needed: shared in FR and EN)."""
    if not mx.BANK_PATH.exists():
        raise mx.GenerationError("Bank not found. Run first: python build_bank.py")
    db = sqlite3.connect(mx.BANK_PATH)
    rows = db.execute("SELECT id, jp, fr, en, tokens FROM sentences WHERE word_count BETWEEN ? AND ? "
                      "AND fr IS NOT NULL AND en IS NOT NULL", (min_words, max_words)).fetchall()
    db.close()
    random.Random(seed).shuffle(rows)
    out, sizes = [], {}
    for id_, jp, fr, en, tokens_json in rows:
        if len(out) >= count:
            break
        tokens = json.loads(tokens_json)
        ex = build(id_, jp, fr, en, tokens)
        if not ex or ex["key"] in skip_keys:
            continue
        if known is not None:
            ex["new_words"] = mx.unknown_words(tokens, set(), known)
            if len(ex["new_words"]) > max_unknown:
                continue
        n = len(ex["tiles"])
        if sizes.get(n, 0) >= max(2, count // 3):
            continue                              # a mix of short and long sentences
        sizes[n] = sizes.get(n, 0) + 1
        out.append(ex)
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import argparse
    p = argparse.ArgumentParser(description="Examples of word-order exercises (nothing is saved).")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()
    known = mx.load_known() if mx.KNOWN_PATH.exists() else None
    for ex in find(args.count, known, seed=args.seed):
        print(" / ".join(ex["tiles"]), "  ←", ex["translation"])


if __name__ == "__main__":
    main()
