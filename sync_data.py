"""Fetch only public official results. Merge successes; never erase prior draws on error."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from takarakuji import OfficialClient, GAMES, REGIONS, parse_digital, parse_regional


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
