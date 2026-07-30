"""
多源价格爬虫: 生意社 / 隆众 / 中联金 / 卓创
─────────────────────────────────────────────
按用户要求: "中联金、隆众、卓创等数据库都要参考, 参考价格以最低为准"
- 同一品种从所有源抓价格 → 取 MIN → 标注哪个源是最低价
- 任一源抓不到时, 自动回退到其余源/兜底价, 绝不显示假基准价

各源覆盖度(以公开可爬为准):
  生意社 (100ppi.com): 硫磺vane+xhb / MAP基准价列表 / YP化工快讯 / LFP基准价
  隆众资讯 (oilchem.net): 硫磺长江港 / MAP湖北55%粉 / DAP 64%出厂
  中联金 (zljsteel.com 静态聚合): 硫磺港口(镇江港/大丰港) + 山东炼厂报价
  卓创资讯 (sci99.com): 公开页无目标品种日价 → 标记"无公开数据"

调用方传入 get_html(url)->str|None (app.py 用 safe_get, generate_static 用 requests.get)。
"""

import re
from datetime import datetime


# ── 隆众资讯 ──
def _fetch_oilchem_home_article_url(get_html, today=None):
    """从隆众磷酸一铵专区找最新一篇「磷铵市场早间提示」文章URL。
    URL 形如: https://www.oilchem.net/26-0730-08-<hash>.html
    返回 (url, date_str 'YYYY-MM-DD') 或 (None, None)。
    """
    today = today or datetime.now().date()
    html = get_html("https://fert.oilchem.net/fert/ammoniumphosphate.shtml")
    if not html or len(html) < 500:
        return None, None
    # 抓所有 <a href="...">[磷铵]：磷铵市场早间提示（YYYYMMDD）</a>
    # 先宽松匹配, 过滤掉超长非油化 URL
    candidates = re.findall(
        r'href="(https?://(?:www\.)?oilchem\.net/\d{2}-\d{4}-\d{2}-[a-f0-9]{16}\.html)"[^>]*>\s*\[?磷铵\]?[^<]{0,40}早间提示',
        html,
    )
    if not candidates:
        return None, None
    url = candidates[0]
    dm = re.search(r"/(\d{2})-(\d{4})-(\d{2})-", url)
    if not dm:
        return url, None
    yy, mm, dd = "20" + dm.group(1), dm.group(2), dm.group(3)
    return url, f"{yy}-{mm}-{dd}"


def _parse_oilchem_phosphate_table(html):
    """从隆众磷铵早间提示文章 HTML 解析硫磺长江港/MAP/DAP价格。
    返回 {key: price}, 长江港/MAP/DAP 任一缺失则该 key 不出现。
    """
    if not html:
        return {}
    out = {}

    # 1) 长江港硫磺: 文本 "长江港颗粒硫磺主流参考报价为9190元/吨" 或表格单元格
    m = re.search(r"长江港[颗]?硫磺主流参考报价为\s*(\d+(?:\.\d+)?)\s*元/吨", html)
    if m:
        out["sulfur_zhenjiang"] = float(m.group(1))
    else:
        # 表格行: <td>硫磺</td><td>长江港</td><td>数字</td>
        m = re.search(
            r"<td[^>]*>\s*硫磺\s*</td>\s*<td[^>]*>\s*长江港\s*</td>\s*<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>",
            html,
        )
        if m:
            out["sulfur_zhenjiang"] = float(m.group(1))

    # 2) 磷酸一铵 湖北地区 55%粉: 文本或表格
    m = re.search(r"湖北地区\s*\d{2,3}%\s*粉[^。\n]*?(\d+(?:\.\d+)?)\s*元/吨", html)
    if m:
        out["map_55"] = float(m.group(1))
    else:
        m = re.search(
            r"<td[^>]*>\s*磷酸一铵\s*</td>\s*<td[^>]*>\s*湖北地区\s*</td>\s*<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>",
            html,
        )
        if m:
            out["map_55"] = float(m.group(1))

    # 3) 磷酸二铵 64% 出厂价(湖北或华东)
    m = re.search(
        r"(?:湖北地区|华东地区)[^\n。]*?64%[^\n。]*?(\d+(?:\.\d+)?)\s*元/吨", html
    )
    if m:
        out["dap_64"] = float(m.group(1))
    else:
        for region in ("湖北地区", "华东地区"):
            m = re.search(
                rf"<td[^>]*>\s*磷酸二铵\s*</td>\s*<td[^>]*>\s*{region}\s*</td>\s*<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>",
                html,
            )
            if m:
                out["dap_64"] = float(m.group(1))
                break

    return out


