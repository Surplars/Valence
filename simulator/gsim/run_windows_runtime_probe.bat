@echo off
setlocal
cd /d "%~dp0"
where clang++.exe >nul 2>&1
if errorlevel 1 (
    echo clang++.exe not found. Run this from an MSYS2 CLANG64 environment with Clang 19 or newer.
    exit /b 1
)

echo Building GSIM-generated smoke model...
clang++ -std=c++20 -O2 -I smoke smoke\GsimSmoke0.cpp smoke\smoke.cpp -o smoke.exe
if errorlevel 1 exit /b 1
smoke.exe
if errorlevel 1 exit /b 1

echo Windows native GSIM-generated model runtime probe passed.
