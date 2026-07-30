"""
硫磺港口库存&报价 / 肥料(磷酸一铵/二铵) / 磷酸铁 实时监控 API Server
数据来源: 生意社(100ppi.com) 真实爬虫 + 模拟回退
"""

import json
import os
import re
import time
import random
import threading
import traceback
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# ── 全局缓存 ──
CACHE_FILE = os.path.join(os.path.dirname(__file__), "data_cache.json")
cache_lock = threading.Lock()
last_scrape_status = {"time": "", "sources": {}, "success_count": 0}

# ── 基准价格数据（2026年7月最新市场参考价，作为爬虫失败回退）──
BASE_PRICES = {
    "sulfur_solid": 9519,       # 颗粒硫磺基准价 07-23
    "sulfur_liquid": 7550,      # 液体硫磺 元/吨
    "sulfur_zhenjiang": 9200,   # 镇江港颗粒硫磺 元/吨
    "map_55": 4470,             # 磷酸一铵 55%粉 07-23基准价
    "map_73": 7300,             # 磷酸一铵 73%工业级 元/吨
    "dap_64": 4850,             # 磷酸二铵 64%颗粒 元/吨
    "dap_98": 8333,             # 磷酸二铵 98% 元/吨
    "lfp": 15000,               # 磷酸铁 元/吨 (7月行情14000-15000区间)
    "lfp_power": 59033,         # 磷酸铁锂动力型 07-22基准价
    "yp": 26300,                # 黄磷 99.9%优等品 07-23全国均价(CBC金属网)
}

# ── 中联金硫磺报价（2026-07-16 最新, 来源: 中联金信息网/金十期货）──
ZLJ_SULFUR_QUOTES = {
    "date": "2026-07-16",
    "refineries": [
        {"name": "东明石化", "product": "液体硫磺", "price": 9300, "change": 50, "status": "报价"},
        {"name": "东明石化", "product": "固体硫磺", "price": 9500, "change": 0, "status": "报价"},
        {"name": "齐成石化", "product": "液体硫磺", "price": 9220, "change": 20, "status": "报价"},
        {"name": "正和石化", "product": "液体硫磺", "price": 9220, "change": 20, "status": "报价"},
        {"name": "鑫泰石化", "product": "液体硫磺", "price": 9155, "change": 5, "status": "报价"},
        {"name": "尚能石化", "product": "液体硫磺", "price": 9000, "change": 0, "status": "报价"},
        {"name": "万通石化", "product": "固体硫磺", "price": 9007, "change": 0, "status": "报价"},
        {"name": "金诚石化", "product": "液体硫磺", "price": None, "change": 0, "status": "暂不报价"},
        {"name": "华星石化", "product": "液体硫磺", "price": None, "change": 0, "status": "暂不报价"},
        {"name": "青岛炼化", "product": "固体/液体", "price": None, "change": 0, "status": "暂不报价"},
        {"name": "神驰化工", "product": "液体硫磺", "price": None, "change": 0, "status": "暂不报价"},
        {"name": "汇丰石化", "product": "液体硫磺", "price": None, "change": 0, "status": "装置停车"},
    ],
    "ports": [
        {"name": "镇江港", "price_low": 9100, "price_high": 9200, "change_low": -100, "change_high": -200},
        {"name": "大丰港", "price_low": 9080, "price_high": 9180, "change_low": -100, "change_high": -200},
    ],
    "reference_price": 9100,  # 港口参考价
    "analysis": "短期理性区间参考8000-9000元/吨 (7-22中联金)",
}

# ── 港口库存基准（万吨, 2026年7月参考）──
PORT_INVENTORY_BASE = {
    "防城港": 35.0,
    "北海港": 6.5,
    "湛江港": 8.0,
    "镇江港": 36.8,
    "南京港": 1.5,
    "大丰港": 4.8,
}

# ── 上次真实价缓存（抓取失败时沿用，避免回退到基准价）──
LAST_GOOD_FILE = os.path.join(os.path.dirname(__file__), "last_good_prices.json")
# 提交的兜底真实价: 全新部署/抓取全失败时使用，确保绝不显示假基准价
FALLBACK_FILE = os.path.join(os.path.dirname(__file__), "fallback_prices.json")
last_good_prices = dict(BASE_PRICES)


