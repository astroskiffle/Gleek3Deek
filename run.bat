@echo off
setlocal
cd /d "%~dp0"

for %%F in (main.py formats.py analysis.py cli.py matcap.py gallery.py environment.py panels.py requirements.txt) do (
    if not exist "%%F" (
        echo.
        echo Missing file: %%F
        echo Keep run.bat in the SAME folder as: main.py, formats.py, analysis.py, cli.py, matcap.py, gallery.py, environment.py, panels.py, requirements.txt
        echo ^(download or clone the whole project, not just this script^)
        pause
        exit /b 1
    )
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo Python 3.9+ was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv || ( echo Failed to create virtual environment. & pause & exit /b 1 )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.gleek_installed" (
    echo Installing required packages ^(first run only, this can take a few minutes^)...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt || ( echo Install failed. & pause & exit /b 1 )
    echo Installing optional FBX/DAE/LWO support ^(safe to fail^)...
    python -m pip install assimp-py
    echo ok> ".venv\.gleek_installed"
)

python main.py %*
if errorlevel 1 pause
