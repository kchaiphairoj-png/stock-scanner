@echo off
chcp 65001 >nul
title Stock Breakout Scanner
echo.
echo ============================================
echo    Stock Breakout Scanner
echo ============================================
echo.
echo  เปิด browser ที่ http://localhost:8501
echo  ปิด window นี้เพื่อหยุดการทำงาน (Ctrl+C)
echo.
cd /d "%~dp0"
python -m streamlit run app.py --browser.gatherUsageStats=false
echo.
echo ============================================
echo  หยุดทำงานแล้ว — กด Enter เพื่อปิด
pause >nul
