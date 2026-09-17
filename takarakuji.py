#!/usr/bin/env python3
"""Read-only Mizuho lottery checker. Python 3.10+. See README.md.

pip install playwright
python -m playwright install chromium
python takarakuji.py check --game loto7 --draw 0691 --numbers '1 2 3 4 5 6 7'

No account, ticket upload, purchase, or prediction. Numbers stay on this machine.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urljoin, urlparse

BASE = 'https://www.mizuhobank.co.jp'
REGIONS = {
    'tokyo': '東京都宝くじ', 'kct': '関東・中部・東北自治宝くじ',
    'kinki': '近畿宝くじ', 'nishinihon': '西日本宝くじ',
    'chiiki': '地域医療等振興自治宝くじ',
}
GAMES = {'loto6': ('loto', 6, 43, 1), 'loto7': ('loto', 7, 37, 2),
         'miniloto': ('loto', 5, 31, 1), 'bingo5': ('bingo', 8, 40, 0),
         'numbers3': ('numbers', 3, 9, 0), 'numbers4': ('numbers', 4, 9, 0)}
ALIASES = {'ロト6':'loto6', 'ロト7':'loto7', 'ミニロト':'miniloto',
           'ビンゴ5':'bingo5', 'ナンバーズ3':'numbers3', 'ナンバーズ4':'numbers4',
           **{v:k for k,v in REGIONS.items()}}
MODES = {'straight':'ストレート', 'box':'ボックス',
         'set_straight':'セット(ストレート)', 'set_box':'セット(ボックス)', 'mini':'ミニ'}

# DOM extraction only; source URLs and full request URLs never include ticket numbers.
EXTRACT = r'''() => ({
 title: document.querySelector('main')?.innerText || document.body.innerText,
 tables: Array.from(document.querySelectorAll('main table'))
   .filter(t => !t.parentElement.closest('table'))
   .map(t => Array.from(t.rows).map(r => Array.from(r.cells).map(c =>
     ({text:c.innerText, rs:c.rowSpan, cs:c.colSpan})))),
 links: Array.from(document.querySelectorAll('main a[href]')).map(a => ({
   text:a.innerText, href:a.href, row:a.closest('tr')?.innerText || ''
 }))
})'''

class CheckError(Exception):
    pass

def norm(x):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(x)))

def game_name(x):
    x = norm(x).lower()
    return ALIASES.get(x, x)

def draw_id(x):
    m = re.fullmatch(r'(?:第)?0*([0-9]+)(?:回)?', norm(x))
    if not m or int(m[1]) < 1:
        raise CheckError(f'期号无效：{x!r}')
    return int(m[1])

def yen(x):
    x = norm(x).replace(',', '')
    if x in ('該当なし', '-', '—', ''):
        return None
    if not re.fullmatch(r'(?:\d+億)?(?:\d+万)?(?:\d+)?円', x):
        raise CheckError(f'无法识别奖金：{x!r}')
    total = 0
    x = x[:-1]
    for unit, scale in [('億', 100000000), ('万', 10000)]:
        if unit in x:
            n, x = x.split(unit)
            total += int(n)*scale
    return total + (int(x) if x else 0)

def values(x):
    if isinstance(x, list):
        if any(type(v) is not int for v in x):
            raise CheckError('numbers array 只能包含 integers')
        return x
    s = unicodedata.normalize('NFKC', str(x)).strip()
    if not re.fullmatch(r'\d+(?:[\s,、]+\d+)*', s):
        raise CheckError('号码之间请用空格或逗号分隔')
    return [int(v) for v in re.split(r'[\s,、]+', s)]

def digits(x, width):
    # A string is mandatory: JSON numeric 0123 loses the leading zero.
    if not isinstance(x, str) or not re.fullmatch(rf'[0-9]{{{width}}}', norm(x)):
        raise CheckError(f'号码必须是 {width} 位 string，保留开头的 0')
    return norm(x)

def validate_numbers(game, nums, bonus=None):
    _, n, maximum, bn = GAMES[game]
    if len(nums) != n or len(set(nums)) != n:
        raise CheckError(f'{game} 必须有 {n} 个不同的号码')
    if any(type(v) is not int or not 1 <= v <= maximum for v in nums):
        raise CheckError(f'{game} 号码范围为 1–{maximum}')
    if game == 'bingo5' and any(not 5*i+1 <= v <= 5*i+5 for i,v in enumerate(nums)):
        raise CheckError('BINGO5 按从左到右、从上到下输入，跳过 FREE；各格依次为 1–5、6–10…36–40')
    if bonus is not None:
        if len(bonus) != bn or len(set(bonus)) != bn or set(bonus)&set(nums):
            raise CheckError('官方 bonus 数量、重复或与本数字重叠异常')
        if any(not 1 <= v <= maximum for v in bonus):
            raise CheckError('官方 bonus 超出范围')

def simple_rows(table):
    """Keep physical columns; preserve rowspan labels without duplicating colspans."""
    grid, carried = [], {}
    for source in table:
        row, col, new = [], 0, {}
        def advance():
            nonlocal col
            while col in carried:
                text, remain = carried[col]
                row.append(text)
                if remain > 1:
                    new[col] = (text, remain-1)
                col += 1
        for cell in source:
            advance()
            text = norm(cell['text'])
            row.append(text)
            if cell.get('rs', 1) > 1:
                new[col] = (text, cell['rs']-1)
            col += 1
        advance()
        carried = new
        grid.append(row)
    return grid

def parse_digital(page, game, url):
    result = {}
    for table in page['tables']:
        rows = simple_rows(table)
        by_label = {r[0]: r[1:] for r in rows if r}
        if '回別' not in by_label:
            continue  # Ignore mobile duplicate sub-tables.
        head = ''.join(by_label['回別'])
        if not re.fullmatch(r'第\d+回', head):
            continue
        num = draw_id(head)
        dates = ''.join(by_label.get('抽せん日', []))
        dm = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', dates)
        if not dm:
            raise CheckError(f'第{num}回开奖日期缺失，停止判定')
        date = f'{int(dm[1]):04}-{int(dm[2]):02}-{int(dm[3]):02}'
        draw = {'game':game, 'draw':num, 'date':date, 'source':url, 'prizes':{}}
        if game.startswith('numbers'):
            draw['number'] = digits(''.join(by_label.get('抽せん数字', [])), GAMES[game][1])
            for key,label in MODES.items():
                if label in by_label:
                    draw['prizes'][key] = yen(by_label[label][-1])
            needed = {'straight','box','set_straight','set_box'}
            if game == 'numbers3': needed.add('mini')
        else:
            if game == 'bingo5':
                cells = [s for r in rows if r and r[0]=='抽せん数字' for s in r[1:]]
                cells = [s for s in cells if s!='FREE']
                if any(not re.fullmatch(r'\d{1,2}', s) for s in cells):
                    raise CheckError('BINGO5 官方棋盘格式异常')
                draw['numbers'] = [int(s) for s in cells]
                draw['bonus'] = []
            else:
                combined = by_label.get('本数字()はボーナス数字')
                cells = combined[:-1] if combined else by_label.get('本数字', [])
                if any(not re.fullmatch(r'\d{1,2}', s) for s in cells):
                    raise CheckError('官方本数字格式异常')
                draw['numbers'] = [int(s) for s in cells]
                b = combined[-1] if combined else ''.join(by_label.get('ボーナス数字', []))
                if not re.fullmatch(r'(?:\(\d{1,2}\))+', b):
                    raise CheckError('官方 bonus 格式异常')
                draw['bonus'] = [int(s) for s in re.findall(r'\d+', b)]
            validate_numbers(game, draw['numbers'], draw['bonus'])
            for key, cells in by_label.items():
                if re.fullmatch(r'\d+等', key):
                    draw['prizes'][key] = yen(cells[-1])
            counts = {'loto6':5, 'loto7':6, 'miniloto':4, 'bingo5':7}
            needed = {f'{i}等' for i in range(1,counts[game]+1)}
        if not needed <= draw['prizes'].keys():
            raise CheckError(f'第{num}回奖金表缺失，停止判定')
        if num in result and result[num] != draw:
            raise CheckError('同一期出现相互矛盾的官方数据')
        result[num] = draw
    if not result:
        raise CheckError('未读取到完整开奖表；可能尚未开奖、数据未载入或官网格式已改变')
    return result

def parse_regional(page, game, number, url):
    title = norm(page['title'])
    required = f'第{number}回{REGIONS[game]}'
    if required not in title:
        raise CheckError(f'页面与 {required} 不匹配；停止判定')
    found = []
    for table in page['tables']:
        rows = simple_rows(table)
        if not rows or rows[0] != ['等級','当せん金額','組','番号']:
            continue
        rules = []
        for r in rows[1:]:
            if len(r) != 4 or not r[0]:
                raise CheckError('地域宝くじ奖金表格式异常')
            grade, money, group, code = r
            amount = yen(money)
            if amount is None:
                raise CheckError('地域宝くじ奖金额缺失')
            rule = {'grade':grade, 'yen':amount, 'group':group, 'number':code}
            # Every row is validated before any losing verdict is possible.
            classify_rule(rule)
            rules.append(rule)
        if rules and rules not in found:
            found.append(rules)
    if len(found) != 1:
        raise CheckError('找不到唯一且完整的地域宝くじ开奖表')
    rules = found[0]
    if any(r['kind'] in ('adjacent','different_group') for r in rules):
        if not any(r['grade']=='1等' and r['kind']=='exact' for r in rules):
            raise CheckError('前後賞／組違い賞缺少可核对的1等基准')
    metadata = {}
    for label in ['抽せん日','支払期間']:
        m = re.search(label+r'[：:]([^\n]+)', page['title'])
        if m: metadata[label] = m[1].strip()
    return {'game':game,'draw':number,'source':url,'rules':rules, **metadata}

def classify_rule(r):
    group, code = r['group'], r['number']
    if code == '1等の前後の番号' and '前後賞' in r['grade']:
        r['kind'] = 'adjacent'
    elif code == '1等の組違い同番号' and '組違い賞' in r['grade']:
        r['kind'] = 'different_group'
    elif re.fullmatch(r'\d{1,6}番', code):
        n = code[:-1]
        tail = re.fullmatch(r'下(\d)(?:ケタ|桁|けた)', group)
        if tail and len(n)==int(tail[1]):
            r.update(kind='suffix', digits=n)
        elif group == '各組共通' and len(n)==6:
            r.update(kind='any_group', digits=n)
        elif re.fullmatch(r'\d+組', group) and len(n)==6:
            r.update(kind='exact', digits=n, group_id=int(group[:-1]))
        else:
            gm = re.fullmatch(r'組下(\d)(?:ケタ|桁|けた)(\d+)組?', group)
            if gm and len(n)==6 and len(gm[2])==int(gm[1]):
                r.update(kind='group_suffix',digits=n,group_digits=gm[2])
            else:
                raise CheckError(f'暂不识别这一奖项规则，请人工核对：{r}')
    else:
        raise CheckError(f'暂不识别这一奖项规则，请人工核对：{r}')

def check_ticket(ticket, draw):
    game = game_name(ticket['game'])
    if game != draw['game'] or draw_id(ticket['draw']) != draw['draw']:
        raise CheckError('彩票类别／期号与开奖数据不一致')
    copies = ticket.get('copies',1)
    if type(copies) is not int or copies < 1:
        raise CheckError('copies 必须是正整数')
    out = {k:v for k,v in draw.items() if k not in ('rules','prizes')}
    out['copies'] = copies
    if game in REGIONS:
        number = digits(ticket.get('number'),6)
        group = norm(ticket.get('group',''))
        if not re.fullmatch(r'\d{1,3}', group) or int(group)<1:
            raise CheckError('请输入彩票上的組（1–999）')
        group = int(group)
        matched = []
        first = [r for r in draw['rules'] if r['grade']=='1等' and r['kind']=='exact']
        for r in draw['rules']:
            kind = r['kind']
            hit = False
            if kind == 'suffix': hit = number.endswith(r['digits'])
            elif kind == 'any_group': hit = number == r['digits']
            elif kind == 'exact': hit = number == r['digits'] and group == r['group_id']
            elif kind == 'group_suffix':
                hit = number == r['digits'] and str(group).zfill(3).endswith(r['group_digits'])
            elif kind == 'different_group':
                hit = any(number==f['digits'] and group!=f['group_id'] for f in first)
            elif kind == 'adjacent':
                # Do not invent cross-group or wraparound behavior for unusual boundaries.
                for f in first:
                    if f['digits'] in ('100000','199999') and number in ('100000','199999'):
                        raise CheckError('前後賞涉及号码边界，请以该期官方规则人工核验')
                hit = any(group==f['group_id'] and abs(int(number)-int(f['digits']))==1 for f in first)
            if hit:
                item = {'grade':r['grade'],'yen_per_ticket':r['yen']}
                if item not in matched: matched.append(item)
        out.update(ticket={'group':group,'number':number},matches=matched,
                   status='WIN' if matched else 'LOSE')
        # Show each award separately; do not assume unusual edition overlap rules.
        return out
    if game.startswith('numbers'):
        mode = norm(ticket.get('mode','')).lower()
        mode = {'ストレート':'straight','ボックス':'box','セット':'set','ミニ':'mini'}.get(mode,mode)
        if mode not in ('straight','box','set','mini') or mode=='mini' and game!='numbers3':
            raise CheckError('请指定 mode：straight／box／set；numbers3 也可 mini')
        pick = digits(ticket.get('number'),2 if mode=='mini' else GAMES[game][1])
        if mode in ('box','set') and len(set(pick))==1:
            raise CheckError('box／set 不能购买全部相同的数字')
        winning = draw['number']
        exact, box = pick==winning, Counter(pick)==Counter(winning)
        key = None
        if mode=='mini' and pick==winning[-2:]: key='mini'
        elif mode=='straight' and exact: key='straight'
        elif mode=='box' and box: key='box'
        elif mode=='set' and box: key='set_straight' if exact else 'set_box'
        out.update(ticket=pick,mode=mode)
    else:
        pick = values(ticket.get('numbers',''))
        validate_numbers(game,pick)
        matches = len(set(pick)&set(draw['numbers']))
        bonus = len(set(pick)&set(draw['bonus']))
        grade = None
        if game=='loto6':
            grade = 1 if matches==6 else (2 if bonus else 3) if matches==5 else {4:4,3:5}.get(matches)
        elif game=='loto7':
            grade = 1 if matches==7 else (2 if bonus else 3) if matches==6 else {5:4,4:5}.get(matches)
            if matches==3 and bonus>=1: grade=6
        elif game=='miniloto':
            grade = 1 if matches==5 else (2 if bonus else 3) if matches==4 else 4 if matches==3 else None
        elif game=='bingo5':
            board = [a==b for a,b in zip(pick,draw['numbers'])]
            board.insert(4,True)
            lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
            completed = [list(line) for line in lines if all(board[i] for i in line)]
            grade = {8:1,6:2,5:3,4:4,3:5,2:6,1:7}.get(len(completed))
            out.update(lines=len(completed),completed_lines=completed)
        key = f'{grade}等' if grade else None
        out.update(ticket=pick,matched_main=matches,matched_bonus=bonus)
    payout = draw['prizes'].get(key) if key else 0
    out.update(status='WIN' if key else 'LOSE',grade=key,
               yen_per_ticket=payout,total_yen=payout*copies if payout is not None else None)
    if key and payout is None:
        out['note']='号码符合此奖项，但官网金额为「該当なし」；请检查输入是否确为已购买的彩票。'
    return out

class OfficialClient:
    def __init__(self, headed=False, refresh=False, show_endpoints=False, cache_dir=None):
        self.headed, self.refresh, self.show_endpoints = headed,refresh,show_endpoints
        self.cache_dir = Path(cache_dir or Path.home()/'.cache'/'takarakuji-checker')
        self.cache_dir.mkdir(parents=True,exist_ok=True)
        self.memo = {}
        self.runtime = self.browser = self.page = None

    def __enter__(self): return self
    def __exit__(self,*args):
        if self.browser: self.browser.close()
        if self.runtime: self.runtime.stop()

    def start(self):
        if self.page: return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise CheckError('请先运行：python -m pip install playwright；python -m playwright install chromium') from e
        self.runtime=sync_playwright().start()
        self.browser=self.runtime.chromium.launch(headless=not self.headed)
        self.page=self.browser.new_page(viewport={'width':1364,'height':1024},locale='ja-JP')
        if self.show_endpoints:
            seen=set()
            def log(response):
                u=response.url
                p=urlparse(u)
                if p.hostname!='www.mizuhobank.co.jp' or u in seen: return
                ct=response.headers.get('content-type','')
                if response.request.resource_type in ('xhr','fetch') or any(s in ct for s in ('json','csv')) or 'lottery.js' in p.path:
                    seen.add(u)
                    print(f'[endpoint] {response.status} {ct} {u}',file=sys.stderr)
            self.page.on('response',log)

    def get(self,url,kind='digital'):
        p=urlparse(url)
        if p.scheme!='https' or p.hostname!='www.mizuhobank.co.jp' or not p.path.startswith('/takarakuji/check/'):
            raise CheckError(f'不允许的开奖来源：{url}')
        if url in self.memo: return self.memo[url]
        cache=self.cache_dir/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if not self.refresh and not self.show_endpoints and cache.exists() and time.time()-cache.stat().st_mtime<3600:
            try:
                doc=json.loads(cache.read_text(encoding='utf-8'))
                if doc.get('url')==url and 'page' in doc:
                    self.memo[url]=doc['page'];return doc['page']
            except (ValueError,OSError): pass
        self.start()
        print(f'[读取官网] {url}',file=sys.stderr)
        try:
            response=self.page.goto(url,wait_until='domcontentloaded',timeout=45000)
            if response and response.status>=400:
                raise CheckError(f'官网返回 HTTP {response.status}，没有判定中奖与否')
            # Explicitly wait for JS-populated result cells, not a fixed sleep.
            conditions={
                'digital':r"() => Array.from(document.querySelectorAll('main table')).some(t => /回別\s*第\d+回/.test(t.innerText) && /[\d,]+円/.test(t.innerText))",
                'regional':r"() => Array.from(document.querySelectorAll('main table')).some(t => /当せん金額/.test(t.innerText) && /\d+番/.test(t.innerText))",
                'links':r"() => Array.from(document.querySelectorAll('main table a[href]')).some(a => /(?:year=|result\.html|backnumber\/)/.test(a.href))"
            }
            self.page.wait_for_function(conditions[kind],timeout=30000)
            data=self.page.evaluate(EXTRACT)
        except CheckError: raise
        except Exception as e:
            raise CheckError(f'无法载入完整官网数据，未作中奖判定。URL: {url}\n{type(e).__name__}: {e}') from e
        data['fetched_at']=datetime.now().astimezone().isoformat()
        cache.write_text(json.dumps({'url':url,'page':data},ensure_ascii=False),encoding='utf-8')
        self.memo[url]=data
        return data

    def digital_url(self,game,month=None):
        url=f'{BASE}/takarakuji/check/{GAMES[game][0]}/{game}/index.html'
        if month:
            if not re.fullmatch(r'\d{4}-\d{2}',month): raise CheckError('month 格式须为 YYYY-MM')
            year,mo=map(int,month.split('-'))
            if not 1<=mo<=12: raise CheckError('month 无效')
            url+=f'?year={year}&month={mo}'
        return url

    def digital(self,game,number=None,month=None):
        url=self.digital_url(game,month)
        draws=parse_digital(self.get(url),game,url)
        if number is None: return list(draws.values())
        if number in draws: return draws[number]
        if month:
            raise CheckError(f'{month} 不包含第{number}回；不会改用最近一期')
        if number>max(draws):
            raise CheckError(f'官网最新为第{max(draws)}回；第{number}回尚未公布或未载入')
        archive=f'{BASE}/takarakuji/check/{GAMES[game][0]}/backnumber/index.html'
        links=self.get(archive,'links')['links']
        # Follow actual official monthly links, newest first. No date-to-draw guesses.
        urls=list(dict.fromkeys(l['href'] for l in links if f'/{game}/index.html?year=' in l['href']))
        for u in urls:
            d=parse_digital(self.get(u),game,u)
            if number in d: return d[number]
            if number>max(d): break
        raise CheckError(f'第{number}回不在已解析的官方月度档案中。较早的旧版 B表不自动判定；请在官网核对。')

    def regional_list(self,game,month=None):
        if month and not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',month):
            raise CheckError('month 格式须为 YYYY-MM')
        url=f'{BASE}/takarakuji/check/tsujyo/top.html?type={game}'
        data=self.get(url,'links')
        result=[]
        for link in data['links']:
            name=norm(link['text'])
            m=re.match(r'第(\d+)回',name)
            if not m or REGIONS[game] not in name or '/tsujyo/result.html?' not in link['href']: continue
            dm=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',norm(link['row']))
            if not dm: raise CheckError('地域宝くじ档案中的日期无法识别')
            date=f'{int(dm[1]):04}-{int(dm[2]):02}-{int(dm[3]):02}'
            if month and not date.startswith(month): continue
            entry={'game':game,'draw':int(m[1]),'date':date,'name':name,'source':link['href']}
            if entry not in result: result.append(entry)
        return result

    def regional(self,game,number,month=None):
        rows=self.regional_list(game,month)
        candidates=[r for r in rows if r['draw']==number]
        if len(candidates)!=1:
            raise CheckError(f'官网档案未列出 {REGIONS[game]} 第{number}回'+(f'（{month}）' if month else '')+'；没有作中奖判定')
        entry=candidates[0]
        data=self.get(entry['source'],'regional')
        draw=parse_regional(data,game,number,entry['source'])
        draw['date']=entry['date']
        return draw

    def draw(self,ticket):
        game=game_name(ticket['game']);number=draw_id(ticket['draw'])
        if game in REGIONS: return self.regional(game,number,ticket.get('month'))
        if game in GAMES: return self.digital(game,number,ticket.get('month'))
        raise CheckError(f'不支持的类别：{game}；可用：{", ".join([*GAMES,*REGIONS])}')

def output(x): print(json.dumps(x,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--headed',action='store_true',help='显示浏览器窗口')
    p.add_argument('--refresh',action='store_true',help='忽略一小时缓存')
    p.add_argument('--show-endpoints',action='store_true',help='输出官网 XHR/fetch、JSON/CSV 和 lottery.js 地址到 stderr')
    p.add_argument('--cache-dir')
    sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('check','draw','list'):
        s=sub.add_parser(cmd)
        s.add_argument('--game',required=True,help=', '.join([*GAMES,*REGIONS])+', or all-regional (list only)')
        s.add_argument('--month',help='YYYY-MM；开奖月份，可加速按期号查询')
        if cmd!='list': s.add_argument('--draw',required=True,help='例如 0691、691、第691回')
        if cmd=='check':
            s.add_argument('--numbers',help='LOTO／BINGO5：用空格或逗号分隔')
            s.add_argument('--number',help='NUMBERS／地域宝くじ：保留开头的 0')
            s.add_argument('--group',help='地域宝くじ的組')
            s.add_argument('--mode',help='straight／box／set／mini')
            s.add_argument('--copies',type=int,default=1)
    s=sub.add_parser('batch');s.add_argument('file',help='彩票 JSON array；可混合类型和期号')
    a=p.parse_args()
    try:
        with OfficialClient(a.headed,a.refresh,a.show_endpoints,a.cache_dir) as client:
            if a.command=='batch':
                tickets=json.loads(Path(a.file).read_text(encoding='utf-8'))
                if not isinstance(tickets,list): raise CheckError('batch 文件必须是 JSON array')
                results=[];failed=False
                for i,t in enumerate(tickets):
                    try:
                        results.append({'index':i,**check_ticket(t,client.draw(t))})
                    except (CheckError,KeyError,TypeError,ValueError) as e:
                        failed=True;results.append({'index':i,'status':'UNKNOWN','error':str(e)})
                output(results);return 2 if failed else 0
            game=game_name(a.game)
            if a.command=='list':
                if game=='all-regional':
                    output([entry for g in REGIONS for entry in client.regional_list(g,a.month)])
                elif game in REGIONS: output(client.regional_list(game,a.month))
                elif game in GAMES: output(client.digital(game,month=a.month))
                else: raise CheckError('未知类别')
            else:
                ticket=vars(a).copy();ticket['game']=game
                draw=client.draw(ticket)
                output(draw if a.command=='draw' else check_ticket(ticket,draw))
        return 0
    except (CheckError,KeyError,TypeError,ValueError,OSError) as e:
        output({'status':'UNKNOWN','error':str(e)})
        return 2

if __name__=='__main__': sys.exit(main())
