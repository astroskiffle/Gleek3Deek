@echo off
setlocal
cd /d "%~dp0"

for %%F in (main.py requirements.txt requirements-build.txt gleek3deek.spec) do (
    if not exist "%%F" (
        echo.
        echo Missing file: %%F
        echo Keep build_exe.bat in the SAME folder as: main.py, requirements.txt, requirements-build.txt, gleek3deek.spec
        echo ^(download or clone the whole project, not just this script^)
        pause
        exit /b 1
    )
)

rem Usage:  build_exe.bat          -> dist\Gleek3Deek.exe  (single file)
rem         build_exe.bat onedir   -> dist\Gleek3Deek\     (folder, starts faster)
if /i "%1"=="onedir" set "GLEEK_ONEDIR=1"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo Python 3.10-3.12 was not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
    echo Creating build environment...
    %PY% -m venv .venv-build || goto :fail
)
call ".venv-build\Scripts\activate.bat"

python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt -r requirements-build.txt || goto :fail
echo Installing optional FBX/DAE/LWO support ^(safe to fail^)...
python -m pip install assimp-py

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller --noconfirm --clean gleek3deek.spec || goto :fail

echo.
if defined GLEEK_ONEDIR ( echo Done: dist\Gleek3Deek\Gleek3Deek.exe ) else ( echo Done: dist\Gleek3Deek.exe )
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up for the first error message.
pause
exit /b 1
