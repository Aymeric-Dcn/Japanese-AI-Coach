"""
Regression tests of the rules that write exercises without a model (no SudachiPy, no bank.db needed: the
analyzer's tokens of a few Tatoeba sentences are kept in tests/sentences.json).

    python -m unittest discover tests
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coach import words  # noqa: E402
from coach.exercises import clauses, conjugate, word_order  # noqa: E402

S = json.loads((Path(__file__).parent / "sentences.json").read_text(encoding="utf-8"))


def text(tokens, span):
    return "".join(t[0] for t in tokens[span[0]:span[1]])


class Conjugation(unittest.TestCase):
    def test_te_past_negative(self):
        cases = {("書く", "五段-カ行"): ("書いて", "書いた", "書かない"),
                 ("行く", "五段-カ行"): ("行って", "行った", "行かない"),   # the exception of 行く
                 ("食べる", "下一段-バ行"): ("食べて", "食べた", "食べない"),
                 ("する", "サ行変格"): ("して", "した", "しない"),
                 ("来る", "カ行変格"): ("来て", "来た", "来ない")}
        for (verb, conj), (te, past, neg) in cases.items():
            f = conjugate.forms(verb, conj)
            self.assertEqual((f["te"], f["past"], f["negative"]), (te, past, neg), verb)


class Clauses(unittest.TestCase):
    def test_relative(self):
        t = S["relative"]["tokens"]                      # 拾った者が持ち主。
        spans = clauses.relative_blanks(t)
        self.assertEqual(text(t, spans[0]), "拾った")
        self.assertIn("forme simple", clauses.notes("relative", t, spans[0])["hint"])

    def test_mae(self):
        t = S["mae-ato"]["tokens"]                       # 飛ぶ前に見よ。
        self.assertEqual(text(t, clauses.mae_ato_blanks(t)[0]), "飛ぶ")

    def test_temo(self):
        t = S["temo"]["tokens"]                          # 望んでも無駄だ。
        self.assertEqual(text(t, clauses.temo_blanks(t)[0]), "望んでも")

    def test_not_temo(self):
        self.assertEqual(clauses.temo_blanks(S["totemo"]["tokens"]), [])    # とっても = とても
        self.assertEqual(clauses.temo_blanks(S["temo_ii"]["tokens"]), [])   # 〜てもいい: permission


class WordOrder(unittest.TestCase):
    def test_tiles(self):
        o = S["order"]                                   # 彼は時々変です。
        ex = word_order.build(o["id"], o["jp"], o["fr"], o["en"], o["tokens"])
        self.assertEqual(ex["tiles"][-1], "変です")       # the predicate stays last
        self.assertEqual("".join(ex["tiles"]) + ex["ending"], o["jp"])


class Words(unittest.TestCase):
    def test_segment_gives_the_sentence_back(self):
        for item in S.values():
            w = words.segment(item["tokens"])
            self.assertTrue(words.matches(w, item["jp"]), item["jp"])
            self.assertTrue(words.has_readings(w))

    def test_conjugated_verb_in_one_piece(self):
        w = words.segment(S["conj"]["tokens"])           # やむなく学校を辞めさせられた。
        self.assertIn(["辞めさせられた", "辞める", "やめさせられた"], w)
        self.assertIn(["学校", "学校", "がっこう"], w)

    def test_no_reading_on_numbers(self):
        w = words.segment(S["number"]["tokens"])         # まだ13歳です。
        self.assertTrue(all(not x[2] for x in w if "13" in x[0]))

    def test_reading_in(self):
        w = words.segment(S["conj"]["tokens"])
        self.assertEqual(words.reading_in(w, S["conj"]["jp"], "学校を"), "がっこうを")
        self.assertEqual(words.reading_in(w, S["conj"]["jp"], "辞め"), "")   # cuts a word with kanji

    def test_choice_readings(self):
        self.assertEqual(words.choice_readings(["座った", "座ります", "座ろう", "座って"], "座って", "すわって",
                                               lambda w: ""),
                         ["すわった", "すわります", "すわろう", "すわって"])
        self.assertEqual(words.choice_readings(["で", "に"], "に", "", lambda w: ""), ["", ""])

    def test_exam_furigana(self):
        w = [["彼", "彼", "かれ"], ["は", "", ""], ["日本", "日本", "にほん"]]
        levels = {"彼": {"j": 3}, "日": {"j": 5}, "本": {"j": 5}}
        self.assertEqual(words.exam_furigana(w, "N4", levels), [0])   # 彼 is N3: above an N4 question


if __name__ == "__main__":
    unittest.main()