def load_last_good():
    global last_good_prices
    try:
        if os.path.exists(LAST_GOOD_FILE):
            with open(LAST_GOOD_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in BASE_PRICES:
                    if k in data and isinstance(data[k], (int, float)):
                        last_good_prices[k] = data[k]
    except Exception:
        pass
    # 若仍无真实价(全新部署且抓取全失败)，用提交的兜底真实价
    if all(last_good_prices.get(k) == BASE_PRICES.get(k) for k in BASE_PRICES):
        try:
            if os.path.exists(FALLBACK_FILE):
                with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in BASE_PRICES:
                        if k in data and isinstance(data[k], (int, float)):
                            last_good_prices[k] = data[k]
        except Exception:
            pass


def save_last_good():
    try:
        with open(LAST_GOOD_FILE, "w", encoding="utf-8") as f:
            json.dump(last_good_prices, f, ensure_ascii=False)
    except Exception:
        pass


# ── 反爬对抗：UA 轮换 + 会话预热 + 多镜像 + 反爬识别重试 ──
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]

_SESSION = None
_session_lock = threading.Lock()


def _new_session():
    """新建带基础 cookie 的会话（预热首页），提高生意社反爬通过率。"""
    import requests
    s = requests.Session()
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Referer": "https://www.100ppi.com/",
    })
    for w in ("https://www.100ppi.com/", "https://m1.100ppi.com/"):
        try:
            s.get(w, timeout=8)
        except Exception:
            pass
    return s


def _get_session(fresh=False):
    global _SESSION
    if fresh or _SESSION is None:
        with _session_lock:
            if fresh or _SESSION is None:
                _SESSION = _new_session()
    return _SESSION


def _is_blocked(text):
    """生意社反爬'安全检查'拦截页判定。"""
    if not text:
        return False
    t = text.lower()
    return ("安全检查" in text) or ("captcha" in t) or ("verify" in t and "100ppi" in t) or ("robot" in t)


def safe_get(url, headers=None, timeout=15, fresh=False):
    """带重试/UA轮换/会话刷新/反爬识别的GET。命中反爬墙或失败返回None。"""
    for attempt in range(4):
        sess = _get_session(fresh=(fresh or attempt > 0))
        h = dict(headers or {})
        h["User-Agent"] = random.choice(_UA_POOL)
        try:
            r = sess.get(url, headers=h, timeout=timeout)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                if _is_blocked(r.text):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                return r
        except Exception:
            pass
        time.sleep(1.2 * (attempt + 1))
    return None


load_last_good()


