# 日本宝くじ查奖器（Python）

在线网页：<https://whydarren-6uom.github.io/takarakuji-checker/>。网页支持单张查奖与多类别、多少期号的 JSON batch；用户号码只在浏览器本地核对。

GitHub Actions 每日读取瑞穗银行公开开奖页面并部署静态数据。同步失败时保留上一份有效数据；网页会显示实际覆盖范围、更新时间和官方来源。未同步期号、未知规则或异常数据一律返回 `UNKNOWN`，不会误报为未中奖。

已确认官网前端通过 `/retail/takarakuji/.../csv/*.CSV` 的 XHR 请求载入开奖数据；`--show-endpoints` 会在浏览器运行时打印实际 CSV 请求地址，HTML 页面 URL 不作为 API 描述。GitHub-hosted runner 被官网 Akamai 拒绝时，定时任务通过 `r.jina.ai` 的只读文本 gateway 传输同一份官方 CSV；同步器会校验返回内容声明的官方 URL、期号、类别、日期、号码范围和完整奖金表，验证失败即保留旧数据并显示同步异常。

输入彩票种类、期号和号码，读取瑞穗银行公开开奖页，自动核对奖项及该期奖金。支持历史月份、精确期号、混合 batch；无需银行账户。**不预测、不购票，也不向官网上传你的号码。** 示例中的投注号码均为演示，不代表你的实际彩票。

## 安装（macOS / Windows / Linux，Python 3.10+）

在解压后的目录打开 Terminal：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Windows：先运行 `py -m venv .venv`，然后 PowerShell 运行 `.venv\Scripts\Activate.ps1`；后两条相同。安装 Chromium 只需一次。

## 支持范围

| game | 彩票 | 输入 |
|---|---|---|
| `loto7` | ロト7 | 1–37 中的7个不同数字 |
| `loto6` | ロト6 | 1–43 中的6个不同数字 |
| `miniloto` | ミニロト（额外支持） | 1–31 中的5个不同数字 |
| `bingo5` | ビンゴ5 | 8个格子的号码，跳过中心 FREE |
| `numbers3` | ナンバーズ3 | 3位 string；mini 为2位 |
| `numbers4` | ナンバーズ4 | 4位 string |
| `tokyo` | 東京都宝くじ | 期号、組、6位番号 |
| `kct` | 関東・中部・東北自治宝くじ | 同上 |
| `kinki` | 近畿宝くじ | 同上 |
| `nishinihon` | 西日本宝くじ | 同上 |
| `chiiki` | 地域医療等振興自治宝くじ／レインボーくじ | 同上 |

接受 `0691`、`691`、`第691回`。不同地域的期号不能混用。ナンバーズ支持 straight、box、set，ナンバーズ3另支持 mini；保留前导零，如 `"0123"`。

## 直接查历史期号

只看开奖信息：

```sh
python takarakuji.py draw --game loto7 --draw 0691
```

核对自己的号码（替换下面的示例号码）：

```sh
python takarakuji.py check --game loto7 --draw 0691 --numbers "1 2 3 4 5 6 7"
```

不知道期号对应的月份也可以：程序读取当前月，然后沿官网档案中的真实月份链接依次寻找。知道月份时加 `--month 2026-08`，减少请求。若月份与期号不符，返回 UNKNOWN，不改用最近一期。

已核实：LOTO7 第691回是 **2026-08-21**，本数字 `08 10 20 22 23 27 37`，bonus `02 09`。这只是对历史数据的核实，不是选号建议。

## 查今年3月有哪些地域宝くじ

```sh
python takarakuji.py list --game all-regional --month 2026-03
python takarakuji.py list --game tokyo --month 2026-03
```

再用列表中的期号核对：

```sh
python takarakuji.py check --game kct --draw 2708 --month 2026-03 --group 03 --number 123456
```

第2708回関東・中部・東北自治宝くじ已用真实3月开奖页测试。地域结果附官方支払期間；程序核对的是号码，不把号码中奖等同于仍在兑奖期限内。返回每一个命中的奖项及单张金额，不自行推断特别版的重叠兑奖总额。

## ビンゴ与ナンバーズ

```sh
python takarakuji.py check --game bingo5 --draw 488 --numbers "1 6 11 16 21 26 31 36"
python takarakuji.py check --game numbers3 --draw 7072 --number 029 --mode straight
python takarakuji.py check --game numbers3 --draw 7072 --number 29 --mode mini
python takarakuji.py check --game numbers4 --draw 7072 --number 0123 --mode set
```

BINGO5 顺序为从左到右、从上到下，跳过 FREE：第一格1–5、第二格6–10，依次到第八格36–40。按8条横、竖、斜线核对，不按命中数字个数判奖。

