#!/usr/bin/env bash
# Source the approved workspace toolchain environment before invoking.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
original=${1:?original clean pinned GSIM source required}
output=${2:?fresh absolute output directory required}
revision=93b8cd23edd3228807c4f2a08c19c3936a463cb2
[[ $(git -C "$original" rev-parse HEAD) == "$revision" ]]
[[ -z $(git -C "$original" status --porcelain --untracked-files=all) ]]
[[ ! -e "$output" ]]
mkdir -p "$output/source"
git -C "$original" archive "$revision" | tar -x -C "$output/source"
(cd "$output/source" && git apply --check "$root/simulator/gsim/tool_fixes/init-byte-span.patch" && git apply "$root/simulator/gsim/tool_fixes/init-byte-span.patch")
make -C "$output/source" -j2 CXX="${GSIM_CXX:?pinned clang19 required}" GSIM_VERSION=93b8cd23-init-byte-span build-gsim > "$output/build.log" 2>&1
python3 "$root/simulator/gsim/tool_fixes/test_init_byte_span.py" --original "$original/build/gsim/gsim" --repaired "$output/source/build/gsim/gsim" --cxx "$GSIM_CXX" --output "$output/regression" > "$output/regression.log" 2>&1
printf 'Built and tested %s; record and qualify a fresh epoch receipt before hardware use.\n' "$output/source/build/gsim/gsim"