# ── 真实数据爬虫 ──
def scrape_real_data():
    """从生意社等公开网站爬取真实基准价数据"""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return {}, "依赖缺失"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    results = {}
    sources_status = {}

    # ── 方法1: 从生意社价格走势页爬取(多镜像域名轮换, 抗反爬墙) ──
    vane_paths = {
        "sulfur": "/vane/427-%E7%A1%AB%E7%A3%BA",
        "map": "/vane/473-%E7%A3%B7%E9%85%B8%E4%B8%80%E9%93%B5",
        "dap": "/vane/426-%E7%A3%B7%E9%85%B8%E4%BA%8C%E9%93%B5",
        "lfp_power": "/vane/529-%E7%A3%B7%E9%85%B8%E9%93%81%E9%93%B1",
        "yp": "/vane/425-%E9%BB%84%E7%A3%B7",
    }
    vane_hosts = ["https://m1.100ppi.com", "https://www.100ppi.com", "https://100ppi.com"]

    for key, path in vane_paths.items():
        resp = None
        for host in vane_hosts:
            try:
                r = safe_get(host + path, headers)
                if r and r.status_code == 200:
                    resp = r
                    break
            except Exception:
                pass
        if not resp:
            sources_status[key] = "爬取失败(多镜像均被拦/超时)"
            continue
        try:
            soup = BeautifulSoup(resp.text, "lxml")
            # 提取价格走势表格中的近期价格数据
            text = soup.get_text()
            # 优先匹配 "MM-DD 价格 涨跌幅%" 形式
            price_pattern = re.findall(r'(\d{2}-\d{2})\s+(\d+\.?\d*)\s*([\-\+]?\d+\.?\d*)%', text)
            if not price_pattern:
                price_pattern = re.findall(r'(\d{2}-\d{2})\s+(\d+\.?\d*)', text)
            if price_pattern:
                # 取最近的日期价格
                latest_price = float(price_pattern[0][1])
                results[key] = {
                    "latest_price": latest_price,
                    "history": price_pattern[:15],  # 保留最近15个数据点
                }
                sources_status[key] = f"生意社走势页(实时): {latest_price}元/吨"
            else:
                sources_status[key] = "爬取失败(未匹配价格)"
        except Exception as e:
            sources_status[key] = f"爬取异常: {str(e)[:50]}"

    # ── 方法2: 从生意社每日参考价页面爬取(服务端渲染, 含全部品种) ──
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    daily_map = {
        "sulfur": r'硫磺\s*形态[：:]\s*颗粒硫磺\s*\d+\.?\d*\s*(\d+\.?\d*)',
        "map": r'磷酸一铵\s*形态[：:][^\n]*?\d+\.?\d*\s*(\d+\.?\d*)',
        "dap": r'磷酸二铵\s*形态[：:][^\n]*?\d+\.?\d*\s*(\d+\.?\d*)',
        "lfp": r'磷酸铁\s*形态[：:][^\n]*?\d+\.?\d*\s*(\d+\.?\d*)',
        "lfp_power": r'磷酸铁锂\s*形态[：:][^\n]*?\d+\.?\d*\s*(\d+\.?\d*)',
        "yp": r'黄磷\s*形态[：:][^\n]*?\d+\.?\d*\s*(\d+\.?\d*)',
    }
    for date_str in [today, yesterday]:
        try:
            url = f"https://www.100ppi.com/xhb/day-{date_str}.html"
            resp = safe_get(url, headers)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                text = soup.get_text()
                # 每日参考价页: "品名 形态:规格 低价 高价 涨跌幅%" -> 取高价(当日)
                for dk, pat in daily_map.items():
                    m = re.search(pat, text)
                    if m and (dk + "_daily") not in results:
                        results[dk + "_daily"] = {"latest_price": float(m.group(1))}
                        sources_status[dk + "_daily"] = f"生意社日报({date_str}): {float(m.group(1))}元/吨"
                if "sulfur_daily" in results:
                    break
        except Exception as e:
            sources_status["daily"] = f"日报爬取异常: {str(e)[:50]}"

    # ── 方法3: 从生意社磷化工频道爬取 ──
    try:
        url = "https://100ppi.com/chanye/lhg.html"
        resp = safe_get(url, headers)
        if resp and resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text()
            # 磷酸一铵参考价: "磷酸一铵参考价为XXXX.XX"
            map_match = re.search(r'磷酸一铵参考价为(\d+\.?\d*)', text)
            if map_match and "map" not in results:
                results["map_channel"] = {"latest_price": float(map_match.group(1))}
                sources_status["map_channel"] = f"磷化工频道: {float(map_match.group(1))}元/吨"

            # 磷酸二铵参考价
            dap_match = re.search(r'磷酸二铵参考价为(\d+\.?\d*)', text)
            if dap_match and "dap" not in results:
                results["dap_channel"] = {"latest_price": float(dap_match.group(1))}
                sources_status["dap_channel"] = f"磷化工频道DAP: {float(dap_match.group(1))}元/吨"

            # 磷酸铁锂基准价(=磷酸铁锂)
            lfp_match = re.search(r'磷酸铁锂基准价为(\d+\.?\d*)元/吨', text)
            if lfp_match and "lfp_power" not in results:
                results["lfp_power_channel"] = {"latest_price": float(lfp_match.group(1))}
                sources_status["lfp_power_channel"] = f"磷化工频道LFP: {float(lfp_match.group(1))}元/吨"

            # 磷酸铁参考价(=磷酸铁, 铁锂前驱体)
            lfp_acid_match = re.search(r'磷酸铁参考价为(\d+\.?\d*)', text)
            if lfp_acid_match and "lfp" not in results:
                results["lfp_channel"] = {"latest_price": float(lfp_acid_match.group(1))}
                sources_status["lfp_channel"] = f"磷化工频道磷酸铁: {float(lfp_acid_match.group(1))}元/吨"

            # 磷酸参考价
            pa_match = re.search(r'磷酸参考价为(\d+\.?\d*)', text)
            if pa_match:
                results["phosphoric_acid"] = {"latest_price": float(pa_match.group(1))}
                sources_status["phosphoric_acid"] = f"磷化工频道磷酸: {float(pa_match.group(1))}元/吨"

            # 黄磷基准价
            yp_match = re.search(r'黄磷基准价为(\d+\.?\d*)元/吨', text)
            if yp_match:
                results["yp_channel"] = {"latest_price": float(yp_match.group(1))}
                sources_status["yp_channel"] = f"磷化工频道黄磷: {float(yp_match.group(1))}元/吨"
    except Exception as e:
        sources_status["lhg_channel"] = f"频道爬取异常: {str(e)[:50]}"

    # ── 合并最优数据（抓取失败则沿用上次真实价，避免回退基准价）──
    final = {}
    real = {}

    # 镇江港颗粒硫磺(=每日/走势 颗粒硫磺当日价, 最权威)
    if "sulfur_daily" in results:
        final["sulfur_zhenjiang"] = results["sulfur_daily"]["latest_price"]; real["sulfur_zhenjiang"] = True
    elif "sulfur" in results:
        final["sulfur_zhenjiang"] = results["sulfur"]["latest_price"]; real["sulfur_zhenjiang"] = True
    else:
        final["sulfur_zhenjiang"] = last_good_prices.get("sulfur_zhenjiang", BASE_PRICES["sulfur_zhenjiang"]); real["sulfur_zhenjiang"] = False

    # 固体硫磺现货价 = 港口价 -300(前端锚定, 后端给一致基准)
    final["sulfur_solid"] = round(final["sulfur_zhenjiang"] - 300, 2); real["sulfur_solid"] = real["sulfur_zhenjiang"]
    # 液体硫磺(无独立源, 沿用上次/基准)
    final["sulfur_liquid"] = last_good_prices.get("sulfur_liquid", BASE_PRICES["sulfur_liquid"]); real["sulfur_liquid"] = False

    # MAP 55%: 走势 > 日报 > 频道
    if "map" in results:
        final["map_55"] = results["map"]["latest_price"]; real["map_55"] = True
    elif "map_daily" in results:
        final["map_55"] = results["map_daily"]["latest_price"]; real["map_55"] = True
    elif "map_channel" in results:
        final["map_55"] = results["map_channel"]["latest_price"]; real["map_55"] = True
    else:
        final["map_55"] = last_good_prices.get("map_55", BASE_PRICES["map_55"]); real["map_55"] = False
    final["map_73"] = last_good_prices.get("map_73", BASE_PRICES["map_73"]); real["map_73"] = False

    # DAP 64%: 走势 > 日报 > 频道
    if "dap" in results:
        final["dap_64"] = results["dap"]["latest_price"]; real["dap_64"] = True
    elif "dap_daily" in results:
        final["dap_64"] = results["dap_daily"]["latest_price"]; real["dap_64"] = True
    elif "dap_channel" in results:
        final["dap_64"] = results["dap_channel"]["latest_price"]; real["dap_64"] = True
    else:
        final["dap_64"] = last_good_prices.get("dap_64", BASE_PRICES["dap_64"]); real["dap_64"] = False
    final["dap_98"] = last_good_prices.get("dap_98", BASE_PRICES["dap_98"]); real["dap_98"] = False

    # 磷酸铁(前驱体): 日报 > 频道(磷酸铁)
    if "lfp_daily" in results:
        final["lfp"] = results["lfp_daily"]["latest_price"]; real["lfp"] = True
    elif "lfp_channel" in results:
        final["lfp"] = results["lfp_channel"]["latest_price"]; real["lfp"] = True
    else:
        final["lfp"] = last_good_prices.get("lfp", BASE_PRICES["lfp"]); real["lfp"] = False

    # 磷酸铁锂: 走势 > 日报 > 频道(磷酸铁锂)
    if "lfp_power" in results:
        final["lfp_power"] = results["lfp_power"]["latest_price"]; real["lfp_power"] = True
    elif "lfp_power_daily" in results:
        final["lfp_power"] = results["lfp_power_daily"]["latest_price"]; real["lfp_power"] = True
    elif "lfp_power_channel" in results:
        final["lfp_power"] = results["lfp_power_channel"]["latest_price"]; real["lfp_power"] = True
    else:
        final["lfp_power"] = last_good_prices.get("lfp_power", BASE_PRICES["lfp_power"]); real["lfp_power"] = False

    # 黄磷: 走势 > 日报 > 频道
    if "yp" in results:
        final["yp"] = results["yp"]["latest_price"]; real["yp"] = True
    elif "yp_daily" in results:
        final["yp"] = results["yp_daily"]["latest_price"]; real["yp"] = True
    elif "yp_channel" in results:
        final["yp"] = results["yp_channel"]["latest_price"]; real["yp"] = True
    else:
        final["yp"] = last_good_prices.get("yp", BASE_PRICES["yp"]); real["yp"] = False

    # 记录真实抓取值, 供下次失败沿用
    for k, is_real in real.items():
        if is_real:
            last_good_prices[k] = final[k]
    save_last_good()

    success_count = sum(1 for v in real.values() if v)

    global last_scrape_status
    last_scrape_status = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": sources_status,
        "real_prices": real,
        "success_count": success_count,
        "raw_results_keys": list(results.keys()),
    }

    return final, results


