@echo off

echo Starting automation browser...

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
--remote-debugging-port=9222 ^
--user-data-dir=C:\ChromeAutomation

timeout /t 2 >nul

echo Running property lookup...
python property_lookup.py

echo Running quote automation...
python main.py

echo Closing automation browser...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9222') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Finished!

timeout /t 2 >nul

pause