NUMBERS 的 set 使用该期官方「セット（ストレート）」或「セット（ボックス）」金额，不用近似公式推算。

## 一次查多张、多期

复制 `tickets.example.json`，替换为你的号码：

```sh
python takarakuji.py batch tickets.example.json > results.json
```

支持在同一文件里混合所有类别；同一类别也可放多期。每一注独立返回结果，某一注失败不会把其他注判成失败。连续购买的每一期作为一条记录；同一期同号码买多口，填 `"copies": 2`。

输出是 JSON：`WIN`、`LOSE` 或 `UNKNOWN`，含期号、日期、官方来源 URL、奖项和金额。LOTO/BINGO/NUMBERS 的 `total_yen` 按 copies 计算；地域券给出 `matches`。`UNKNOWN` 表示没有完成可靠核对，不是未中奖；batch 含 UNKNOWN 时 exit code 为2。

## JavaScript / Network endpoints

本次已观察到官方页面加载：

- `https://www.mizuhobank.co.jp/common2024/js/transfer/lottery.js`
- 历史月份页面：`/takarakuji/check/loto/loto7/index.html?year=2026&month=8`
- 地域逐期页面：`/takarakuji/check/tsujyo/result.html?type=kct&order=2708`

这些后两者是**页面 URL，不是已验证的 JSON API**。当前研究环境直接读取该 JS 返回 Access Denied，不能诚实地声称已找到内部 endpoint；没有猜测未验证的 API。

代码用 Playwright 等待官网 JS 填好表格后读取 DOM。下列选项在你本机监听真实 response events，将瑞穗域名的 XHR/fetch、JSON/CSV 和 lottery.js 地址打印到 stderr：

```sh
python takarakuji.py --show-endpoints --headed draw --game loto7 --draw 0691 --month 2026-08
```

这可帮助后续确认直接数据 endpoint。它不把请求发给未知服务、不修改 headers 或浏览器 fingerprint，不绕过任何验证。没有 CAPTCHA 自动处理。

## 历史覆盖及明确限制

- 数字选择式：支持官网当前月份和 A表中过去12个月的月度格式，所以2026年3月、LOTO7第691回都在覆盖内。官网更早的 B表旧格式尚未实现，**不是全历史数据库**；不会用最近一期冒充。
- 地域宝くじ：支持官网当前公开列表中列出的历史期次；地域档案的保留时间可能不同，列表没有的期次返回 UNKNOWN。
- 地域规则覆盖：指定組＋完整号码、各組共通、末尾1–6位、1等前後賞、1等組違い賞，以及可识别的組下位格式。特殊奖项表达不识别或前後賞涉及100000／199999边界时返回 UNKNOWN，交由人工核验。
- 不含スクラッチ、着せかえクーちゃん、ジャンボ、全国通常宝くじ；本版本聚焦上表所列类别。
- 官网变版、未开奖、缺失数据、网络失败均返回 UNKNOWN。缓存保留1小时；`--refresh` 强制更新，`--cache-dir PATH` 指定目录。
- 需要互联网与可正常访问官网的本机环境；最终兑奖以官方和彩票实物为准。

## 验证

```sh
python -m unittest -v
python parity_check.py
```

附真实官网 DOM fixtures（2026-09-17读取），涵盖6种数字选择式与5种地域类别、LOTO7第691回和3月地域券。测试包含全256种BINGO命中格局、LOTO bonus 分级、NUMBERS前导零和重复数字、地域尾号／前後賞／組違い賞、错误期号、损坏数据，以及历史链接选择。

已在研究环境运行 parser／判奖／历史选择测试；真实网页通过云浏览器读取。由于此环境的外部网络限制，**未在本地完整执行 Playwright 下载到判奖的端到端流程**。本机首次运行若出现 UNKNOWN，请保留报错和来源 URL 以便定位。

## 官方依据

- 开奖总入口：https://www.mizuhobank.co.jp/takarakuji/check/index.html
- 地域档案：https://www.mizuhobank.co.jp/takarakuji/check/tsujyo/index.html
- LOTO7历史月：https://www.mizuhobank.co.jp/takarakuji/check/loto/loto7/index.html?year=2026&month=8
- 3月地域样本：https://www.mizuhobank.co.jp/takarakuji/check/tsujyo/result.html?type=kct&order=2708
- ナンバーズ规则：https://www.mizuhobank.co.jp/takarakuji/products/numbers/index.html
- ビンゴ5规则：https://www.mizuhobank.co.jp/takarakuji/products/bingo5/index.html
