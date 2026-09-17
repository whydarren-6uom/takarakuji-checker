"""Fetch only public official results. Merge successes; never erase prior draws on error."""
import argparse
import certifi
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import ssl
import sys
import unicodedata
from urllib.request import Request, urlopen
from takarakuji import (OfficialClient, GAMES, REGIONS, parse_digital,
                        parse_regional, validate_numbers)

OFFICIAL = 'https://www.mizuhobank.co.jp'
CSV_FAMILIES = {
    'loto7': ('/retail/takarakuji/loto/loto7/csv/loto7.csv', 'A103', 4),
    'loto6': ('/retail/takarakuji/loto/loto6/csv/loto6.csv', 'A102', 4),
    'miniloto': ('/retail/takarakuji/loto/miniloto/csv/miniloto.csv', 'A101', 4),
    'bingo5': ('/retail/takarakuji/bingo/bingo5/csv/bingo5.csv', 'A104', 4),
    'numbers': ('/retail/takarakuji/numbers/csv/numbers.csv', 'A100', 4),
}


def _norm(value):
    return unicodedata.normalize('NFKC', value).strip()


def _date(value):
    match = re.fullmatch(r'令和(\d+)年(\d+)月(\d+)日', _norm(value))
    if not match:
        raise ValueError(f'无法识别官方 CSV 日期：{value!r}')
    return f'{2018 + int(match[1]):04}-{int(match[2]):02}-{int(match[3]):02}'


def _yen(value):
    value = _norm(value).replace(',', '')
    if value == '該当なし':
        return None
    if not re.fullmatch(r'\d+円', value):
        raise ValueError(f'无法识别官方 CSV 奖金：{value!r}')
    return int(value[:-1])


def parse_official_csv(text, source):
    """Parse one official per-draw CSV after transport-level validation."""
    rows = [[_norm(cell) for cell in row]
            for row in csv.reader(text.splitlines()) if row]
    if len(rows) < 5 or not re.fullmatch(r'A\d{2}', rows[0][0]):
        raise ValueError('官方 CSV header 异常')
    header = rows[1]
    match = re.fullmatch(r'第0*(\d+)回(ロト7|ロト6|ミニロト|ビンゴ5|ナンバーズ)', header[0])
    if not match or len(header) < 3:
        raise ValueError('官方 CSV 期号 header 异常')
    number, label = int(match[1]), match[2]
    date = _date(header[2])
    labels = {'ロト7': 'loto7', 'ロト6': 'loto6', 'ミニロト': 'miniloto',
              'ビンゴ5': 'bingo5'}
    if label == 'ナンバーズ':
        results = []
        for game, heading, width in [('numbers3', 'ナンバーズ3抽せん数字', 3),
                                     ('numbers4', 'ナンバーズ4抽せん数字', 4)]:
            starts = [i for i, row in enumerate(rows) if row[0] == heading]
            if len(starts) != 1 or len(rows[starts[0]]) != 2:
                raise ValueError(f'{heading} 缺失或重复')
            start = starts[0]
            end = next((i for i in range(start + 1, len(rows))
                        if rows[i][0].endswith('抽せん数字')), len(rows))
            prizes = {}
            keys = {'ストレート': 'straight', 'ボックス': 'box',
                    'セット(ストレート)': 'set_straight',
                    'セット(ボックス)': 'set_box', 'ミニ': 'mini'}
            for row in rows[start + 1:end]:
                key = keys.get(row[0])
                if key and key not in prizes and not (key == 'mini' and game == 'numbers4'):
                    prizes[key] = _yen(row[-1])
            needed = {'straight', 'box', 'set_straight', 'set_box'}
            if game == 'numbers3':
                needed.add('mini')
            if prizes.keys() < needed:
                raise ValueError(f'{heading} 奖金表缺失')
            winning = rows[start][1]
            if not re.fullmatch(rf'\d{{{width}}}', winning):
                raise ValueError(f'{heading} 号码异常')
            results.append({'game': game, 'draw': number, 'date': date,
                            'source': source, 'prizes': prizes, 'number': winning})
        return results
    game = labels.get(label)
    if not game:
        raise ValueError('官方 CSV 彩票类别异常')
    number_rows = [row for row in rows if row[0] in ('本数字', 'ビンゴ5抽せん数字')]
    if len(number_rows) != 1:
        raise ValueError('官方 CSV 开奖号码缺失或重复')
    row = number_rows[0]
    if game == 'bingo5':
        main, bonus = [int(x) for x in row[1:]], []
    else:
        if row.count('ボーナス数字') != 1:
            raise ValueError('官方 CSV bonus 分隔符异常')
        split = row.index('ボーナス数字')
        main = [int(x) for x in row[1:split]]
        bonus = [int(x) for x in row[split + 1:]]
    validate_numbers(game, main, bonus)
    prizes = {}
    for prize_row in rows:
        if re.fullmatch(r'[1-7]等', prize_row[0]) and prize_row[0] not in prizes:
            prizes[prize_row[0]] = _yen(prize_row[-1])
    needed = {'loto6': 5, 'loto7': 6, 'miniloto': 4, 'bingo5': 7}[game]
    if prizes.keys() < {f'{i}等' for i in range(1, needed + 1)}:
        raise ValueError('官方 CSV 奖金表缺失')
    return [{'game': game, 'draw': number, 'date': date, 'source': source,
             'prizes': prizes, 'numbers': main, 'bonus': bonus}]


