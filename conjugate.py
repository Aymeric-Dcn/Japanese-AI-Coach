"""
A small, deterministic Japanese verb conjugator (used for JLPT multiple-choice options).

    conjugate("書く", "te")                 → "書いて"
    conjugate("たべる", "negative", "一段")   → "たべない"
    forms("行く")                           → {"te": "行って", "past": "行った", …}

The verb class comes from SudachiPy's conjugation type when known (五段-カ行, 下一段-バ行,
サ行変格, カ行変格); otherwise it is guessed from the ending.
"""

FORMS = ["plain", "masu", "te", "past", "negative", "tai", "volitional", "ba", "tara", "causative", "passive"]

GODAN_ROWS = {  # dictionary ending → (a, i, e, o) rows
    "う": "わいえお", "く": "かきけこ", "ぐ": "がぎげご", "す": "さしせそ", "つ": "たちてと",
    "ぬ": "なにねの", "ぶ": "ばびべぼ", "む": "まみめも", "る": "らりれろ",
}
TE = {"う": ("って", "った"), "つ": ("って", "った"), "る": ("って", "った"),
      "む": ("んで", "んだ"), "ぶ": ("んで", "んだ"), "ぬ": ("んで", "んだ"),
      "く": ("いて", "いた"), "ぐ": ("いで", "いだ"), "す": ("して", "した")}
# Verbs ending in -iru / -eru that are nevertheless godan.
GODAN_RU = {"帰る", "かえる", "入る", "はいる", "走る", "はしる", "知る", "しる", "切る", "きる", "要る", "いる",
            "限る", "かぎる", "喋る", "しゃべる", "減る", "へる", "焦る", "あせる", "蹴る", "ける", "滑る", "すべる",
            "握る", "にぎる", "参る", "まいる", "混じる", "まじる", "照る", "てる", "茂る", "しげる", "湿る", "しめる"}
I_ROW = set("いきぎしじちぢにひびぴみりゐ")
E_ROW = set("えけげせぜてでねへべぺめれゑ")


def verb_class(lemma: str, conj_type: str = "", reading: str = "") -> str:
    """"godan", "ichidan", "suru", "kuru" (or "" if not a verb we can conjugate)."""
    if conj_type:
        if conj_type.startswith("五段"):
            return "godan"
        if "一段" in conj_type:
            return "ichidan"
        if conj_type.startswith("サ行変格"):
            return "suru"
        if conj_type.startswith("カ行変格"):
            return "kuru"
    if lemma.endswith(("する", "為る")):
        return "suru"
    if lemma in ("来る", "くる"):
        return "kuru"
    if lemma[-1:] not in GODAN_ROWS:
        return ""
    if lemma.endswith(("帰る", "返る", "入る", "走る", "切る", "要る", "減る", "限る")):
        return "godan"   # 生き返る, 立ち入る…: compounds of godan verbs that look ichidan
    if lemma.endswith("る") and lemma not in GODAN_RU:
        before = (reading or lemma)[-2:-1]
        if before in I_ROW or before in E_ROW:
            return "ichidan"
    return "godan"


def conjugate(lemma: str, form: str, conj_type: str = "", reading: str = "") -> str:
    cls = verb_class(lemma, conj_type, reading)
    if form == "plain":
        return lemma
    if cls == "ichidan":
        stem = lemma[:-1]
        return stem + {"masu": "ます", "te": "て", "past": "た", "negative": "ない", "tai": "たい",
                       "volitional": "よう", "ba": "れば", "tara": "たら", "causative": "させる",
                       "passive": "られる", "nagara": "ながら"}[form]
    if cls == "suru":
        stem = lemma[:-2]
        return stem + {"masu": "します", "te": "して", "past": "した", "negative": "しない", "tai": "したい",
                       "volitional": "しよう", "ba": "すれば", "tara": "したら", "causative": "させる",
                       "passive": "される", "nagara": "しながら"}[form]
    if cls == "kuru":
        k = "来" if lemma.startswith("来") else ""
        stem = lemma[:-2] if not k else lemma[:-2]
        table = {"masu": ("き", "ます"), "te": ("き", "て"), "past": ("き", "た"), "negative": ("こ", "ない"),
                 "tai": ("き", "たい"), "volitional": ("こ", "よう"), "ba": ("く", "れば"), "tara": ("き", "たら"),
                 "causative": ("こ", "させる"), "passive": ("こ", "られる"), "nagara": ("き", "ながら")}
        kana, ending = table[form]
        return stem + (k or kana) + ending
    if cls == "godan":
        stem, last = lemma[:-1], lemma[-1]
        a, i, e, o = GODAN_ROWS[last]
        if form in ("te", "past", "tara"):
            te, ta = TE[last]
            if lemma in ("行く", "いく", "逝く"):
                te, ta = "って", "った"
            return stem + {"te": te, "past": ta, "tara": ta + "ら"}[form]
        if form == "negative" and lemma in ("ある", "有る"):
            return "ない"
        return stem + {"masu": i + "ます", "negative": a + "ない", "tai": i + "たい", "volitional": o + "う",
                       "ba": e + "ば", "causative": a + "せる", "passive": a + "れる",
                       "nagara": i + "ながら"}[form]
    return ""


