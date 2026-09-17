import unittest

from sync_data import gateway_entries, parse_official_csv


class CsvFallbackTests(unittest.TestCase):
    def test_loto7_official_csv(self):
        text = """A53
第0694回ロト７,数字選択式全国自治宝くじ,令和8年9月11日,東京 宝くじドリーム館
支払期間,令和8年9月12日から令和9年9月11日まで
本数字,03,13,24,26,30,31,36,ボーナス数字,23,34
１等,1口,1200000000円
２等,7口,10624700円
３等,138口,620800円
４等,7244口,7100円
５等,122297口,1400円
６等,203095口,1000円
"""
        draw = parse_official_csv(text, 'https://www.mizuhobank.co.jp/example.CSV')[0]
        self.assertEqual(draw['draw'], 694)
        self.assertEqual(draw['date'], '2026-09-11')
        self.assertEqual(draw['numbers'], [3, 13, 24, 26, 30, 31, 36])
        self.assertEqual(draw['bonus'], [23, 34])
        self.assertEqual(draw['prizes']['2等'], 10624700)

    def test_numbers_combined_csv(self):
        text = """A50
第7073回ナンバーズ,数字選択式全国自治宝くじ,令和8年9月17日,東京 宝くじドリーム館
支払期間,令和8年9月18日から令和9年9月17日まで
ナンバーズ３抽せん数字,188
ストレート,188,62口,87100円
ボックス,253口,29000円
セット（ストレート）,162口,58000円
セット（ボックス）,419口,14500円
ミニ,下２ケタ,468口,8700円
ナンバーズ４抽せん数字,6916
ストレート,6916,18口,986400円
ボックス,153口,82200円
セット（ストレート）,51口,534300円
セット（ボックス）,680口,41100円
"""
        draws = parse_official_csv(text, 'https://www.mizuhobank.co.jp/example.CSV')
        self.assertEqual([(d['game'], d['number']) for d in draws],
                         [('numbers3', '188'), ('numbers4', '6916')])
        self.assertEqual(draws[0]['prizes']['mini'], 8700)

    def test_manifest_is_strictly_newest_first(self):
        text = "第0694回ロト７,foo\n第0693回ロト７,foo"
        self.assertEqual(gateway_entries(text, 'loto7'),
                         [(694, 'A1030694.CSV'), (693, 'A1030693.CSV')])
        with self.assertRaises(ValueError):
            gateway_entries("第0693回\n第0694回", 'loto7')


if __name__ == '__main__':
    unittest.main()
