"""
Subordinate clauses: where the blank goes, and the hint and explanation (written by rules, no model needed).

  relative clauses (連体修飾): what describes a noun comes before it, with no « who / that »:
    - "relative-ga":   私が書いた手紙 — the subject of the clause takes が (or の), never は. Only kept when
                       the sentence already has a topic with は before the clause (これは私が書いた手紙です):
                       then は in the clause is wrong for sure.
    - "relative":      the verb before the noun stays in the plain form: 昨日買った本, 隣に住んでいる人
                       (past, negative, ている: the dictionary form alone would just be the cue copied).
  time and concession:
    - "mae-ato":       行く前に (always the dictionary form), 食べた後で (always the past).
    - "temo":          雨が降っても (て-form + も: even if).
"""

import conjugate

# Nouns after a verb that are not « a thing described by a clause » but grammar: こと, ため, 前…
FORMAL_NOUNS = {"こと", "事", "もの", "物", "ところ", "所", "ため", "為", "よう", "様", "はず", "筈", "つもり", "積もり",
                "前", "後", "あと", "時", "とき", "間", "うち", "内", "まま", "わけ", "訳", "ほう", "方", "たび", "度",
                "代わり", "かわり", "通り", "とおり", "くらい", "ぐらい", "程", "ほど", "中", "最中", "場合", "頃", "ごろ",
                "もん", "の", "ん", "感じ", "予定", "限り", "かぎり", "以上", "以外", "あいだ", "気"}
PERMISSION = {"いい", "良い", "よい", "構う", "かまう", "大丈夫", "よろしい", "宜しい"}   # 行ってもいい: permission, not « even if »


def verb_group(tokens: list, v: int) -> int:
    """End (exclusive) of the verb group starting at v: 書い + た, 住ん + で + いる, 行か + なかっ + た."""
    j = v + 1
    while j < len(tokens):
        t = tokens[j]
        if t[1] == "助動詞" and t[4] in ("た", "だ", "ない"):
            j += 1
        elif t[0] in ("て", "で") and t[2] == "接続助詞" and j + 1 < len(tokens) and tokens[j + 1][4] in ("いる", "居る"):
            j += 2
        else:
            break
    return j


def _auxiliary(tokens: list, v: int) -> bool:
    """食べて + いる / しまう: the verb after て is not the one to conjugate."""
    return tokens[v][2] == "非自立可能" and v > 0 and tokens[v - 1][0] in ("て", "で") and tokens[v - 1][2] == "接続助詞"


def plain_forms(lemma: str, conj_type: str) -> dict:
    """The plain forms a verb can take before a noun, by name."""
    f = conjugate.forms(lemma, conj_type)
    neg = f.get("negative") or ""
    te = f.get("te") or ""
    out = {"past": f.get("past"), "negative": neg,
           "negative_past": neg[:-1] + "かった" if neg.endswith("い") else "",
           "te_iru": te + "いる" if te else "", "te_ita": te + "いた" if te else ""}
    return {k: v for k, v in out.items() if v}


FORM_LABEL = {"present": ("présent", "present"), "past": ("passé", "past"), "negative": ("négatif", "negative"),
              "negative_past": ("négatif passé", "negative past"), "te_iru": ("action en cours ou état (〜ている)",
              "ongoing action or state (〜ている)"), "te_ita": ("en cours dans le passé (〜ていた)", "ongoing in the past (〜ていた)")}


def _noun_after(tokens: list, e: int) -> bool:
    if e >= len(tokens):
        return False
    t = tokens[e]
    return t[1] == "名詞" and t[2] == "普通名詞" and t[4] not in FORMAL_NOUNS and t[0] not in FORMAL_NOUNS


# ---------------------------------------------------------------------------
# Where the blank goes
# ---------------------------------------------------------------------------

