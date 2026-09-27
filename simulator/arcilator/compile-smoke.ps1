$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

foreach ($tool in @('firtool', 'arcilator', 'opt', 'llc', 'cl.exe', 'python')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is missing from PATH. Open a Visual Studio Developer PowerShell with CIRCT/LLVM bin on PATH."
    }
}

$arcDir = Split-Path (Get-Command arcilator).Source
$headerGenerator = Join-Path $arcDir 'arcilator-header-cpp.py'
if (-not (Test-Path $headerGenerator)) { throw "Missing $headerGenerator" }

& firtool GsimSmoke.fir --ir-hw -o GsimSmoke.win.mlir
if ($LASTEXITCODE -ne 0) { throw 'firtool failed to lower GsimSmoke.fir' }
& arcilator GsimSmoke.win.mlir --state-file=GsimSmoke.json -o GsimSmoke.ll
if ($LASTEXITCODE -ne 0) { throw 'Arcilator failed to compile GsimSmoke.mlir' }
& opt -O3 -S GsimSmoke.ll -o GsimSmoke.opt.ll
if ($LASTEXITCODE -ne 0) { throw 'LLVM opt failed' }
& llc -O3 --filetype=obj GsimSmoke.opt.ll -o GsimSmoke.obj
if ($LASTEXITCODE -ne 0) { throw 'LLVM llc failed' }

& python $headerGenerator GsimSmoke.json --view-depth 1 |
    Set-Content -Encoding utf8 GsimSmoke_arc.h
if ($LASTEXITCODE -ne 0) { throw 'Arcilator C++ header generation failed' }
& cl.exe /nologo /std:c++17 /EHsc /O2 "/I$arcDir" smoke.cpp GsimSmoke.obj /Fe:GsimSmoke.exe
if ($LASTEXITCODE -ne 0) { throw 'MSVC failed to build the Arcilator harness' }
& .\GsimSmoke.exe
if ($LASTEXITCODE -ne 0) { throw 'Arcilator smoke test failed' }
