@echo off
REM install.bat
REM Windows installation script for LunaBlue

echo ==================================================
echo LunaBlue Installation Script (Windows)
echo ==================================================
echo.

REM Check Node.js
echo Checking Node.js installation...
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo X Node.js not found. Please install from https://nodejs.org/
    exit /b 1
)

for /f "tokens=*" %%i in ('node -v') do set NODE_VERSION=%%i
echo OK Node.js: %NODE_VERSION%
echo.

REM Install dependencies
echo Installing Node.js dependencies...
call npm install
if %ERRORLEVEL% NEQ 0 (
    echo X Installation failed
    exit /b 1
)
echo OK Dependencies installed
echo.

REM Run setup
echo Running setup...
call npm run setup
if %ERRORLEVEL% NEQ 0 (
    echo X Setup failed
    exit /b 1
)
echo.

echo ==================================================
echo OK Installation completed successfully!
echo ==================================================
echo.
echo Next steps:
echo 1. Download models: npm run setup:models
echo 2. Build: npm run build
echo 3. Start: npm start
echo.
pause
