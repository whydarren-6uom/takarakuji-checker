export const games = {loto6:'ロト6',loto7:'ロト7',miniloto:'ミニロト',bingo5:'ビンゴ5',numbers3:'ナンバーズ3',numbers4:'ナンバーズ4',zenkoku:'全国自治宝くじ',tokyo:'東京都宝くじ',kct:'関東・中部・東北自治宝くじ',kinki:'近畿宝くじ',nishinihon:'西日本宝くじ',chiiki:'地域医療等振興自治宝くじ'};
const specs={loto6:[6,43,1,5],loto7:[7,37,2,6],miniloto:[5,31,1,4],bingo5:[8,40,0,7]};
const norm=x=>String(x??'').normalize('NFKC').replace(/\s/g,'');
const fail=m=>{throw new Error(m)};
export function drawId(x){const m=norm(x).match(/^(?:第)?0*([0-9]+)(?:回)?$/);if(!m||!Number.isSafeInteger(+m[1])||+m[1]<1)fail('期号无效');return +m[1]}
export function gameName(x){const s=norm(x).toLowerCase();if(s==='全国通常宝くじ')return 'zenkoku';return Object.keys(games).find(k=>games[k]===s)||s}
function digits(x,n){if(typeof x!=='string'||!new RegExp(`^[0-9]{${n}}$`).test(norm(x)))fail(`号码必须是 ${n} 位 string，保留开头的 0`);return norm(x)}
function numbers(x){if(Array.isArray(x)){if(x.some(n=>!Number.isInteger(n)))fail('numbers array 只能包含 integers');return x}const s=String(x??'').normalize('NFKC').trim();if(!/^\d+(?:[\s,、]+\d+)*$/.test(s))fail('号码之间请用空格或逗号分隔');return s.split(/[\s,、]+/).map(Number)}
function validate(g,ns,bs){const [n,max,bn]=specs[g];if(ns.length!==n||new Set(ns).size!==n||ns.some(v=>!Number.isInteger(v)||v<1||v>max))fail(`${games[g]} 需要 ${n} 个不同的号码，范围 1–${max}`);if(g==='bingo5'&&ns.some((v,i)=>v<5*i+1||v>5*i+5))fail('BINGO5 各格依次为 1–5、6–10…36–40，跳过 FREE');if(bs&&(bs.length!==bn||new Set(bs).size!==bn||bs.some(v=>!Number.isInteger(v)||v<1||v>max||ns.includes(v))))fail('官方 bonus 数据异常')}
export function checkTicket(t,d){
 if(!t||typeof t!=='object'||Array.isArray(t))fail('每张彩票必须是一个 JSON object');
 const game=gameName(t.game),id=drawId(t.draw);if(!games[game])fail('不支持的彩票类别');if(!d)fail('该期尚未同步，无法判定。请查看官方来源');if(game!==d.game||id!==d.draw)fail('彩票类别／期号与开奖数据不一致');if(t.month&&(!/^\d{4}-(0[1-9]|1[0-2])$/.test(t.month)||!d.date?.startsWith(t.month)))fail('月份与开奖数据不一致');
 const copies=t.copies??1;if(!Number.isSafeInteger(copies)||copies<1||copies>1000000)fail('copies 必须是 1–1000000 的整数');
 const out=Object.fromEntries(Object.entries(d).filter(([k])=>!['rules','prizes','fetched_at'].includes(k)));out.copies=copies;
 if(!specs[game]&&!game.startsWith('numbers')){
  const number=digits(t.number,6),g=norm(t.group);if(!/^\d{1,3}$/.test(g)||+g<1)fail('请输入彩票上的組（1–999）');const group=+g;
  if(!Array.isArray(d.rules)||!d.rules.length)fail('官方奖项缺失');const first=d.rules.filter(r=>r.grade==='1等'&&['exact','group_suffix'].includes(r.kind)),matched=[];
  for(const r of d.rules){let hit=false;if(!Number.isSafeInteger(r.yen)||r.yen<0)fail('奖金额异常');
   if(r.kind==='suffix')hit=number.endsWith(r.digits);
   else if(r.kind==='any_group')hit=number===r.digits;
   else if(r.kind==='exact')hit=number===r.digits&&group===r.group_id;
   else if(r.kind==='group_suffix')hit=number===r.digits&&String(group).padStart(3,'0').endsWith(r.group_digits);
   else if(['different_group','adjacent'].includes(r.kind)){
    if(!first.length)fail('缺少1等基准');
    if(r.kind==='different_group')hit=first.some(f=>f.kind==='exact'&&number===f.digits&&group!==f.group_id);
    else{if(first.some(f=>['100000','199999'].includes(f.digits)&&['100000','199999'].includes(number)))fail('前後賞涉及号码边界，请人工核验');hit=first.some(f=>(f.kind==='exact'?group===f.group_id:String(group).padStart(3,'0').endsWith(f.group_digits))&&Math.abs(+number-+f.digits)===1)}
   }else fail('未知地域奖项规则，请人工核对');
   if(hit&&!matched.some(m=>m.grade===r.grade&&m.yen_per_ticket===r.yen))matched.push({grade:r.grade,yen_per_ticket:r.yen});
  }return {...out,ticket:{group,number},matches:matched,status:matched.length?'WIN':'LOSE'};
 }
 let key=null;
 if(game.startsWith('numbers')){
  let mode=norm(t.mode).toLowerCase();mode=({'ストレート':'straight','ボックス':'box','セット':'set','ミニ':'mini'})[mode]||mode;
  if(!['straight','box','set','mini'].includes(mode)||(mode==='mini'&&game!=='numbers3'))fail('请指定 straight／box／set；numbers3 也可 mini');
  const width=game==='numbers3'?3:4,pick=digits(t.number,mode==='mini'?2:width),winning=digits(d.number,width);
  const needed=['straight','box','set_straight','set_box',...(width===3?['mini']:[])];if(needed.some(k=>!Object.hasOwn(d.prizes||{},k)))fail('官方奖金表缺失');
  if(['box','set'].includes(mode)&&new Set(pick).size===1)fail('box／set 不能购买全部相同的数字');
  const exact=pick===winning,box=[...pick].sort().join('')===[...winning].sort().join('');
  if(mode==='mini'&&pick===winning.slice(-2))key='mini';else if(mode==='straight'&&exact)key='straight';else if(mode==='box'&&box)key='box';else if(mode==='set'&&box)key=exact?'set_straight':'set_box';Object.assign(out,{ticket:pick,mode});
 }else{
  validate(game,d.numbers,d.bonus);if(Array.from({length:specs[game][3]},(_,i)=>`${i+1}等`).some(k=>!Object.hasOwn(d.prizes||{},k)))fail('官方奖金表缺失');
  const pick=numbers(t.numbers);validate(game,pick);const m=pick.filter(v=>d.numbers.includes(v)).length,b=pick.filter(v=>d.bonus.includes(v)).length;let grade;
  if(game==='loto6')grade=m===6?1:m===5?(b?2:3):({4:4,3:5})[m];
  if(game==='loto7')grade=m===7?1:m===6?(b?2:3):m===3&&b>=1?6:({5:4,4:5})[m];
  if(game==='miniloto')grade=m===5?1:m===4?(b?2:3):m===3?4:null;
  if(game==='bingo5'){const board=pick.map((v,i)=>v===d.numbers[i]);board.splice(4,0,true);const lines=[[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]].filter(l=>l.every(i=>board[i]));grade=({8:1,6:2,5:3,4:4,3:5,2:6,1:7})[lines.length];Object.assign(out,{lines:lines.length,completed_lines:lines})}
  key=grade?`${grade}等`:null;Object.assign(out,{ticket:pick,matched_main:m,matched_bonus:b});
 }
 const payout=key?d.prizes[key]:0;if(payout!==null&&(!Number.isSafeInteger(payout)||payout<0))fail('奖金额异常');Object.assign(out,{status:key?'WIN':'LOSE',grade:key,yen_per_ticket:payout,total_yen:payout===null?null:payout*copies});
 if(key&&payout===null)out.note='号码符合此奖项，但官网金额为「該当なし」；请检查输入是否确为已购买的彩票。';return out;
}
export function checkBatch(tickets,draws){return tickets.map((ticket,index)=>{let game,id;try{game=gameName(ticket?.game);id=drawId(ticket?.draw);return {index,...checkTicket(ticket,draws.find(d=>d.game===game&&d.draw===id))}}catch(e){return {index,game,draw:id,status:'UNKNOWN',error:e.message}}})}
