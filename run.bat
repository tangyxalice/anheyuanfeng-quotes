@echo off
cd /d %~dp0
echo ============================================
echo   安和垣丰咨信自用网站 - 行情监控系统
echo   正在启动... (Ctrl+C 退出)
echo ============================================
pip install -r requirements.txt >nul 2>&1
python app.py
pause
