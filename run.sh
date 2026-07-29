#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  安和垣丰咨信自用网站 - 行情监控系统"
echo "  正在启动... (Ctrl+C 退出)"
echo "============================================"
pip3 install -r requirements.txt >/dev/null 2>&1
python3 app.py
