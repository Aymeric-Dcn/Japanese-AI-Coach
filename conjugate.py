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
                       "passive": "られる"}[form]
    if cls == "suru":
        stem = lemma[:-2]
        return stem + {"masu": "します", "te": "して", "past": "した", "negative": "しない", "tai": "したい",
                       "volitional": "しよう", "ba": "すれば", "tara": "したら", "causative": "させる",
                       "passive": "される"}[form]
    if cls == "kuru":
        k = "来" if lemma.startswith("来") else ""
        stem = lemma[:-2] if not k else lemma[:-2]
        table = {"masu": ("き", "ます"), "te": ("き", "て"), "past": ("き", "た"), "negative": ("こ", "ない"),
                 "tai": ("き", "たい"), "volitional": ("こ", "よう"), "ba": ("く", "れば"), "tara": ("き", "たら"),
                 "causative": ("こ", "させる"), "passive": ("こ", "られる")}
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
                       "ba": e + "ば", "causative": a + "せる", "passive": a + "れる"}[form]
    return ""


def forms(lemma: str, conj_type: str = "", reading: str = "") -> dict:
    return {f: conjugate(lemma, f, conj_type, reading) for f in FORMS}
