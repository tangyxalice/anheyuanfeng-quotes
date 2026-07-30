"""
共享反爬模块 — UA轮换 + 会话预热 + 反爬识别 + 多镜像重试
─────────────────────────────────────────────────────────
供 generate_static.py 和 app.py 共用，避免两份代码漂移。

核心函数:
  safe_get(url, headers=None, timeout=15, fresh=False) -> requests.Response | None
  make_get_text(headers=None) -> callable(url) -> str | None   # 适配 history_scraper / multi_source_scraper 的 get_text 接口
"""

import random
import time
import threading

# ── UA 池（真实浏览器指纹，覆盖 Win/Mac/Linux/Mobile）──
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]

# ── 标准请求头（模拟浏览器完整行为）──
_BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.100ppi.com/",
    "Upgrade-Insecure-Requests": "1",
}

# ── 会话管理（线程安全，带 cookie 预热）──
_SESSION = None
_session_lock = threading.Lock()


def _new_session():
    """新建带基础 cookie 的会话（预热首页），提高生意社反爬通过率。"""
    try:
        import requests
    except ImportError:
        return None
    s = requests.Session()
    s.headers.update(_BASE_HEADERS)
    # 预热: 先访问首页拿 cookie
    for warmup_url in ("https://www.100ppi.com/", "https://m1.100ppi.com/"):
        try:
            s.get(warmup_url, timeout=8)
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
    return (
        "安全检查" in text
        or "captcha" in t
        or ("verify" in t and "100ppi" in t)
        or "robot" in t
        or len(text) < 700  # 空白页/极短响应 = 被掐
    )


def safe_get(url, headers=None, timeout=15, fresh=False):
    """带重试/UA轮换/会话刷新/反爬识别的GET。命中反爬墙或失败返回None。

    - 4 次重试，每次换 UA + 刷新 session
    - 命中反爬墙时指数退避 (1.2s, 2.4s, 3.6s, 4.8s)
    - 自动检测空白页/安全检查页
    """
    try:
        import requests
    except ImportError:
        return None

    for attempt in range(4):
        sess = _get_session(fresh=(fresh or attempt > 0))
        if sess is None:
            # requests 不可用时直接用 requests.get 兜底
            try:
                h = dict(_BASE_HEADERS)
                h.update(headers or {})
                h["User-Agent"] = random.choice(_UA_POOL)
                r = requests.get(url, headers=h, timeout=timeout)
                if r.status_code == 200 and not _is_blocked(r.text):
                    r.encoding = r.apparent_encoding or "utf-8"
                    return r
            except Exception:
                pass
        else:
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


def make_get_text(headers=None):
    """返回一个 (url) -> str|None 的函数，适配 history_scraper / multi_source_scraper 的 get_text 接口。"""
    def _get_text(url):
        r = safe_get(url, headers=headers, timeout=15)
        if r and r.status_code == 200 and len(r.text) > 500:
            return r.text
        return None
    return _get_text


# ── 新闻列表页配置: 提取当日参考价(反爬较弱, 成功率高) ──
# 这些页面在 history_scraper.py 中用于历史数据，这里用于提取最新一日价格
NEWS_LIST_SOURCES = {
    "yp": {
        "url": "https://chem.100ppi.com/kx/list-1170-13-1.html",
        # "7月30日黄磷为27196.00" — 注意排除"与7月1日(...)"的对比句
        "regex": r"(\d{1,2})月(\d{1,2})日黄磷为(\d+\.?\d*)",
    },
    "map_55": {
        "url": "https://map.100ppi.com/news/list--1217-1.html",
        "regex": r"(\d{1,2})月(\d{1,2})日[^\n<]*?磷酸一铵基准价为(\d+\.?\d*)元/吨",
    },
    "lfp_power": {
        "url": "https://lfp.100ppi.com/news/list--1217-1.html",
        "regex": r"(\d{1,2})月(\d{1,2})日[^\n<]*?磷酸铁锂基准价为(\d+\.?\d*)元/吨",
    },
}


def scrape_news_list_prices(get_text=None):
    """从新闻列表页提取各品种最新一日参考价。

    返回 {key: {"latest_price": float, "date": "M月D日"}}，提取失败的 key 不出现。
    get_text: 可选的自定义取文本函数；默认用 safe_get。
    """
    import re
    from datetime import datetime

    if get_text is None:
        get_text = make_get_text()

    today = datetime.now().date()
    result = {}

    for key, cfg in NEWS_LIST_SOURCES.items():
        try:
            text = get_text(cfg["url"])
            if not text:
                continue
            matches = re.findall(cfg["regex"], text)
            if not matches:
                continue
            # 取第一条(最新日)的价格
            mm, dd, price = int(matches[0][0]), int(matches[0][1]), float(matches[0][2])
            if price <= 0:
                continue
            result[key] = {
                "latest_price": price,
                "date": f"{mm}月{dd}日",
            }
        except Exception:
            continue

    return result
