@echo off
pushd "C:\Users\tangYX\WorkBuddy\2026-07-23-20-37-14"
git remote set-url origin https://github.com/tangyxalice/anheyuanfeng-quotes.git 2>nul || git remote add origin https://github.com/tangyxalice/anheyuanfeng-quotes.git
git push -u origin master
pause
