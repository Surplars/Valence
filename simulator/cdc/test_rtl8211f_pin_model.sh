#!/usr/bin/env bash
# Focused model qualification using an existing, unmodified emitted engine.
# Run from any directory; no elaboration, installation or production edits.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo"
source scripts/cloud/env.sh
if [[ $# -ne 2 ]]; then
    echo "usage: IVERILOG=/path/iverilog VVP=/path/vvp $0 emitted-MdioClause22.sv NEW-output-directory" >&2
    exit 2
fi
rtl=$(realpath "$1")
out=$(realpath -m "$2")
# Atomic creation deliberately refuses even an empty pre-existing directory.
mkdir -p "$(dirname "$out")"
if ! mkdir "$out"; then
    echo 'Refusing to overwrite an existing evidence directory' >&2
    exit 2
fi
iverilog=$(command -v "${IVERILOG:-iverilog}")
vvp=$(command -v "${VVP:-vvp}")
timeout_tool=$(command -v timeout)
python3 - "$rtl" "$out" "$iverilog" "$vvp" "$timeout_tool" <<'PY'
import datetime, hashlib, json, pathlib, shlex, sys
rtl, out, iverilog, vvp, timeout = sys.argv[1:]
paths = {pathlib.Path(p).resolve() for p in (rtl, iverilog, vvp, timeout,
    'simulator/cdc/rtl8211f_pin_model.sv', 'simulator/cdc/rtl8211f_pin_model_tb.sv',
    'simulator/cdc/test_rtl8211f_pin_model.sh', 'scripts/cloud/env.sh')}
# Native validation may supply the repository's small shell launcher. Bind its
# actual executable and complete -B support tree too, not just launcher text.
for tool in (iverilog, vvp):
    raw = pathlib.Path(tool).read_bytes()
    if raw.startswith(b'#!'):
        for line in raw.decode().splitlines():
            words = shlex.split(line)
            if words and words[0] == 'exec':
                executable = pathlib.Path(words[1])
                if not executable.is_absolute() or not executable.is_file():
                    raise SystemExit('Cannot evidence-bind non-absolute launcher executable')
                paths.add(executable.resolve())
                if '-B' in words:
                    base = pathlib.Path(words[words.index('-B') + 1])
                    if not base.is_dir():
                        raise SystemExit('Missing compiler support directory')
                    paths.update(p.resolve() for p in base.rglob('*') if p.is_file())
pre = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    tools=dict(iverilog=iverilog, vvp=vvp, timeout=timeout),
    limits_seconds=dict(compile=60, positive=120, negative=120),
    sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})
pathlib.Path(out, 'inputs-before.json').write_text(json.dumps(pre, indent=2) + '\n')
PY
"$timeout_tool" --signal=TERM --kill-after=5s 60s "$iverilog" \
    -g2012 -s rtl8211f_pin_model_tb -o "$out/pin-model.vvp" \
    simulator/cdc/rtl8211f_pin_model.sv simulator/cdc/rtl8211f_pin_model_tb.sv "$rtl" \
    >"$out/compile.log" 2>&1
sha256sum "$out/pin-model.vvp" >"$out/compiled-before.sha256"
set +e
"$timeout_tool" --signal=TERM --kill-after=5s 120s "$vvp" "$out/pin-model.vvp" >"$out/positive.log" 2>&1
positive_rc=$?
"$timeout_tool" --signal=TERM --kill-after=5s 120s "$vvp" "$out/pin-model.vvp" \
    +inject_expected_mismatch >"$out/negative.log" 2>&1
negative_rc=$?
set -e
python3 - "$out" "$positive_rc" "$negative_rc" <<'PY'
import datetime, hashlib, json, pathlib, sys
out = pathlib.Path(sys.argv[1])
positive_rc, negative_rc = map(int, sys.argv[2:])
pre = json.loads((out / 'inputs-before.json').read_text())
def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
post = {p: digest(p) for p in pre['sha256']}
changed = [p for p in post if post[p] != pre['sha256'][p]]
compiled_before = (out / 'compiled-before.sha256').read_text().split()[0]
compiled_after = digest(out / 'pin-model.vvp')
positive_ok = positive_rc == 0 and 'RTL8211F_PIN_MODEL_PASS ' in (out / 'positive.log').read_text()
negative_ok = negative_rc == 1 and ('PIN_MODEL readback reg=2 write=0 got=001c/0 expected=001d/0'
    in (out / 'negative.log').read_text())
passed = positive_ok and negative_ok and not changed and compiled_before == compiled_after
receipt = dict(result='pass' if passed else 'fail',
    started_utc=pre['started_utc'], finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    positive_exit=positive_rc, negative_exit=negative_rc, limits_seconds=pre['limits_seconds'],
    tools=pre['tools'], inputs_before=pre['sha256'], inputs_after=post,
    inputs_unchanged=not changed, changed_inputs=changed,
    compiled_vvp_sha256_before=compiled_before, compiled_vvp_sha256_after=compiled_after,
    negative='Expected ID1 changed to 001d; ordinary response comparator rejected actual 001c.',
    scope='Test-only PHY pin/register responder against existing emitted MdioClause22. Not actual-manager debounce, physical PHY timing, or full managed-bank qualification.',
    artifact_sha256={name: digest(out / name) for name in
        ('inputs-before.json', 'compiled-before.sha256', 'compile.log', 'positive.log', 'negative.log')})
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
if not passed:
    raise SystemExit('Pin-model qualification failed; inspect fresh receipt and logs')
PY
cat "$out/positive.log"
printf 'PIN_MODEL_NEGATIVE_PASS ordinary_readback_checker=1 exit=%s\n' "$negative_rc"