def relative_blanks(tokens: list) -> list:
    """The verb group of a relative clause (買った in 昨日買った本), when its form is a plain one."""
    spans = []
    for v, t in enumerate(tokens):
        if t[1] != "動詞" or _auxiliary(tokens, v) or t[4].endswith("ずる"):
            continue
        if v and tokens[v - 1][0] in ("ば", "なけれ"):
            continue   # しなければならない仕事: the blank would be ならない
        e = verb_group(tokens, v)
        if not _noun_after(tokens, e):
            continue
        surface = "".join(x[0] for x in tokens[v:e])
        if surface not in plain_forms(t[4], t[6] if len(t) > 6 else "").values():
            continue   # passive, potential, causative…: the cue would not be enough to find it
        spans.append((v, e))
    return spans if len(spans) == 1 else []


def relative_ga_blanks(tokens: list) -> list:
    """が of a relative clause, in a sentence whose topic (は) comes before: これは私が書いた手紙です."""
    spans = []
    for k, t in enumerate(tokens):
        if t[0] != "が" or t[2] != "格助詞" or k == 0 or tokens[k - 1][1] not in ("名詞", "代名詞", "接尾辞"):
            continue
        if not any(x[0] == "は" and x[2] == "係助詞" for x in tokens[:k]):
            continue
        v = next((j for j in range(k + 1, len(tokens)) if tokens[j][1] in ("動詞", "形容詞")), None)
        if v is None or any(x[0] in ("は", "、", "が", "も") or x[1] == "補助記号" for x in tokens[k + 1:v]):
            continue
        if tokens[v][1] != "動詞":
            continue   # 青が一番美しい色だ: with an adjective, often a sentence of its own, not a relative clause
        e = verb_group(tokens, v)
        if _noun_after(tokens, e):
            spans.append((k, k + 1))
    return spans if len(spans) == 1 else []


def mae_ato_blanks(tokens: list) -> list:
    """行く前に (blank 行く) or 食べた後で (blank 食べた)."""
    spans = []
    for v, t in enumerate(tokens):
        if t[1] != "動詞" or _auxiliary(tokens, v):
            continue
        nxt = tokens[v + 1:v + 4]
        if len(nxt) >= 2 and nxt[0][4] == "前" and nxt[1][0] in ("に", "は") and t[0] == t[4]:
            spans.append((v, v + 1))
        elif len(nxt) >= 3 and nxt[0][0] in ("た", "だ") and nxt[0][1] == "助動詞" and nxt[1][4] in ("後", "あと") \
                and nxt[2][0] in ("で", "に", "は"):
            spans.append((v, v + 2))
    return spans if len(spans) == 1 else []


def temo_blanks(tokens: list) -> list:
    """降っても (blank 降っても): て-form + も, not 〜てもいい (permission)."""
    spans = []
    for v, t in enumerate(tokens):
        if t[1] != "動詞" or _auxiliary(tokens, v):
            continue
        nxt = tokens[v + 1:v + 4]
        if t[0] == "とっ" and t[4] == "とる":
            continue   # とっても = とても (very)
        before = tokens[v - 1][0] if v else ""
        if before in ("に", "何と", "なんと") or (t[4] in ("する", "為る") and before in ("どう", "いずれ")):
            continue   # にしても / についても, どうしても / 何としても / なんと言っても: set phrases
        if len(tokens) > v + 3 and tokens[v + 3][4] in ("見る", "みる"):
            continue   # 思ってもみない: « never thought », a set phrase
        if len(nxt) >= 2 and nxt[0][0] in ("て", "で") and nxt[0][2] == "接続助詞" and nxt[1][0] == "も" \
                and not (len(nxt) > 2 and nxt[2][4] in PERMISSION):
            spans.append((v, v + 3))
    return spans if len(spans) == 1 else []


BLANKS = {"relative": relative_blanks, "mae-ato": mae_ato_blanks, "temo": temo_blanks}


# ---------------------------------------------------------------------------
# Hints and explanations
# ---------------------------------------------------------------------------