def scrape_oilchem_phosphate(get_html, today=None):
    """隆众资讯磷铵早间提示: 长江港硫磺 + 湖北MAP + 64%DAP 价格。
    返回 {'source': 'oilchem', 'date': 'YYYY-MM-DD', 'prices': {...}, 'url': '...'} 或 None。"""
    try:
        url, date_str = _fetch_oilchem_home_article_url(get_html, today)
        if not url:
            return None
        html = get_html(url)
        if not html:
            return None
        prices = _parse_oilchem_phosphate_table(html)
        if not prices:
            return None
        return {
            "source": "oilchem",
            "date": date_str,
            "url": url,
            "prices": prices,
        }
    except Exception:
        return None


# ── 卓创资讯 ──
def scrape_sci99_overview(get_html):
    """卓创资讯首页涨跌幅榜: 公开页通常不含目标品种具体日价, 但仍抓首页摘要做存档。
    返回 None 或 {'source': 'sci99', 'note': '...'}; 价格字段多为空(公开页限制)。
    """
    html = get_html("https://www.sci99.com/")
    if not html or len(html) < 500:
        return None
    # 首页有"涨跌幅排行榜", 但目标品种硫磺/黄磷/MAP/DAP 通常不在涨幅榜
    # 公开可抓数据有限, 主要作为来源存在性标识
    return {
        "source": "sci99",
        "note": "公开页仅含首页涨跌幅榜单, 硫磺/黄磷/MAP/DAP 日价需登录付费会员, 当前无公开数据",
        "prices": {},
    }


# ── 中联金硫磺 (静态聚合) ──
def get_zhonglianjin_sulfur_static(zlj_quotes):
    """中联金硫磺报价静态聚合(从外部传入 ZLJ_SULFUR_QUOTES)。
    返回 {'source':'zlj', 'prices': {'sulfur_zhenjiang': 港口参考价, ...}, 'refineries': [...], 'ports': [...]}"""
    out = {"source": "zlj", "prices": {}, "refineries": zlj_quotes.get("refineries", []), "ports": zlj_quotes.get("ports", [])}
    if zlj_quotes.get("ports"):
        p = zlj_quotes["ports"][0]
        out["prices"]["sulfur_zhenjiang"] = (p["price_low"] + p["price_high"]) / 2.0
    if zlj_quotes.get("reference_price"):
        out["prices"]["sulfur_zhenjiang"] = float(zlj_quotes["reference_price"])
    return out


# ── 聚合: 多源取最低价 ──
def aggregate_min_prices(source_prices_list, default_prices):
    """对每个品种从所有源价格中取 MIN 作为最终参考价, 并标注最低来源。
    source_prices_list: [{'source': 'name', 'prices': {key: val}}, ...]
    default_prices: 单源时的基准(生意社抓的); 用于完全没源时兜底
    返回: (final_prices, source_winner) 两个 dict。
    """
    final = {}
    winner = {}
    for key in default_prices:
        candidates = []  # (price, source_name)
        for sp in source_prices_list:
            p = (sp.get("prices") or {}).get(key)
            if p is not None and p > 0:
                candidates.append((float(p), sp.get("source", "?")))
        if candidates:
            lo = min(candidates, key=lambda x: x[0])
            final[key] = round(lo[0], 2)
            winner[key] = lo[1]
        else:
            # 无任何源 → 沿用 default (生意社单源结果)
            final[key] = default_prices.get(key, 0)
            winner[key] = "single_source_fallback"
    return final, winner


def build_source_breakdown(source_prices_list, default_prices):
    """为 UI 生成各品种的多源价格对照表, 用于显示在卡片上。
    返回: {key: {'sources': {'shengyishe': 4466.67, 'oilchem': 4450, ...}, 'min': 4450, 'winner': 'oilchem'}}
    """
    breakdown = {}
    for key in default_prices:
        sources = {}
        for sp in source_prices_list:
            p = (sp.get("prices") or {}).get(key)
            if p is not None and p > 0:
                sources[sp.get("source", "?")] = round(float(p), 2)
        if sources:
            lo_name = min(sources, key=sources.get)
            breakdown[key] = {
                "sources": sources,
                "min": sources[lo_name],
                "winner": lo_name,
            }
        else:
            breakdown[key] = {
                "sources": {},
                "min": default_prices.get(key, 0),
                "winner": "none",
            }
    return breakdown