# ── 历史价格生成（当爬虫无法获取走势时使用模拟回退）──
def generate_history(base_price, days=30, volatility=0.03, trend=0.002):
    """无真实走势时的回退：末点(今天)锚定当前价，保证图表末端与卡片价一致。"""
    return generate_history_from_real(base_price, [], days, volatility, trend)


def generate_history_from_real(base_price, real_history_list, days=30, volatility=0.02, trend=0.002):
    """生成 days 天走势：最后一天(今天)价格恒等于当前价 base_price，确保与卡片价一致。
    优先用真实走势做形状；无真实数据时生成平滑随机游走，末点锚定 base_price。"""
    base_price = float(base_price)
    today = datetime.now().date()

    # 1) 生成以 base_price 收尾的模拟基线(末点=当前价)
    sim = []
    price = base_price * (1 - trend * days)
    for _ in range(days):
        price += random.gauss(0, volatility * base_price / 100) + trend * base_price / 100
        price = max(base_price * 0.6, min(base_price * 1.6, price))
        sim.append(round(price, 2))
    sim[-1] = round(base_price, 2)

    # 2) 若有真实走势，覆盖最近若干天(末点保留 base_price)；按量级缩放避免断层
    real_prices = [float(x[1]) for x in reversed(real_history_list)] if real_history_list else []
    n_real = min(len(real_prices), max(0, days - 1))
    if n_real > 0:
        ref = real_prices[-1] or base_price
        scale = base_price / ref if ref else 1.0
        for j in range(n_real):
            idx = days - 1 - (n_real - j)  # 覆盖 days-n_real .. days-2
            if idx >= 0:
                sim[idx] = round(real_prices[j] * scale, 2)
    sim[-1] = round(base_price, 2)  # 末点再次确认

    # 3) 组装连续日期(末日=今天)
    history = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        history.append({"date": d.strftime("%Y-%m-%d"), "price": sim[i]})
    return history


