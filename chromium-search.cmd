@echo off
where py >nul 2>nul && goto :py
python "%~dp0chromium-search.py" %*
exit /b %errorlevel%
:py
py -3 "%~dp0chromium-search.py" %*
exit /b %errorlevel%
