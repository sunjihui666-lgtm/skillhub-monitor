@echo off
REM ============================================================
REM  SkillHub 下载量看板 · 一键启动（Windows）
REM  双击即可：准备环境 -> 装依赖 -> 起服务 -> 开浏览器
REM ============================================================
cd /d "%~dp0"
setlocal enabledelayedexpansion

set HOST=127.0.0.1
set PORT=8787
set VENV=%~dp0.venv
set PY=%VENV%\Scripts\python.exe

REM ---- 找 Python ----
set PYBASE=
for %%P in (python py) do (
  if not defined PYBASE (
    %%P -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1 && set PYBASE=%%P
  )
)
if not defined PYBASE (
  echo [看板] 未找到 Python 3.8+，请先安装：https://www.python.org/downloads/
  pause & exit /b 1
)

REM ---- 建虚拟环境 ----
if not exist "%PY%" (
  echo [看板] 首次运行，创建虚拟环境...
  %PYBASE% -m venv "%VENV%"
)

REM ---- 装依赖 ----
"%PY%" -c "import requests" >nul 2>&1
if errorlevel 1 (
  echo [看板] 安装依赖 requests...
  "%PY%" -m pip install -q --disable-pip-version-check requests
)

REM ---- 启动 + 开浏览器 ----
echo [看板] 启动本地服务：http://%HOST%:%PORT%/
start "" http://%HOST%:%PORT%/
"%PY%" serve.py --host %HOST% --port %PORT%

pause