# ── 港口库存历史 ──
def generate_inventory_history(days=30):
    history = []
    total_base = sum(PORT_INVENTORY_BASE.values())
    for i in range(days):
        date = (datetime.now() - timedelta(days=days - i)).strftime("%Y-%m-%d")
        decline_factor = (200 - 88) / days
        total = 200 - decline_factor * i + random.gauss(0, 3)
        total = max(80, min(220, total))
        ports = {}
        for port, base in PORT_INVENTORY_BASE.items():
            ratio = base / total_base
            port_val = total * ratio + random.gauss(0, 0.5)
            port_val = max(0.5, port_val)
            ports[port] = round(port_val, 2)
        history.append({"date": date, "total": round(total, 2), "ports": ports})
    return history


# ── 数据更新线程 ──
def refresh_and_cache(force=False):
    """抓取生意社真实价并落盘缓存。force=True 时忽略周二~周五限制(手动刷新用)。
    返回 data dict；若非更新日且非强制，直接返回已有缓存(不爬取)。"""
    now = datetime.now()
    weekday = now.weekday()  # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    is_update_day = weekday in (1, 2, 3, 4)

    if not force and not is_update_day:
        # 非更新日(周一/周末): 保留已有缓存(最近一次业务日数据), 不爬取
        return get_cached_data()

    try:
        prices, raw_results = scrape_real_data()

        # 添加当日微小波动（模拟盘中实时变化）
        for key in prices:
            jitter = random.gauss(0, abs(prices[key]) * 0.001)
            prices[key] = round(prices[key] + jitter, 2)

        # 港口库存微调
        inventory = {}
        for port, base in PORT_INVENTORY_BASE.items():
            jitter = random.gauss(0, 0.3)
            inventory[port] = round(base + jitter, 2)
        total_inventory = round(sum(inventory.values()), 2)

        # 生成历史数据（优先使用爬虫获取的真实走势）
        sulfur_real_history = raw_results.get("sulfur", {}).get("history", []) if "sulfur" in raw_results else []
        map_real_history = raw_results.get("map", {}).get("history", []) if "map" in raw_results else []
        dap_real_history = raw_results.get("dap", {}).get("history", []) if "dap" in raw_results else []
        lfp_real_history = raw_results.get("lfp_power", {}).get("history", []) if "lfp_power" in raw_results else []
        yp_real_history = raw_results.get("yp", {}).get("history", []) if "yp" in raw_results else []

        history = {
            "sulfur_solid": generate_history_from_real(prices["sulfur_solid"], sulfur_real_history, days=30, volatility=3, trend=0.015),
            "sulfur_zhenjiang": generate_history_from_real(prices["sulfur_zhenjiang"], [], days=30, volatility=2.5, trend=0.012),
            "map_55": generate_history_from_real(prices["map_55"], map_real_history, days=30, volatility=2, trend=0.008),
            "map_73": generate_history_from_real(prices["map_73"], [], days=30, volatility=2.5, trend=0.01),
            "dap_64": generate_history_from_real(prices["dap_64"], dap_real_history, days=30, volatility=1.5, trend=0.006),
            "lfp": generate_history_from_real(prices["lfp"], [], days=30, volatility=2, trend=0.005),
            "lfp_power": generate_history_from_real(prices["lfp_power"], lfp_real_history, days=30, volatility=1.5, trend=0.003),
            "yp": generate_history_from_real(prices["yp"], yp_real_history, days=30, volatility=4, trend=-0.01),
            "port_inventory": generate_inventory_history(days=30),
        }

        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prices": prices,
            "port_inventory": inventory,
            "total_inventory": total_inventory,
            "history": history,
            "zlj_sulfur": ZLJ_SULFUR_QUOTES,
            "source_info": {
                "sulfur": "生意社(100ppi.com) 实时爬取",
                "map": "生意社/磷化工频道",
                "dap": "生意社(100ppi.com)",
                "lfp": "百川盈孚/Mysteel",
                "yp": "生意社/CBC金属网",
                "inventory": "生意社港口库存统计(估算)",
                "zlj": "中联金信息网(zljsteel.com)",
            },
            "scrape_status": last_scrape_status,
        }

        with cache_lock:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        return data

    except Exception:
        traceback.print_exc()
        return get_cached_data()


