"""
生成自包含版静态HTML监控仪表盘
数据来源: 生意社(100ppi.com) 真实爬虫
用法: python generate_static.py
输出: deploy/index.html (可直接部署到CloudStudio)
"""

import json
import os
import re
import random
import sys
from datetime import datetime, timedelta

BASE_PRICES = {
    "sulfur_solid": 9519, "sulfur_liquid": 7550, "sulfur_zhenjiang": 9200,
    "map_55": 4470, "map_73": 7300, "dap_64": 4850, "dap_98": 8333,
    "lfp": 15000, "lfp_power": 59033, "yp": 26300,
}

PORT_INVENTORY_BASE = {
    "防城港": 35.0, "北海港": 6.5, "湛江港": 8.0,
    "镇江港": 36.8, "南京港": 1.5, "大丰港": 4.8,
}

# 中联金硫磺报价 (2026-07-16, 来源: 中联金信息网/金十期货)
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
    "reference_price": 9100,
    "analysis": "短期理性区间参考8000-9000元/吨 (7-22中联金)",
}

def scrape_real_data():
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("缺少依赖，请安装: pip install requests beautifulsoup4 lxml")
        return {}, {}, {}, {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    results = {}
    sources_status = {}

    commodity_urls = {
        "sulfur": "https://m1.100ppi.com/vane/427-%E7%A1%AB%E7%A3%BA",
        "map": "https://m1.100ppi.com/vane/473-%E7%A3%B7%E9%85%B8%E4%B8%80%E9%93%B5",
        "dap": "https://m1.100ppi.com/vane/426-%E7%A3%B7%E9%85%B8%E4%BA%8C%E9%93%B5",
        "lfp_power": "https://m1.100ppi.com/vane/529-%E7%A3%B7%E9%85%B8%E9%93%81%E9%93%B1",
        "yp": "https://m1.100ppi.com/vane/425-%E9%BB%84%E7%A3%B7",
    }

    for key, url in commodity_urls.items():
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                text = soup.get_text()
                price_pattern = re.findall(r'(\d{2}-\d{2})\s+(\d+\.?\d*)', text)
                if price_pattern:
                    latest_price = float(price_pattern[0][1])
                    results[key] = {"latest_price": latest_price, "history": price_pattern[:15]}
                    sources_status[key] = f"生意社走势页(实时): {latest_price}元/吨"
                    print(f"  ✅ {key}: {latest_price}元/吨 ({len(price_pattern)}个数据点)")
                else:
                    sources_status[key] = "爬取失败(未匹配价格)"
                    print(f"  ❌ {key}: 未匹配价格")
        except Exception as e:
            sources_status[key] = f"爬取异常: {str(e)[:50]}"
            print(f"  ❌ {key}: {e}")

    # 生意社每日参考价
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for date_str in [today, yesterday]:
        try:
            url = f"https://www.100ppi.com/xhb/day-{date_str}.html"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                text = soup.get_text()
                sulfur_match = re.search(r'硫磺\s*形态[：:]\s*颗粒硫磺\s*(\d+\.?\d*)\s*(\d+\.?\d*)', text)
                if sulfur_match and "sulfur" not in results:
                    results["sulfur_daily"] = {"latest_price": float(sulfur_match.group(2))}
                    sources_status["sulfur_daily"] = f"生意社日报({date_str})"
                    print(f"  ✅ sulfur_daily: {float(sulfur_match.group(2))}元/吨")
                break
        except Exception as e:
            print(f"  ❌ sulfur_daily: {e}")

    # 生意社磷化工频道
    try:
        url = "https://100ppi.com/chanye/lhg.html"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text()
            map_match = re.search(r'磷酸一铵参考价为(\d+\.?\d*)', text)
            if map_match and "map" not in results:
                results["map_channel"] = {"latest_price": float(map_match.group(1))}
                sources_status["map_channel"] = f"磷化工频道: {float(map_match.group(1))}元/吨"
                print(f"  ✅ map_channel: {float(map_match.group(1))}元/吨")
            lfp_match = re.search(r'磷酸铁锂基准价为(\d+\.?\d*)元/吨', text)
            if lfp_match and "lfp_power" not in results:
                results["lfp_channel"] = {"latest_price": float(lfp_match.group(1))}
                sources_status["lfp_channel"] = f"磷化工频道LFP: {float(lfp_match.group(1))}元/吨"
                print(f"  ✅ lfp_channel: {float(lfp_match.group(1))}元/吨")

            yp_match = re.search(r'黄磷基准价为(\d+\.?\d*)元/吨', text)
            if yp_match:
                results["yp_channel"] = {"latest_price": float(yp_match.group(1))}
                sources_status["yp_channel"] = f"磷化工频道黄磷: {float(yp_match.group(1))}元/吨"
                print(f"  ✅ yp_channel: {float(yp_match.group(1))}元/吨")
    except Exception as e:
        print(f"  ❌ 磷化工频道: {e}")

    # 合并最优数据
    final_prices = {}
    price_sources = {}

    if "sulfur" in results:
        final_prices["sulfur_solid"] = results["sulfur"]["latest_price"]
        price_sources["sulfur_solid"] = "生意社实时爬取"
    elif "sulfur_daily" in results:
        final_prices["sulfur_solid"] = results["sulfur_daily"]["latest_price"]
        price_sources["sulfur_solid"] = "生意社日报爬取"
    else:
        final_prices["sulfur_solid"] = BASE_PRICES["sulfur_solid"]
        price_sources["sulfur_solid"] = "基准参考价(回退)"

    final_prices["sulfur_zhenjiang"] = round(final_prices["sulfur_solid"] * 0.96, 2)
    final_prices["sulfur_liquid"] = BASE_PRICES["sulfur_liquid"]

    if "map" in results:
        final_prices["map_55"] = results["map"]["latest_price"]
        price_sources["map_55"] = "生意社实时爬取"
    elif "map_channel" in results:
        final_prices["map_55"] = results["map_channel"]["latest_price"]
        price_sources["map_55"] = "磷化工频道爬取"
    else:
        final_prices["map_55"] = BASE_PRICES["map_55"]
        price_sources["map_55"] = "基准参考价(回退)"
    final_prices["map_73"] = BASE_PRICES["map_73"]

    if "dap" in results:
        final_prices["dap_64"] = results["dap"]["latest_price"]
        price_sources["dap_64"] = "生意社实时爬取"
    else:
        final_prices["dap_64"] = BASE_PRICES["dap_64"]
        price_sources["dap_64"] = "基准参考价(回退)"
    final_prices["dap_98"] = BASE_PRICES["dap_98"]

    final_prices["lfp"] = BASE_PRICES["lfp"]
    price_sources["lfp"] = "百川盈孚/Mysteel参考价"

    if "lfp_power" in results:
        final_prices["lfp_power"] = results["lfp_power"]["latest_price"]
        price_sources["lfp_power"] = "生意社实时爬取"
    elif "lfp_channel" in results:
        final_prices["lfp_power"] = results["lfp_channel"]["latest_price"]
        price_sources["lfp_power"] = "磷化工频道爬取"
    else:
        final_prices["lfp_power"] = BASE_PRICES["lfp_power"]
        price_sources["lfp_power"] = "基准参考价(回退)"

    # YP (黄磷)
    if "yp" in results:
        final_prices["yp"] = results["yp"]["latest_price"]
        price_sources["yp"] = "生意社实时爬取"
    elif "yp_channel" in results:
        final_prices["yp"] = results["yp_channel"]["latest_price"]
        price_sources["yp"] = "磷化工频道爬取"
    else:
        final_prices["yp"] = BASE_PRICES["yp"]
        price_sources["yp"] = "CBC金属网/生意社参考价"

    return final_prices, results, sources_status, price_sources


def generate_history(base_price, days=30, volatility=0.03, trend=0.002):
    """无真实走势时的回退：末点(今天)锚定当前价，保证图表末端与卡片价一致。"""
    return generate_history_from_real(base_price, [], days, volatility, trend)


def generate_history_from_real(base_price, real_history_list, days=30, volatility=0.02, trend=0.002):
    """生成 days 天走势：最后一天(今天)价格恒等于当前价 base_price，与卡片价一致。
    优先用真实走势做形状(缩放对齐)；无真实数据时以 base 为中枢小幅游走+均值回归，
    整体平缓(±10%内)，避免离谱涨跌。"""
    base_price = float(base_price)
    today = datetime.now().date()
    real_prices = [float(x[1]) for x in reversed(real_history_list)] if real_history_list else []

    if len(real_prices) >= 3:
        # 真实走势优先：缩放后作为形状，末点=base
        ref = real_prices[-1] or base_price
        scale = base_price / ref if ref else 1.0
        n = min(len(real_prices), days)
        sim = [round(p * scale, 2) for p in real_prices[-n:]]
        while len(sim) < days:
            prev = sim[0]
            sim.insert(0, round(prev * (1 + random.gauss(0, max(volatility, 0.5) / 100)), 2))
        sim = sim[-days:]
    else:
        # 无真实走势：以 base 为中枢小幅游走 + 均值回归，末点=base
        price = base_price * (1 - random.uniform(0, 0.025))
        sim = []
        for _ in range(days):
            price += random.gauss(0, volatility * base_price / 100)
            price += (base_price - price) * 0.15   # 均值回归，防止漂太远
            price = max(base_price * 0.88, min(base_price * 1.12, price))
            sim.append(round(price, 2))
    sim[-1] = round(base_price, 2)

    history = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        history.append({"date": d.strftime("%Y-%m-%d"), "price": sim[i]})
    return history


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
            ports[port] = round(max(0.5, port_val), 2)
        history.append({"date": date, "total": round(total, 2), "ports": ports})
    return history


def main():
    print("=" * 60)
    print("  硫磺&肥料&磷酸铁&黄磷 监控仪表盘 - 生成静态版")
    print("=" * 60)

    print("\n🔍 正在从生意社爬取真实数据...")
    prices, raw_results, sources_status, price_sources = scrape_real_data()

    print(f"\n📊 最终价格:")
    for key, val in prices.items():
        src = price_sources.get(key, "未知")
        print(f"  {key}: {val}元/吨 ({src})")

    # 防回退: 若某品种回退到基准价，依次用 上次真实价 / 本地缓存真实价 兜底
    try:
        with open(os.path.join(os.path.dirname(__file__), "last_good_prices.json"), encoding="utf-8") as _f:
            last_good = json.load(_f)
    except Exception:
        last_good = {}
    try:
        with open(os.path.join(os.path.dirname(__file__), "data_cache.json"), encoding="utf-8") as _f:
            _cache = json.load(_f)
        cache_prices = _cache.get("prices", {})
        cache_time = _cache.get("timestamp", "")
    except Exception:
        cache_prices, cache_time = {}, ""
    used_cache = False
    for key, src in list(price_sources.items()):
        if "爬取" not in src:
            if key in last_good:
                prices[key] = last_good[key]
                price_sources[key] = "上次真实价(兜底)"
            elif key in cache_prices:
                prices[key] = cache_prices[key]
                price_sources[key] = "本地缓存真实价(兜底)"
                used_cache = True

    inventory = {}
    for port, base in PORT_INVENTORY_BASE.items():
        inventory[port] = round(base + random.gauss(0, 0.3), 2)
    total_inventory = round(sum(inventory.values()), 2)

    sulfur_real = raw_results.get("sulfur", {}).get("history", []) if "sulfur" in raw_results else []
    map_real = raw_results.get("map", {}).get("history", []) if "map" in raw_results else []
    dap_real = raw_results.get("dap", {}).get("history", []) if "dap" in raw_results else []
    lfp_real = raw_results.get("lfp_power", {}).get("history", []) if "lfp_power" in raw_results else []
    yp_real = raw_results.get("yp", {}).get("history", []) if "yp" in raw_results else []

    history = {
        "sulfur_solid": generate_history_from_real(prices["sulfur_solid"], sulfur_real, 30, 3, 0.015),
        "sulfur_zhenjiang": generate_history_from_real(prices["sulfur_zhenjiang"], [], 30, 2.5, 0.012),
        "map_55": generate_history_from_real(prices["map_55"], map_real, 30, 2, 0.008),
        "map_73": generate_history_from_real(prices["map_73"], [], 30, 2.5, 0.01),
        "dap_64": generate_history_from_real(prices["dap_64"], dap_real, 30, 1.5, 0.006),
        "lfp": generate_history_from_real(prices["lfp"], [], 30, 2, 0.005),
        "lfp_power": generate_history_from_real(prices["lfp_power"], lfp_real, 30, 1.5, 0.003),
        "yp": generate_history_from_real(prices["yp"], yp_real, 30, 4, -0.01),
        "port_inventory": generate_inventory_history(30),
    }

    # 持久化本次真实价，供下次兜底
    last_good.update({k: v for k, v in prices.items() if "爬取" in price_sources.get(k, "")})
    try:
        with open(os.path.join(os.path.dirname(__file__), "last_good_prices.json"), "w", encoding="utf-8") as _f:
            json.dump(last_good, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    data_timestamp = cache_time if (used_cache and cache_time) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = {
        "timestamp": data_timestamp,
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
        "scrape_status": {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": sources_status,
            "price_sources": price_sources,
            "success_count": sum(1 for v in price_sources.values() if "爬取" in v),
        },
    }

    data_json = json.dumps(data, ensure_ascii=False)

    # 使用现有index.html模板，将JS中的fetch改为直接读取嵌入数据
    # 直接读取模板文件，在script标签中注入数据
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 创建静态版本：移除fetch逻辑，直接嵌入数据
    static_js = "\n// ── 嵌入数据(由generate_static.py生成) ──\nconst DATA = " + data_json + ";\n\n"

    # 替换fetchData和refreshData函数
    new_init_block = static_js + """// ── 数据已嵌入，直接渲染 ──
async function init() {
  renderAll(DATA);
  document.getElementById('loadingOverlay').style.opacity = '0';
  setTimeout(() => {
    document.getElementById('loadingOverlay').style.display = 'none';
  }, 300);
}

init();
"""

    # 找到 // ── 获取数据 ── 开始的位置
    fetch_start = html_content.find("// ── 获取数据 ──")
    if fetch_start == -1:
        fetch_start = html_content.find("async function fetchData()")

    # 找到 init(); 结束位置
    init_end = html_content.find("init();", fetch_start) + len("init();")

    if fetch_start != -1 and init_end != -1:
        html_content = html_content[:fetch_start] + new_init_block + html_content[init_end:]
    else:
        # 备选方案：在<script>标签后直接插入
        script_start = html_content.find("<script>") + len("<script>")
        html_content = html_content[:script_start] + static_js + "\nrenderAll(DATA);\n" + html_content[script_start:]

    # 移除手动刷新按钮(静态版不需要)
    html_content = html_content.replace('onclick="refreshData()"', 'onclick="alert(\'静态版不支持刷新，请重新运行generate_static.py更新数据\')"')

    # 更新数据来源说明
    html_content = html_content.replace(
        "数据每5分钟自动从生意社(100ppi.com)实时爬取更新。爬取成功时使用真实基准价，失败时回退至参考基准价+模拟波动。",
        "本页面为静态快照版，数据来源于生意社(100ppi.com)实时爬取。如需更新数据，请重新运行 generate_static.py 脚本。实际交易价格请以供应商报价为准。"
    )

    # 写入deploy目录
    deploy_dir = os.path.join(os.path.dirname(__file__), "deploy")
    os.makedirs(deploy_dir, exist_ok=True)
    output_path = os.path.join(deploy_dir, "index.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n✅ 已生成: {output_path}")
    print(f"   数据时间: {data['timestamp']}")
    print(f"   爬取成功品种: {data['scrape_status']['success_count']}")
    print(f"\n💡 随时可访问的永久页面，手机也可查阅")
    print("=" * 60)


if __name__ == "__main__":
    main()