def fetch_text_gateway(source):
    """Read a public Mizuho CSV through a text gateway when Akamai blocks Actions."""
    if not source.startswith(OFFICIAL + '/retail/takarakuji/') or not source.lower().endswith('.csv'):
        raise ValueError('不允许的 CSV 来源')
    gateway = 'https://r.jina.ai/http://' + source.removeprefix('https://')
    request = Request(gateway, headers={'User-Agent': 'takarakuji-checker/1.0'})
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=30, context=context) as response:
        body = response.read().decode('utf-8')
    declared = source.replace('https://', 'http://')
    if f'URL Source: {declared}' not in body or 'Markdown Content:' not in body:
        raise ValueError('CSV text gateway 没有返回预期的官方来源')
    content = body.split('Markdown Content:', 1)[1].strip()
    if 'お探しのページが見つかりませんでした' in content:
        raise ValueError('官方 CSV 不存在')
    return content


def gateway_entries(manifest_text, family):
    prefix = CSV_FAMILIES[family][1]
    entries = []
    for line in manifest_text.splitlines():
        match = re.match(r'第0*(\d+)回', _norm(line))
        if match:
            number = int(match[1])
            entries.append((number, f'{prefix}{number:04}.CSV'))
    if not entries or entries != sorted(set(entries), reverse=True):
        raise ValueError('官方 CSV 索引缺失、重复或顺序异常')
    return entries


def sync(path, full=False):
    old = json.loads(path.read_text()) if path.exists() else {'draws': [], 'coverage': {}}
    draws = {(d['game'], d['draw']): d for d in old['draws']}
    coverage = old.get('coverage', {})
    errors, successes = [], []
    now = datetime.now(timezone.utc).isoformat()
    with OfficialClient(refresh=True, show_endpoints=True, cache_dir='.cache/official') as c:
        def save(records, url):
            for d in records:
                d['fetched_at'] = now
                draws[d['game'], d['draw']] = d
            coverage[url] = {'last_success': now, 'count': len(records)}
            successes.append(url)
        def attempt(url, fn):
            try:
                records = fn()
                if not records:
                    raise ValueError('官方页面未包含可识别的开奖数据')
                save(records, url)
            except Exception as e:
                errors.append({'source': url, 'error': str(e)[:700]})
                print(f'FAILED {url}: {e}', file=sys.stderr)
        for game in GAMES:
            url = c.digital_url(game)
            attempt(url, lambda g=game, u=url: list(parse_digital(c.get(u), g, u).values()))
            if full:
                archive = f'https://www.mizuhobank.co.jp/takarakuji/check/{GAMES[game][0]}/backnumber/index.html'
                try:
                    links = c.get(archive, 'links')['links']
                    urls = list(dict.fromkeys(l['href'] for l in links if f'/{game}/index.html?year=' in l['href']))
                    if not urls: raise ValueError('未找到 A表历史月份链接')
                    for u in urls:
                        attempt(u, lambda g=game, u=u: list(parse_digital(c.get(u), g, u).values()))
                except Exception as e:
                    errors.append({'source': archive, 'error': str(e)[:700]})
        for game in REGIONS:
            listing = f'https://www.mizuhobank.co.jp/takarakuji/check/tsujyo/top.html?type={game}'
            try:
                entries = c.regional_list(game)
                if not entries: raise ValueError('未找到地域历史期次')
                for entry in entries:
                    if not full and (game,entry['draw']) in draws: continue
                    def regional(e=entry, g=game):
                        d = parse_regional(c.get(e['source'], 'regional'), g, e['draw'], e['source'])
                        d['date'] = e['date']
                        return [d]
                    attempt(entry['source'], regional)
            except Exception as e:
                errors.append({'source': listing, 'error': str(e)[:700]})
    # GitHub-hosted runners are currently rejected by Mizuho's Akamai edge.
    # The fallback transports the same public official CSV through r.jina.ai.
    # Both the declared source and every CSV field are validated before merge.
    for family, (manifest_path, _prefix, _width) in CSV_FAMILIES.items():
        manifest_source = OFFICIAL + manifest_path
        try:
            manifest = fetch_text_gateway(manifest_source)
            entries = gateway_entries(manifest, family)
            games = ('numbers3', 'numbers4') if family == 'numbers' else (family,)
            latest_stored = max((number for game, number in draws if game in games), default=0)
            if entries[0][0] < latest_stored:
                raise ValueError('CSV 索引比已保存数据更旧，拒绝降级')
            refreshed = 0
            for number, filename in entries[:40 if full else 5]:
                if all((game, number) in draws for game in games):
                    continue
                source = manifest_source.rsplit('/', 1)[0] + '/' + filename
                records = parse_official_csv(fetch_text_gateway(source), source)
                if {record['game'] for record in records} != set(games):
                    raise ValueError('CSV 内容与索引类别不一致')
                save(records, source)
                refreshed += len(records)
            coverage[manifest_source] = {
                'last_success': now, 'count': refreshed,
                'transport': 'r.jina.ai text gateway',
            }
            successes.append(manifest_source)
        except Exception as e:
            errors.append({'source': manifest_source, 'error': str(e)[:700]})
            print(f'FAILED CSV fallback {manifest_source}: {e}', file=sys.stderr)
    result = {**old, 'schema_version':1, 'last_attempt':now,
              'last_success':now if successes else old.get('last_success'),
              'last_complete_success':now if successes and not errors else old.get('last_complete_success'),
              'sync_status':'ok' if not errors and successes else 'partial' if successes else 'failed',
              'errors':errors, 'coverage':coverage,
              'draws': sorted(draws.values(),key=lambda d:(d['game'],d['draw']))}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
    print(f'{len(result["draws"])} draws, {len(successes)} pages refreshed, {len(errors)} errors')
    return 0 if successes else 1

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--full',action='store_true');p.add_argument('--output',type=Path,default=Path('web/data/results.json'));a=p.parse_args()
    sys.exit(sync(a.output,a.full))