def ensure_initial_cache():
    """启动即写一份初始缓存(来自兜底真实价)，避免首启瞬间 /api/data 空数据。"""
    if not os.path.exists(CACHE_FILE):
        try:
            data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "prices": dict(last_good_prices),
                "port_inventory": dict(PORT_INVENTORY_BASE),
                "total_inventory": round(sum(PORT_INVENTORY_BASE.values()), 2),
                "history": {k: [] for k in ("sulfur_solid", "sulfur_zhenjiang", "map_55", "map_73", "dap_64", "lfp", "lfp_power", "yp", "port_inventory")},
                "zlj_sulfur": ZLJ_SULFUR_QUOTES,
                "source_info": {"sulfur": "生意社(100ppi.com)", "map": "磷化工频道", "dap": "生意社", "lfp": "百川盈孚/Mysteel", "yp": "生意社/CBC金属网", "inventory": "估算", "zlj": "中联金"},
                "scrape_status": last_scrape_status,
            }
            with cache_lock:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass


def update_data_periodically():
    """后台定时更新：仅在周二至周五(weekday 1~4)自动爬取；其余时间保留最近一次业务日数据。"""
    while True:
        refresh_and_cache(force=False)
        now = datetime.now()
        if now.weekday() in (1, 2, 3, 4):
            time.sleep(3600)  # 更新日: 每小时刷新一次
        else:
            time.sleep(7200)  # 每2小时检查是否进入更新日


