@echo off
where py >nul 2>nul && goto :py
python "%~dp0chromium_search.py" %*
exit /b %errorlevel%
:py
py -3 "%~dp0chromium_search.py" %*
exit /b %errorlevel%
