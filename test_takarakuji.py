import copy
import itertools
import json
from pathlib import Path
import unittest
import takarakuji as t

F=json.loads(Path(__file__).with_name('fixtures.json').read_text(encoding='utf-8'))
REGIONAL_IDS={'tokyo':2661,'kct':2708,'kinki':2845,'nishinihon':2531,'chiiki':441}

def digital(game):
    return t.parse_digital(F[game],game,'fixture')

class CheckerTests(unittest.TestCase):
    def test_all_real_digital_pages(self):
        for g in t.GAMES:
            with self.subTest(game=g):
                draws=digital(g)
                self.assertTrue(draws)
                self.assertTrue(all(d['game']==g for d in draws.values()))

    def test_all_real_regional_pages(self):
        for g,n in REGIONAL_IDS.items():
            with self.subTest(game=g):
                d=t.parse_regional(F[g],g,n,'fixture')
                first=next(r for r in d['rules'] if r['grade']=='1等')
                result=t.check_ticket({'game':g,'draw':n,'group':first['group_id'],'number':first['digits']},d)
                self.assertTrue(any(r['grade']=='1等' for r in result['matches']))

    def test_real_0691_and_march(self):
        d=digital('loto7')[t.draw_id('0691')]
        self.assertEqual(d['date'],'2026-08-21')
        self.assertEqual(d['numbers'],[8,10,20,22,23,27,37])
        self.assertEqual(d['bonus'],[2,9])
        r=t.parse_regional(F['kct'],'kct',2708,'fixture')
        self.assertIn('3月',r['抽せん日'])

    def test_loto7_sixth_prize_needs_bonus(self):
        d=digital('loto7')[691]
        for picks,expected in [([8,10,20,1,3,4,5],None),([8,10,20,2,3,4,5],'6等'),
                               ([8,10,20,2,9,4,5],'6等'),([8,10,20,22,3,4,5],'5等')]:
            with self.subTest(picks=picks):
                r=t.check_ticket({'game':'loto7','draw':'0691','numbers':picks},d)
                self.assertEqual(r['grade'],expected)

    def test_loto6_bonus_only_changes_second(self):
        d=digital('loto6')[2137]
        cases=[([4,8,10,25,28,33],'1等'),([4,8,10,25,28,9],'2等'),
               ([4,8,10,25,28,1],'3等'),([4,8,10,25,9,1],'4等'),
               ([4,8,10,9,1,2],'5等'),([4,8,9,1,2,3],None)]
        for picks,expected in cases:
            with self.subTest(picks=picks):
                self.assertEqual(t.check_ticket({'game':'loto6','draw':2137,'numbers':picks},d)['grade'],expected)

    def test_miniloto_ranks(self):
        d=next(iter(digital('miniloto').values()))
        nums,bonus=d['numbers'],d['bonus'][0]
        other=[n for n in range(1,32) if n not in nums+[bonus]]
        for picks,rank in [(nums,'1等'),(nums[:4]+[bonus],'2等'),(nums[:4]+other[:1],'3等'),
                           (nums[:3]+other[:2],'4等'),(nums[:2]+[bonus]+other[:2],None)]:
            self.assertEqual(t.check_ticket({'game':'miniloto','draw':d['draw'],'numbers':picks},d)['grade'],rank)

    def test_bingo_all_256_hit_patterns(self):
        d=digital('bingo5')[488]
        histogram=CounterForTest()
        for mask in itertools.product([False,True],repeat=8):
            pick=[v if hit else 5*i+1+(v-5*i)%5 for i,(v,hit) in enumerate(zip(d['numbers'],mask))]
            grid=list(mask[:4])+[True]+list(mask[4:])
            expected=sum(all(grid[3*r+c] for c in range(3)) for r in range(3))
            expected+=sum(all(grid[3*r+c] for r in range(3)) for c in range(3))
            expected+=int(all(grid[4*i] for i in range(3)))+int(all(grid[2+2*i] for i in range(3)))
            r=t.check_ticket({'game':'bingo5','draw':488,'numbers':pick},d)
            self.assertEqual(r['lines'],expected)
            histogram.add(expected)
        self.assertNotIn(7,histogram.values)
        self.assertIn(8,histogram.values)

    def test_numbers_all_modes_duplicate_digits(self):
        d=digital('numbers3')[7072]  # 229
        cases=[('straight','229',99300),('straight','292',0),('box','292',33100),
               ('set','229',66200),('set','922',16500),('mini','29',9900),('box','299',0)]
        for mode,number,money in cases:
            with self.subTest(mode=mode,number=number):
                r=t.check_ticket({'game':'numbers3','draw':7072,'number':number,'mode':mode},d)
                self.assertEqual(r['yen_per_ticket'],money)

    def test_leading_zero_and_invalid_modes(self):
        d=copy.deepcopy(digital('numbers3')[7072]);d['number']='007'
        self.assertEqual(t.check_ticket({'game':'numbers3','draw':7072,'number':'070','mode':'box'},d)['status'],'WIN')
        for number,mode in [(7,'straight'),('07','straight'),('111','box'),('111','set')]:
            with self.assertRaises(t.CheckError):
                t.check_ticket({'game':'numbers3','draw':7072,'number':number,'mode':mode},d)
        d4=next(iter(digital('numbers4').values()))
        with self.assertRaises(t.CheckError):
            t.check_ticket({'game':'numbers4','draw':d4['draw'],'number':'23','mode':'mini'},d4)

    def test_regional_adjacent_different_and_suffix(self):
        d=t.parse_regional(F['tokyo'],'tokyo',2661,'fixture')
        for group,number,grade in [(5,'178079','1等の前後賞'),(5,'178081','1等の前後賞'),
                                    (6,'178080','1等の組違い賞'),(5,'100248','2等'),(5,'100614','3等')]:
            r=t.check_ticket({'game':'tokyo','draw':2661,'group':group,'number':number},d)
            self.assertIn(grade,[m['grade'] for m in r['matches']])
        r=t.check_ticket({'game':'tokyo','draw':2661,'group':6,'number':'178079'},d)
        self.assertNotIn('1等の前後賞',[m['grade'] for m in r['matches']])

    def test_wrong_draw_is_not_checked(self):
        with self.assertRaises(t.CheckError):
            t.check_ticket({'game':'loto7','draw':690,'numbers':[1,2,3,4,5,6,7]},digital('loto7')[691])

    def test_corrupt_or_empty_results_fail_closed(self):
        with self.assertRaises(t.CheckError): t.parse_digital({'tables':[]},'loto6','fixture')
        p=copy.deepcopy(F['loto6']);p['tables']=p['tables'][:1];p['tables'][0][2][1]['text']='99'
        with self.assertRaises(t.CheckError): t.parse_digital(p,'loto6','fixture')
        p=copy.deepcopy(F['tokyo']);p['tables'][0][1][3]['text']='不明な特別賞'
        with self.assertRaises(t.CheckError): t.parse_regional(p,'tokyo',2661,'fixture')

    def test_invalid_picks_and_amounts(self):
        for picks in [[1,1,2,3,4,5],[0,2,3,4,5,6],[1,2,3,4,5,44]]:
            with self.assertRaises(t.CheckError): t.validate_numbers('loto6',picks)
        self.assertEqual(t.yen('1億2500万円'),125000000)
        self.assertIsNone(t.yen('該当なし'))
        with self.assertRaises(t.CheckError): t.yen('未発表')

    def test_historical_resolver_uses_official_links(self):
        # Fake only transport; use real parsed pages and the inspected official link.
        client=t.OfficialClient.__new__(t.OfficialClient)
        game='loto7'
        current=client.digital_url(game)
        old=client.digital_url(game,'2026-08')
        new=copy.deepcopy(F['loto7'])
        for table in new['tables']:
            for row in table:
                for cell in row:
                    cell['text']=cell['text'].replace('第691回','第701回').replace('第692回','第702回')
                    cell['text']=cell['text'].replace('第690回','第700回').replace('第689回','第699回')
        archive=f'{t.BASE}/takarakuji/check/loto/backnumber/index.html'
        pages={current:new,archive:{'links':[{'href':old}]},old:F['loto7']}
        client.get=lambda url,kind='digital':pages[url]
        self.assertEqual(client.digital(game,691)['date'],'2026-08-21')
        with self.assertRaises(t.CheckError): client.digital(game,9999)

class CounterForTest:
    def __init__(self): self.values=set()
    def add(self,x): self.values.add(x)

if __name__=='__main__': unittest.main()