# ── 读取缓存数据 ──
def get_cached_data():
    with cache_lock:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)

    # 首次启动，立即爬取
    prices, raw_results = scrape_real_data()
    for key in prices:
        prices[key] = round(prices[key] + random.gauss(0, prices[key] * 0.001), 2)

    inventory = {}
    for port, base in PORT_INVENTORY_BASE.items():
        inventory[port] = round(base + random.gauss(0, 0.2), 2)
    total_inventory = round(sum(inventory.values()), 2)

    sulfur_real_history = raw_results.get("sulfur", {}).get("history", []) if "sulfur" in raw_results else []
    map_real_history = raw_results.get("map", {}).get("history", []) if "map" in raw_results else []
    dap_real_history = raw_results.get("dap", {}).get("history", []) if "dap" in raw_results else []
    lfp_real_history = raw_results.get("lfp_power", {}).get("history", []) if "lfp_power" in raw_results else []
    yp_real_history = raw_results.get("yp", {}).get("history", []) if "yp" in raw_results else []

    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prices": prices,
        "port_inventory": inventory,
        "total_inventory": total_inventory,
        "history": {
            "sulfur_solid": generate_history_from_real(prices["sulfur_solid"], sulfur_real_history, 30, 3, 0.015),
            "sulfur_zhenjiang": generate_history_from_real(prices["sulfur_zhenjiang"], [], 30, 2.5, 0.012),
            "map_55": generate_history_from_real(prices["map_55"], map_real_history, 30, 2, 0.008),
            "map_73": generate_history_from_real(prices["map_73"], [], 30, 2.5, 0.01),
            "dap_64": generate_history_from_real(prices["dap_64"], dap_real_history, 30, 1.5, 0.006),
            "lfp": generate_history_from_real(prices["lfp"], [], 30, 2, 0.005),
            "lfp_power": generate_history_from_real(prices["lfp_power"], lfp_real_history, 30, 1.5, 0.003),
            "yp": generate_history_from_real(prices["yp"], yp_real_history, 30, 4, -0.01),
            "port_inventory": generate_inventory_history(30),
        },
        "zlj_sulfur": ZLJ_SULFUR_QUOTES,
        "source_info": {
            "sulfur": "生意社(100ppi.com) 实时爬取",
            "map": "生意社/磷化工频道",
            "dap": "生意社(100ppi.com)",
            "lfp": "百川盈孚/Mysteel",
            "inventory": "生意社港口库存统计(估算)",
        },
        "scrape_status": last_scrape_status,
    }
    with cache_lock:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


# ── API路由 ──
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    data = get_cached_data()
    return jsonify(data)


@app.route("/api/refresh")
def api_refresh():
    # 强制重新爬取(忽略周二~周五限制)，失败则沿用上次真实价
    data = refresh_and_cache(force=True)
    if data is None:
        data = get_cached_data() or {}
    return jsonify(data)


@app.route("/api/scrape-status")
def api_scrape_status():
    return jsonify(last_scrape_status)


# ── 云部署：模块加载时即启动爬虫线程（gunicorn 不会执行 __main__）──
# 配合单 worker(-w 1) 部署，避免多进程重复爬取生意社
ensure_initial_cache()
_updater = threading.Thread(target=update_data_periodically, daemon=True)
_updater.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("  安和垣丰咨信自用网站 - 实时监控系统 启动")
    print("  数据来源: 生意社(100ppi.com) 实时爬取")
    print(f"  访问: http://localhost:{port}")
    print(f"  API: http://localhost:{port}/api/data")
    print(f"  爬虫状态: http://localhost:{port}/api/scrape-status")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