def forms(lemma: str, conj_type: str = "", reading: str = "") -> dict:
    return {f: conjugate(lemma, f, conj_type, reading) for f in FORMS}


# ---------------------------------------------------------------------------
# How a form is built, in words (hints and explanations of the exercises)
# ---------------------------------------------------------------------------

SUFFIX = {"masu": "ます", "negative": "ない", "tai": "たい", "volitional": "う", "ba": "ば", "causative": "せる", "nagara": "ながら"}
GODAN_ROW = {"masu": 1, "tai": 1, "nagara": 1, "negative": 0, "causative": 0, "ba": 2, "volitional": 3}
ICHIDAN_SUFFIX = {"masu": "ます", "te": "て", "past": "た", "negative": "ない", "tai": "たい", "volitional": "よう",
                  "ba": "れば", "tara": "たら", "causative": "させる", "nagara": "ながら"}
TE_RULE = {"fr": "う・つ・る → って, む・ぶ・ぬ → んで, く → いて, ぐ → いで, す → して",
           "en": "う・つ・る → って, む・ぶ・ぬ → んで, く → いて, ぐ → いで, す → して"}
TE_WORD = {"te": "て", "past": "た", "tara": "たら"}


def describe(lemma: str, form: str, answer: str, conj_type: str = "", reading: str = "") -> dict:
    """{"hint", "hint_en", "rule", "rule_en"} for « lemma → answer », or {} when the form is not the regular one
    (the answer may be a potential or a compound: then nothing is said rather than something wrong)."""
    cls = verb_class(lemma, conj_type, reading)
    built = conjugate(lemma, form, conj_type, reading)
    if not cls or not built or built != answer:
        return {}
    last = lemma[-1]
    if cls == "ichidan":
        ending = ICHIDAN_SUFFIX[form]
        kind_fr, kind_en = "un verbe ichidan", "an ichidan verb"
        return {"hint": f"{lemma} est {kind_fr} : on enlève る.", "hint_en": f"{lemma} is {kind_en}: drop る.",
                "rule": f"{lemma} → {lemma[:-1]} + {ending} = {built}.", "rule_en": f"{lemma} → {lemma[:-1]} + {ending} = {built}."}
    if cls == "suru":
        base = lemma[:-2]
        piece = built[len(base):]
        who = f"{lemma} se conjugue comme する" if base else "する est irrégulier"
        who_en = f"{lemma} conjugates like する" if base else "する is irregular"
        return {"hint": f"{who}.", "hint_en": f"{who_en}.",
                "rule": f"{lemma} → {built}{' (する → ' + piece + ')' if base else ''}.",
                "rule_en": f"{lemma} → {built}{' (する → ' + piece + ')' if base else ''}."}
    if cls == "kuru":
        return {"hint": "来る est irrégulier.", "hint_en": "来る is irregular.",
                "rule": f"来る → {built}.", "rule_en": f"来る → {built}."}
    stem = lemma[:-1]
    if form in TE_WORD:
        special = lemma in ("行く", "いく")
        ending = built[len(stem):]
        rule = f"{lemma} → {built} ({last} → {ending}{', exception de 行く' if special else ''})."
        rule_en = f"{lemma} → {built} ({last} → {ending}{', 行く is the exception' if special else ''})."
        return {"hint": f"{lemma} est un verbe godan en -{last}. Rappel : {TE_RULE['fr']}.",
                "hint_en": f"{lemma} is a godan verb in -{last}. Reminder: {TE_RULE['en']}.",
                "rule": rule, "rule_en": rule_en}
    kana = GODAN_ROWS[last][GODAN_ROW[form]]
    suffix = SUFFIX[form]
    if form == "negative" and lemma in ("ある", "有る"):
        return {"hint": "ある est une exception.", "hint_en": "ある is an exception.",
                "rule": "ある → ない (exception : pas de あらない).", "rule_en": "ある → ない (exception: no あらない)."}
    row_fr = {0: "a", 1: "i", 2: "e", 3: "o"}[GODAN_ROW[form]]
    extra_fr = " (う devient わ, pas あ)" if last == "う" and GODAN_ROW[form] == 0 else ""
    extra_en = " (う becomes わ, not あ)" if last == "う" and GODAN_ROW[form] == 0 else ""
    return {"hint": f"{lemma} est un verbe godan en -{last} : {last} passe en -{row_fr}{extra_fr}.",
            "hint_en": f"{lemma} is a godan verb in -{last}: {last} moves to the -{row_fr} row{extra_en}.",
            "rule": f"{lemma} → {stem}{kana} + {suffix} = {built}.", "rule_en": f"{lemma} → {stem}{kana} + {suffix} = {built}."}