def notes(form: str, tokens: list, span: tuple) -> dict:
    """{"hint", "hint_en", "explanation", "explanation_en"} for a blank found above ({} if unsure)."""
    a, b = span
    verb = tokens[a]
    lemma, conj = verb[4], verb[6] if len(verb) > 6 else ""
    answer = "".join(t[0] for t in tokens[a:b])
    if form == "relative-ga":
        return _notes_relative_ga(tokens, a)
    if form == "relative":
        name = next((k for k, v in plain_forms(lemma, conj).items() if v == answer), "")
        if not name:
            return {}
        noun = tokens[b][0]
        fr, en = FORM_LABEL[name]
        return {"hint": "Devant un nom, le verbe reste à la forme simple (pas de ます). La traduction dit le temps.",
                "hint_en": "Before a noun the verb stays in the plain form (no ます). The translation tells the tense.",
                "explanation": f"{lemma} → {answer} ({fr}). Une proposition relative se place devant le nom qu'elle décrit "
                               f"(ici « {noun} »), sans « qui / que », et son verbe est à la forme simple.",
                "explanation_en": f"{lemma} → {answer} ({en}). A relative clause comes before the noun it describes "
                                  f"(here « {noun} »), with no « who / that », and its verb is in the plain form."}
    if form == "mae-ato":
        if tokens[b][4] == "前":
            return {"hint": "Devant 前に, le verbe garde toujours la même forme, même pour une action passée.",
                    "hint_en": "Before 前に the verb always keeps the same form, even for a past action.",
                    "explanation": f"〜前に = avant de… : le verbe reste à la forme du dictionnaire ({lemma}), même "
                                   f"quand la phrase est au passé (jamais 〜た前に).",
                    "explanation_en": f"〜前に = before…: the verb stays in the dictionary form ({lemma}), even when the "
                                      f"sentence is in the past (never 〜た前に)."}
        d = conjugate.describe(lemma, "past", answer, conj)
        if not d:
            return {}
        return {"hint": d["hint"] + " Devant 後で : toujours le passé en た.",
                "hint_en": d["hint_en"] + " Before 後で: always the た past.",
                "explanation": f"{d['rule']} 〜た後で = après avoir… : le verbe est toujours au passé en た devant 後で, "
                               f"même pour une action future.",
                "explanation_en": f"{d['rule_en']} 〜た後で = after…: the verb is always in the た past before 後で, "
                                  f"even for a future action."}
    if form == "temo":
        d = conjugate.describe(lemma, "te", answer[:-1], conj)
        if not d:
            return {}
        return {"hint": d["hint"] + " Puis + も.", "hint_en": d["hint_en"] + " Then + も.",
                "explanation": f"{d['rule']} + も = {answer} : « même si… / même en… ». Ce qui suit arrive malgré tout.",
                "explanation_en": f"{d['rule_en']} + も = {answer}: « even if… ». What follows happens anyway."}
    return {}


def _notes_relative_ga(tokens: list, k: int) -> dict:
    topic_end = max(j for j in range(k) if tokens[j][0] == "は" and tokens[j][2] == "係助詞")
    start = topic_end
    while start > 0 and tokens[start - 1][1] not in ("補助記号",) and tokens[start - 1][0] not in ("、",):
        start -= 1
    topic = "".join(t[0] for t in tokens[start:topic_end + 1])
    v = next(j for j in range(k + 1, len(tokens)) if tokens[j][1] in ("動詞", "形容詞"))
    e = verb_group(tokens, v) if tokens[v][1] == "動詞" else v + 1
    clause = "".join(t[0] for t in tokens[k - 1:e])
    noun = tokens[e][0]
    return {"hint": f"« …{noun} » est décrit par une proposition placée devant lui. Quel est le sujet de cette proposition ?",
            "hint_en": f"« …{noun} » is described by a clause placed before it. What is the subject of that clause?",
            "explanation": f"« {clause} » décrit « {noun} » : c'est une proposition relative. Son sujet prend が (ou の), "
                           f"jamais は : は marque le thème de toute la phrase, ici « {topic} ».",
            "explanation_en": f"« {clause} » describes « {noun} »: it is a relative clause. Its subject takes が (or の), "
                              f"never は: は marks the topic of the whole sentence, here « {topic} »."}
