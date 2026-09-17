"""Check browser checker output against the Python implementation."""
import json
from pathlib import Path
import subprocess
import tempfile

import takarakuji as py

FIXTURES = json.loads(Path('fixtures.json').read_text(encoding='utf-8'))
REGIONAL = {'tokyo': 2661, 'kct': 2708, 'kinki': 2845,
            'nishinihon': 2531, 'chiiki': 441}


def draw(game, number=None):
    if game in py.GAMES:
        rows = py.parse_digital(FIXTURES[game], game, 'https://www.mizuhobank.co.jp/')
        return rows[number] if number else next(iter(rows.values()))
    return py.parse_regional(FIXTURES[game], game, REGIONAL[game],
                             'https://www.mizuhobank.co.jp/')


draws = [draw('loto7', 691), draw('loto6', 2137), draw('miniloto'),
         draw('bingo5', 488), draw('numbers3', 7072), draw('numbers4')]
draws += [draw(game) for game in REGIONAL]
draws.append({'game':'zenkoku','draw':1116,'date':'2026-08-12','source':'https://www.mizuhobank.co.jp/',
              'rules':[{'grade':'1等','yen':30000000,'group':'組下1ケタ8組','number':'143069番',
                        'kind':'group_suffix','digits':'143069','group_digits':'8'},
                       {'grade':'1等の前後賞','yen':10000000,'group':'','number':'1等の前後の番号',
                        'kind':'adjacent'}]})
first_regional = next(r for r in draws[6]['rules']
                      if r['grade'] == '1等' and r['kind'] == 'exact')
cases = [
    {'game': 'loto7', 'draw': '第0691回', 'numbers': [8, 10, 20, 22, 23, 27, 37]},
    {'game': 'loto7', 'draw': 691, 'numbers': [8, 10, 20, 2, 3, 4, 5]},
    {'game': 'loto6', 'draw': 2137, 'numbers': [4, 8, 10, 25, 28, 9]},
    {'game': 'miniloto', 'draw': draws[2]['draw'], 'numbers': draws[2]['numbers']},
    {'game': 'bingo5', 'draw': 488, 'numbers': draws[3]['numbers']},
    {'game': 'numbers3', 'draw': 7072, 'number': '229', 'mode': 'set'},
    {'game': 'numbers3', 'draw': 7072, 'number': '29', 'mode': 'mini'},
    {'game': 'numbers4', 'draw': draws[5]['draw'], 'number': draws[5]['number'], 'mode': 'straight'},
    {'game': 'tokyo', 'draw': REGIONAL['tokyo'], 'group': str(first_regional['group_id']),
     'number': first_regional['digits']},
    {'game': '全国通常宝くじ', 'draw': 1116, 'group': '18', 'number': '143068'},
    {'game': 'loto7', 'draw': 999999, 'numbers': [1, 2, 3, 4, 5, 6, 7]},
]

expected = []
for index, ticket in enumerate(cases):
    try:
        selected = next(d for d in draws
                        if d['game'] == py.game_name(ticket['game'])
                        and d['draw'] == py.draw_id(ticket['draw']))
        expected.append({'index': index, **py.check_ticket(ticket, selected)})
    except (StopIteration, py.CheckError, KeyError, TypeError, ValueError) as exc:
        expected.append({'index': index, 'status': 'UNKNOWN', 'error': str(exc)})

with tempfile.TemporaryDirectory() as directory:
    payload = Path(directory, 'payload.json')
    payload.write_text(json.dumps({'tickets': cases, 'draws': draws}, ensure_ascii=False),
                       encoding='utf-8')
    script = """
      import fs from 'node:fs';
      import {checkBatch} from './web/checker.js';
      const data=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
      process.stdout.write(JSON.stringify(checkBatch(data.tickets,data.draws)));
    """
    actual = json.loads(subprocess.check_output(
        ['node', '--input-type=module', '-e', script, str(payload)], text=True))

for want, got in zip(expected, actual):
    assert want['status'] == got['status'], (want, got)
    if want['status'] != 'UNKNOWN':
        for key in ('game', 'draw', 'grade', 'yen_per_ticket',
                    'total_yen', 'matches', 'lines'):
            assert want.get(key) == got.get(key), (key, want, got)

print(f'Python/JavaScript parity: {len(cases)} cases passed')
