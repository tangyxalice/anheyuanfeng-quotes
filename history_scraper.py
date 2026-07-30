"""
真实历史价格爬虫 + 走势构建
─────────────────────────────
彻底替代原来的「随机游走模拟」(random.gauss)。

数据来源(生意社 100ppi.com):
  - 磷酸一铵 MAP55% : map.100ppi.com/news/list--1217-N.html  (每日基准价新闻列表, 可翻页)
  - 黄磷 YP        : chem.100ppi.com/kx/list-1170-13-N.html  (每日参考价快讯, 可翻页)
  - 磷酸铁锂 LFP   : lfp.100ppi.com/news/list--1217-N.html   (每日基准价新闻列表, 可翻页)
  - 硫磺(颗粒现货) : m1.100ppi.com/vane/427-硫磺             (走势页, 稀疏真实点, 业务日更新)

对缺失日期采用「线性插值」(在两两真实点之间), 并在每个数据点标注来源:
  - flag="real"     : 当日有真实基准价
  - flag="interp"   : 缺失日, 由相邻两个真实点线性插值得到
  - flag="fallback" : 序列最前端的空缺(早于首个真实点), 沿用最近真实点
  - flag="reference": 该品种无真实历史序列, 以当前参考价画水平线(如 DAP / 液体硫磺 / 磷酸铁等)

调用方需传入 get_text(url)->str|None (app.py 用 safe_get, generate_static.py 用 requests.get)。
"""

import re
from datetime import datetime, timedelta


# ── 各品种「基准价新闻列表」配置 ──
# pages: 多个翻页 URL(覆盖 >30 天)
# regex: 从页面文本提取 (月, 日, 价格)
BENCHMARK_CONFIG = {
    "map_55": {
        "pages": ["https://map.100ppi.com/news/list--1217-{n}.html".format(n=i) for i in range(1, 5)],
        "regex": r"(\d{1,2})月(\d{1,2})日[^\n<]*?磷酸一铵基准价为(\d+\.?\d*)元/吨",
    },
    "yp": {
        "pages": ["https://chem.100ppi.com/kx/list-1170-13-{n}.html".format(n=i) for i in range(1, 5)],
        "regex": r"(\d{1,2})月(\d{1,2})日黄磷为(\d+\.?\d*)",
    },
    "lfp_power": {
        "pages": ["https://lfp.100ppi.com/news/list--1217-{n}.html".format(n=i) for i in range(1, 5)],
        "regex": r"(\d{1,2})月(\d{1,2})日[^\n<]*?磷酸铁锂基准价为(\d+\.?\d*)元/吨",
    },
}


def _resolve_year(month, today):
    """月 -> 年: 跨年时(月 > 当前月)归为上一年, 否则当年。"""
    return today.year - 1 if month > today.month else today.year


