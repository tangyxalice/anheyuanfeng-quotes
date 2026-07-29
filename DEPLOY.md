# 安和垣丰咨信自用网站 · 运行与异地更新指南

## 一、本机运行（最简单，推荐）
后端 `app.py`（Flask）提供网页，数据由爬虫从生意社抓取。
1. 安装依赖（首次）：`pip install -r requirements.txt`（需 Python 3.10+）
2. 启动：双击 `run.bat`（Windows）或 `bash run.sh`（Linux/Mac），或手动 `python app.py`
3. 浏览器打开 http://localhost:5000 即实时看板。

## 二、数据更新规则（按你的要求）
- **自动更新**：仅在 **周二、三、四、五**（工作日）运行，每小时重新爬取一次；**周一与周末不爬取**，保留最近一个交易日的数据。
- **手动更新**：任何时候点网页右上角「🔄 刷新」= 调用 `/api/refresh` 立即重新爬取。你不在电脑旁、异地登录时都可手动触发，不受星期限制。
- 爬虫失败（如生意社反爬"安全检查"拦截）时，**沿用上一次成功抓到的真实价**，不会回退到假基准价；一旦某次抓取成功即自动刷新为最新真实价。

## 三、爬虫与数据源（已优化，避免"失败回退"）
- 多源稳健解析：生意社 ①价格走势页 ②每日参考价日报页 ③磷化工频道，三路互补；带 3 次重试 + 共享 Session 预热 cookie，提升反爬通过率。
- 失败保护：每个品种独立判断是否抓到真实价；抓不到时取 `last_good_prices.json` 中"上次真实价"。该文件随每次成功抓取自动更新并落盘，重启不丢。
- 反爬说明：生意社对自动化请求有"安全检查"拦截，本地网络大部分时间可通过；偶发被拦时站点显示上次真实价（非造假），下一工作日自动恢复。

## 四、异地电脑登录更新数据
**方式 A（推荐，零网络配置）**：
1. 异地电脑安装 WorkBuddy，用**同一账号**登录。
2. 打开本任务（已同步/上传到云端，见第五节），在任务里运行 `run.bat` / `run.sh`（或 `python app.py`）。
3. 浏览器打开 http://localhost:5000 即看到最新行情；点「刷新」随时手动更新。

**方式 B（家中电脑常开）**：
1. 家中电脑一直运行着 `app.py`（网站在跑）。
2. 异地直接用浏览器打开家中电脑的网站地址（需家中电脑有公网 IP / 端口转发，或用 WorkBuddy「连接电脑」模式），点「刷新」即可更新——无需在异地跑代码。

## 五、把本任务上传/同步到云端（异地可见的前提）
- WorkBuddy 的任务记录本就存储在服务端（**同账号多端互通**）。要让**项目文件（app.py 等）也能在异地打开运行**，需在 WorkBuddy 中将本 workspace 同步/上传到云端：
  - 在 WorkBuddy 左侧任务/空间列表，对本任务选择「同步到云端 / 上传到云端」（按钮名以当前版本 UI 为准）。
  - 或在 Web 端 workbuddy 用同一账号登录，任务会自动同步。
- 同步后，任意电脑/手机用同一账号登录即可看到本任务并运行。
- 手机端：装 WorkBuddy App 同账号登录即可在任务列表看到；若看不到，多为账号不一致（iOS 用 Apple ID 快捷登录需先在 Web 端绑定同一邮箱）或需手动触发同步。

## 六、常用接口
- 首页：`/`
- 数据：`/api/data`
- 手动刷新（重新爬取）：`/api/refresh`
- 爬虫状态：`/api/scrape-status`

## 七、其他
- 静态快照（冻结数据）：`python generate_static.py` 会生成 `deploy/index.html`（数据冻结，仅供无 Python 环境时查看，不实时）。
- 数据持久化文件：`data_cache.json`（最近一次抓取结果）、`last_good_prices.json`（各品种"上次真实价"，防回退）。

## 八、部署到 Render 常驻云端（异地/手机随时看实时数据）
把 `app.py` 部署到 Render 免费 Web Service，云端 7×24 运行、自动爬数据；你拿到一个固定网址，异地电脑/手机浏览器直接打开就是最新行情，**不再依赖你自己的电脑开机**（彻底解决"之前的网址是冻结快照/打不开"的问题）。`app.py` 已适配云端：端口读 `$PORT`、爬虫线程模块加载即启动、`requirements.txt` 含 `gunicorn`。

### 准备（一次性）
1. 注册 Render 账号（render.com，可用 GitHub 登录）。
2. 把本项目推到 GitHub 仓库（需含：`app.py`、`templates/`、`requirements.txt`、`Procfile`、`render.yaml`、`runtime.txt`）。本目录已是完整可部署结构；本地新建空仓库后执行：
   ```
   git init
   git add app.py templates requirements.txt Procfile render.yaml runtime.txt
   git commit -m "安和垣丰咨信自用网站 实时后端"
   git remote add origin <你的GitHub仓库URL>
   git push -u origin main
   ```

### 在 Render 部署
3. Dashboard → New → Web Service → 连接上面的 GitHub 仓库。
4. 关键设置（基本会自动识别 `render.yaml`，可核对）：
   - Runtime: Python 3 ｜ Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app` ｜ Plan: Free
5. 点 Deploy，约 1–2 分钟构建完成，得到网址 `https://anheyuanfeng-quotes.onrender.com`（命名可在后台改）。

### 防止免费版休眠（重要）
免费 Web Service 15 分钟无流量会休眠，后台爬虫也随之暂停。用 UptimeRobot（uptimerobot.com，免费）每 5 分钟 ping 一次你的网址 `/` 保活：
- New Monitor → HTTP(s) → URL: `https://<你的网址>/` → Interval: 5 分钟。
保活后，云端后台线程持续按"周二~周五每小时"爬取，数据常新。

### 使用
- 任意设备浏览器打开网址即看实时看板。
- 手动刷新（任意时间，不受星期限制）：`https://<你的网址>/api/refresh`。

### 可选调整
- 想让云端 **每天都爬**（不止周二~周五）：把 `app.py` 第 434 行 `weekday in (1, 2, 3, 4)` 改为 `weekday in range(7)`，重新部署即可。
- 想更频繁更新：UptimeRobot 的 URL 指向 `/api/refresh`（间隔建议 ≥10 分钟，避免触发生意社反爬）。
- 注：云端磁盘为临时盘，每次重启会清空 `last_good_prices.json`，但进程启动即重新爬取，无影响。
