@echo off
echo Installing d2t with GUI dependencies...
pip install -e "%~dp0.[gui]"
echo.
echo Done! Double-click run_d2t.bat to start the app.
pause