def _extract_dated_prices(text, regex, today):
    """用 regex 从文本提取 {(YYYY-MM-DD): price}。"""
    out = {}
    if not text:
        return out
    for m in re.finditer(regex, text):
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            price = float(m.group(3))
        except (ValueError, IndexError):
            continue
        if price <= 0:
            continue
        yyyy = _resolve_year(mm, today)
        try:
            ds = datetime(yyyy, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            continue
        out[ds] = price
    return out


def scrape_commodity_histories(get_text, today=None, max_pages=4):
    """抓取 MAP / YP / LFP 的每日真实基准价。
    返回 {key: {date_str: price}}。"""
    today = today or datetime.now().date()
    result = {}
    for key, cfg in BENCHMARK_CONFIG.items():
        merged = {}
        for url in cfg["pages"][:max_pages]:
            try:
                txt = get_text(url)
            except Exception:
                txt = None
            if not txt:
                continue
            merged.update(_extract_dated_prices(txt, cfg["regex"], today))
            if len(merged) >= 40:  # 足够覆盖 30 天即停止翻页
                break
        if merged:
            result[key] = merged
    return result


def scrape_vane_history(get_text, code, label="硫磺", today=None):
    """抓取 vane 走势页的稀疏真实点(如硫磺 427)。
    返回 {date_str: price}。兼容 HTML 表格结构(单元格被 <td> 分隔)。"""
    today = today or datetime.now().date()
    url = "https://m1.100ppi.com/vane/{code}-{label}".format(code=code, label=label)
    try:
        txt = get_text(url)
    except Exception:
        txt = None
    if not txt or len(txt) < 500:
        return {}
    out = {}
    # 优先尝试 BS4 解析表格
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(txt, "lxml")
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            txts = [c.get_text(strip=True) for c in cells]
            mm_dd = None
            price = None
            for t in txts:
                if mm_dd is None:
                    m = re.match(r"^(\d{2})-(\d{2})$", t)
                    if m:
                        mm_dd = (int(m.group(1)), int(m.group(2)))
                        continue
                if mm_dd is not None and price is None:
                    pm = re.match(r"^(\d+\.?\d*)$", t)
                    if pm:
                        try:
                            p = float(pm.group(1))
                            if p > 0:
                                price = p
                        except ValueError:
                            pass
            if mm_dd and price:
                mm, dd = mm_dd
                yyyy = _resolve_year(mm, today)
                try:
                    ds = datetime(yyyy, mm, dd).strftime("%Y-%m-%d")
                    out[ds] = price
                except ValueError:
                    pass
        if out:
            return out
    except ImportError:
        pass
    except Exception:
        pass
    # 回退: 宽松正则(允许 HTML 标签/空白在 MM-DD 和价格之间)
    for m in re.finditer(r">(\d{2})-(\d{2})</td>.{0,300}?>(\d+\.?\d*)</td>", txt, re.DOTALL):
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            price = float(m.group(3))
        except (ValueError, IndexError):
            continue
        if price <= 0:
            continue
        yyyy = _resolve_year(mm, today)
        try:
            ds = datetime(yyyy, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            continue
        out[ds] = price
    return out


def build_real_series(real_map, days, current_price, today=None):
    """把真实 {(date): price} 扩展为最近 days 天的序列。
    - 注入「今天=当前真实价」, 保证曲线末点=卡片价
    - 缺失日线性插值, 标注 flag
    返回 (points, meta)
      points: [{date, price, flag}], 长度=days
      meta:  {real, interp, fallback, has_series}
    """
    today = today or datetime.now().date()
    days = int(days)
    current_price = float(current_price)

    # 真实点(注入今天为真实点, 末点=卡片价)
    rm = {k: float(v) for k, v in real_map.items() if v and float(v) > 0}
    today_str = today.strftime("%Y-%m-%d")
    rm[today_str] = current_price

    known_dates = sorted(rm.keys())
    truly_real = set(real_map.keys())  # 真正抓取到的日期(不含注入的今天)
    truly_real.add(today_str)

    dates = [(today - timedelta(days=days - 1 - i)) for i in range(days)]
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]

    points = []
    meta = {"real": 0, "interp": 0, "fallback": 0}
    has_series = len(truly_real - {today_str}) >= 2  # 至少有 2 个真实历史点才算有序列

    for ds in date_strs:
        if ds in rm:
            points.append({"date": ds, "price": round(rm[ds], 2), "flag": "real"})
            meta["real"] += 1
            continue
        # 找前后最近真实点
        before = None
        after = None
        for kd in known_dates:
            if kd < ds:
                before = kd
            elif kd > ds:
                after = kd
                break
        if before and after:
            pb, pa = rm[before], rm[after]
            db = datetime.strptime(before, "%Y-%m-%d").date()
            da = datetime.strptime(after, "%Y-%m-%d").date()
            dd_ = datetime.strptime(ds, "%Y-%m-%d").date()
            span = max(1, (da - db).days)
            frac = (dd_ - db).days / span
            val = pb + (pa - pb) * frac
            points.append({"date": ds, "price": round(val, 2), "flag": "interp"})
            meta["interp"] += 1
        elif before:
            points.append({"date": ds, "price": round(rm[before], 2), "flag": "fallback"})
            meta["fallback"] += 1
        elif after:
            points.append({"date": ds, "price": round(rm[after], 2), "flag": "fallback"})
            meta["fallback"] += 1
        else:
            points.append({"date": ds, "price": round(current_price, 2), "flag": "fallback"})
            meta["fallback"] += 1

    meta["has_series"] = has_series
    return points, meta


def flat_reference_series(current_price, days, today=None):
    """无真实历史序列的品种: 以当前参考价画水平线, flag='reference'。"""
    today = today or datetime.now().date()
    days = int(days)
    current_price = float(current_price)
    points = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        points.append({"date": d.strftime("%Y-%m-%d"), "price": round(current_price, 2), "flag": "reference"})
    return points, {"real": 0, "interp": 0, "fallback": 0, "has_series": False}
