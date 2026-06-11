@echo off
title AI Router
echo Starting AI Router...
echo.
echo Once started, your browser will open automatically.
echo To stop the app, close this window.
echo.
cd /d C:\Users\kirkk\Projects\ai-router
set PYTHONPATH=C:\Users\kirkk\Projects\ai-router
C:\Users\kirkk\AppData\Local\Programs\Python\Python313\python.exe -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause