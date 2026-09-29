"""
The study programme: grammar topics in teaching order, from JLPT N5 to N4.

Each topic is an exercise recipe for make_exercises.py:
  - particles:    "targets" (the possible answers) + "pos" (required part of speech);
  - conjugations: "form" (see make_exercises.FORMS).

Progression (see store.topic_states):
  - a topic is "passed" when it is mastered (≥ 80 % right over its last 20 answers, at least 10 answers),
    fast-tracked (5 answers or more, all right), or marked « Je maîtrise déjà » in the app;
  - the daily session brings new exercises from the first MAX_CURRENT topics not passed yet;
    the following ones stay locked until one of them is passed. Reviews of every topic keep coming back.
"""

MAX_CURRENT = 2
MASTERY_WINDOW = 20      # answers considered to measure a topic
MASTERY_MIN = 10         # answers needed before a topic can be mastered
MASTERY_RATE = 0.8
FAST_TRACK_MIN = 5       # this many answers, all right → passed straight away

TOPICS = [
    # ---------------- N5 ----------------
    {"id": "masu", "level": "N5", "title": "Forme polie en ます", "form": "masu", "note": "Forme polie non passée : radical en -i + ます (書く → 書きます, 食べる → 食べます, する → します, 来る → 来ます). Négatif poli : ません ; passé poli : ました.", "title_en": "Polite form: ます", "note_en": "Non-past polite form: -i stem + ます (書く → 書きます, 食べる → 食べます, する → します, 来る → 来ます). Polite negative: ません; polite past: ました."},
    {"id": "wa-ga", "level": "N5", "title": "Particules は / が", "targets": "は,が", "pos": "係助詞,格助詞", "note": "は marque le thème (ce dont on parle, souvent déjà connu, ou un contraste). が marque le sujet grammatical : information nouvelle, mise en avant, réponse à « qui / quoi ? », sujet d'une subordonnée, ce qui existe avec ある / いる, et ce qu'on aime ou sait faire avec 好き / 上手 / 分かる.", "title_en": "Particles は / が", "note_en": "は marks the topic (what we talk about, often already known, or a contrast). が marks the grammatical subject: new information, emphasis, the answer to « who / what? », the subject of a subordinate clause, what exists with ある / いる, and what one likes or can do with 好き / 上手 / 分かる."},
    {"id": "wo-ga", "level": "N5", "title": "Particules を / が", "targets": "を,が", "pos": "格助詞", "note": "を marque l'objet direct d'un verbe d'action (パンを食べる). が remplace を avec les expressions d'état ou de capacité : 好き, 嫌い, 上手, 分かる, できる, 欲しい, forme potentielle (日本語が話せる).", "title_en": "Particles を / が", "note_en": "を marks the direct object of an action verb (パンを食べる). が replaces を with expressions of state or ability: 好き, 嫌い, 上手, 分かる, できる, 欲しい, potential form (日本語が話せる)."},
    {"id": "ni-de", "level": "N5", "title": "Particules に / で", "targets": "に,で", "pos": "格助詞", "note": "に : destination (学校に行く), moment précis (七時に), lieu d'existence avec いる / ある (部屋に猫がいる), destinataire (友達に書く), résultat (医者になる). で : lieu où se déroule une action (図書館で読む), moyen ou instrument (電車で, 箸で), cause (風邪で), langue (日本語で), limite ou total (三つで).", "title_en": "Particles に / で", "note_en": "に: destination (学校に行く), point in time (七時に), place of existence with いる / ある (部屋に猫がいる), recipient (友達に書く), result (医者になる). で: place where an action happens (図書館で読む), means or tool (電車で, 箸で), cause (風邪で), language (日本語で), limit or total (三つで)."},
    {"id": "negative", "level": "N5", "title": "Négatif en ない", "form": "negative", "note": "Négatif neutre : verbe en -a + ない pour les godan (書かない, 飲まない ; う → わ : 会わない), radical + ない pour les ichidan (食べない), しない, 来ない. ある → ない.", "title_en": "Negative: ない", "note_en": "Plain negative: godan verbs -a + ない (書かない, 飲まない; う → わ: 会わない), ichidan stem + ない (食べない), しない, 来ない. ある → ない."},
    {"id": "ni-e", "level": "N5", "title": "Particules に / へ", "targets": "に,へ", "pos": "格助詞", "note": "へ (prononcé « e ») insiste sur la direction du mouvement ; に marque la destination atteinte. Avec les verbes de déplacement les deux sont souvent possibles (日本に / へ行く) ; seul に s'emploie pour le lieu d'existence, le moment ou le destinataire.", "title_en": "Particles に / へ", "note_en": "へ (read « e ») stresses the direction of the movement; に marks the destination reached. With movement verbs both are often possible (日本に / へ行く); only に is used for a place of existence, a time or a recipient."},
    {"id": "past", "level": "N5", "title": "Passé en た", "form": "past", "note": "Passé neutre : comme la forme en て avec た / だ (書いた, 読んだ, 行った, 食べた, した, 来た). Poli : ました.", "title_en": "Past: た", "note_en": "Plain past: like the て-form with た / だ (書いた, 読んだ, 行った, 食べた, した, 来た). Polite: ました."},
    {"id": "wa-mo", "level": "N5", "title": "Particules は / も", "targets": "は,も", "pos": "係助詞", "note": "も signifie « aussi / même » et remplace は, が ou を (私も学生です). は pose le thème ou marque un contraste.", "title_en": "Particles は / も", "note_en": "も means « also / even » and replaces は, が or を (私も学生です). は sets the topic or marks a contrast."},
    {"id": "to-ya", "level": "N5", "title": "Particules と / や", "targets": "と,や", "pos": "格助詞,副助詞", "note": "と : « et » pour une liste complète (パンと卵), « avec » (友達と), citation (と言う). や : liste non exhaustive, « … entre autres » (パンや卵など).", "title_en": "Particles と / や", "note_en": "と: « and » for a complete list (パンと卵), « with » (友達と), quotation (と言う). や: incomplete list, « … among others » (パンや卵など)."},
    {"id": "te-form", "level": "N5", "title": "Forme en て", "form": "te", "note": "Forme en て : godan う/つ/る → って, む/ぶ/ぬ → んで, く → いて (sauf 行く → 行って), ぐ → いで, す → して ; ichidan → て ; する → して ; 来る → 来て. Sert à enchaîner des actions, demander (てください), l'action en cours (ている), la permission (てもいい).", "title_en": "て-form", "note_en": "て-form: godan う/つ/る → って, む/ぶ/ぬ → んで, く → いて (except 行く → 行って), ぐ → いで, す → して; ichidan → て; する → して; 来る → 来て. Used to chain actions, ask (てください), ongoing actions (ている), permission (てもいい)."},
    {"id": "word-order", "level": "N5", "title": "Ordre des mots", "order": True, "note": "Le prédicat (verbe, adjectif, nom + です) va toujours à la fin. Les autres groupes gardent leur particule, qui dit leur rôle : leur ordre est assez libre. L'ordre le plus courant : thème (は), moment, lieu, objet (を), verbe. Ce qui précise un nom (私の, この, 大きい) se place juste devant lui.", "title_en": "Word order", "note_en": "The predicate (verb, adjective, noun + です) always comes last. The other groups keep their particle, which tells their role: their order is fairly free. The most usual order: topic (は), time, place, object (を), verb. What describes a noun (私の, この, 大きい) comes right before it."},
    {"id": "kara-made", "level": "N5", "title": "Particules から / まで", "targets": "から,まで", "pos": "格助詞,副助詞", "note": "から : point de départ (« depuis, à partir de ») dans l'espace ou le temps, et après une phrase : la cause. まで : point d'arrivée, « jusqu'à ».", "title_en": "Particles から / まで", "note_en": "から: starting point (« from, since ») in space or time, and after a clause: the cause. まで: end point, « until / up to »."},
    {"id": "tai", "level": "N5", "title": "Envie : forme en たい", "form": "tai", "note": "Envie : radical en -i + たい (食べたい, 行きたい), se conjugue comme un adjectif en い (食べたくない, 食べたかった). Pour une autre personne : たがる.", "title_en": "Wanting: たい", "note_en": "Wanting to do: -i stem + たい (食べたい, 行きたい), conjugated like an い-adjective (食べたくない, 食べたかった). For someone else: たがる."},
    {"id": "relative-ga", "level": "N5", "title": "Relatives : は ou が", "targets": "は,が", "pos": "relative", "rules": True, "note": "Une proposition relative se place devant le nom qu'elle décrit, sans « qui / que » : 私が書いた手紙 = la lettre que j'ai écrite. Son sujet prend が (ou の : 私の書いた手紙), jamais は, qui reste le thème de toute la phrase (これは私が書いた手紙です).", "title_en": "Relative clauses: は or が", "note_en": "A relative clause comes before the noun it describes, with no « who / that »: 私が書いた手紙 = the letter I wrote. Its subject takes が (or の: 私の書いた手紙), never は, which stays the topic of the whole sentence (これは私が書いた手紙です)."},
    {"id": "relative-form", "level": "N5", "title": "Relatives : verbe devant le nom", "form": "relative", "rules": True, "note": "Devant un nom, le verbe est à la forme simple, jamais en ます : 昨日買った本 (le livre acheté hier), 隣に住んでいる人 (la personne qui habite à côté), 行かない人 (ceux qui n'y vont pas).", "title_en": "Relative clauses: the verb before the noun", "note_en": "Before a noun the verb is in the plain form, never ます: 昨日買った本 (the book I bought yesterday), 隣に住んでいる人 (the person who lives next door), 行かない人 (those who don't go)."},
    # ---------------- N4 ----------------
    {"id": "volitional", "level": "N4", "title": "Volitif en う / よう", "form": "volitional", "note": "Volitif : godan en -o + う (行こう, 飲もう), ichidan + よう (食べよう), しよう, 来よう. « Faisons… / je vais… » ; ようと思う = avoir l'intention de.", "title_en": "Volitional: う / よう", "note_en": "Volitional: godan -o + う (行こう, 飲もう), ichidan + よう (食べよう), しよう, 来よう. « Let's… / I'll… »; ようと思う = to intend to."},
    {"id": "nagara", "level": "N4", "title": "Simultanéité : ながら", "form": "nagara", "note": "ながら : radical en -i + ながら = deux actions simultanées du même sujet, l'action principale en dernier (音楽を聞きながら勉強する).", "title_en": "While: ながら", "note_en": "ながら: -i stem + ながら = two simultaneous actions by the same subject, the main one last (音楽を聞きながら勉強する)."},
    {"id": "ba", "level": "N4", "title": "Conditionnel en ば", "form": "ba", "note": "Conditionnel en ば : godan en -e + ば (行けば), ichidan + れば (食べれば), すれば, 来れば ; adjectifs : 高ければ. Condition générale ou hypothèse : « si… (alors) ».", "title_en": "Conditional: ば", "note_en": "ば conditional: godan -e + ば (行けば), ichidan + れば (食べれば), すれば, 来れば; adjectives: 高ければ. General condition or hypothesis: « if… (then) »."},
    {"id": "tara", "level": "N4", "title": "Conditionnel en たら", "form": "tara", "note": "Conditionnel en たら : passé + ら (行ったら, 食べたら). « Si / quand… » : condition ponctuelle, ou ce qui arrive une fois l'action faite ; très courant à l'oral.", "title_en": "Conditional: たら", "note_en": "たら conditional: past + ら (行ったら, 食べたら). « If / when… »: a one-off condition, or what happens once the action is done; very common in speech."},
    {"id": "noni-node", "level": "N4", "title": "のに / ので", "targets": "のに,ので", "pos": "接続助詞", "note": "ので : « comme, parce que », cause objective et polie. のに : « alors que, pourtant », résultat contraire à l'attente, souvent avec un regret.", "title_en": "のに / ので", "note_en": "ので: « because, since », objective and polite cause. のに: « although, even though », a result against expectations, often with regret."},
    {"id": "mae-ato", "level": "N4", "title": "Avant / après : 前に・後で", "form": "mae-ato", "rules": True, "note": "〜前に (avant de) : toujours la forme du dictionnaire, même au passé : 寝る前に歯を磨いた. 〜た後で (après avoir) : toujours le passé en た, même pour le futur : 食べた後で行きます.", "title_en": "Before / after: 前に・後で", "note_en": "〜前に (before): always the dictionary form, even in the past: 寝る前に歯を磨いた. 〜た後で (after): always the た past, even for the future: 食べた後で行きます."},
    {"id": "temo", "level": "N4", "title": "Même si : ても", "form": "temo", "rules": True, "note": "Forme en て + も = « même si, même en » : 雨が降っても行きます (j'irai même s'il pleut). Avec いい (〜てもいい), c'est une permission, un autre point.", "title_en": "Even if: ても", "note_en": "て-form + も = « even if »: 雨が降っても行きます (I'll go even if it rains). With いい (〜てもいい) it is a permission, another point."},
    {"id": "causative", "level": "N4", "title": "Causatif en せる / させる", "form": "causative", "note": "Causatif « faire / laisser faire » : godan en -a + せる (行かせる), ichidan + させる (食べさせる), させる, 来させる. La personne qu'on fait agir prend に ou を.", "title_en": "Causative: せる / させる", "note_en": "Causative « make / let someone do »: godan -a + せる (行かせる), ichidan + させる (食べさせる), させる, 来させる. The person made to act takes に or を."},
]

BY_ID = {t["id"]: t for t in TOPICS}
BY_TITLE = {t["title"]: t for t in TOPICS}
ORDER = {t["title"]: i for i, t in enumerate(TOPICS)}


def title(topic_title: str, lang: str = "fr") -> str:
    """The topic's title in the interface language (titles in French are the keys in the database)."""
    t = BY_TITLE.get(topic_title)
    if t and lang == "en":
        return t.get("title_en", topic_title)
    if lang == "en" and topic_title.startswith("JLPT "):
        import re
        return re.sub(r"\((lecture|écriture|vocabulaire|grammaire|ordre)\)",
                      lambda m: "(" + JLPT_EN[m.group(1)] + ")", topic_title)
    return topic_title


def note(topic: dict, lang: str = "fr") -> str:
    return topic.get("note_en", topic["note"]) if lang == "en" else topic["note"]


JLPT_EN = {"lecture": "reading", "écriture": "writing", "vocabulaire": "vocabulary", "grammaire": "grammar",
           "ordre": "word order"}


def kind(topic: dict) -> str:
    if topic.get("order"):
        return "order"
    return "conjugation" if "form" in topic else "particle"


def is_particle_topic(title: str) -> bool:
    t = BY_TITLE.get(title)
    return bool(t) and "targets" in t
