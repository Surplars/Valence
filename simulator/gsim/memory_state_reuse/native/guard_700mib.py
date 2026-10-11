#!/usr/bin/env python3
"""Additional coordinator-required 700 MiB free-space floor for the live run."""
import json, os, signal, shutil, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
FLOOR = 700 * 1024**2
OUTPUT = HERE/'execution/additional-700mib-guard.json'
TRACE = HERE/'execution/additional-700mib-guard.jsonl'
matches = []
for path in Path('/proc').iterdir():
    if not path.name.isdigit():
        continue
    try:
        args = (path/'cmdline').read_bytes().split(b'\0')
        if any(arg.endswith(b'memory-state-reuse-native-20261011-r1/run_native.py') for arg in args) and b'run' in args:
            matches.append(int(path.name))
    except (FileNotFoundError, PermissionError):
        pass
if len(matches) != 1:
    raise RuntimeError('Expected exactly one running native runner, found ' + str(matches))
runner = matches[0]
state = dict(status='RUNNING', runner_pid=runner, minimum_free_bytes=FLOOR, observed_minimum_free_bytes=None,
             started_at_epoch=time.time(), triggered=False,
             scope='Additional independent free-space guard; initial immutable runner has a lower 650 MiB floor.')
OUTPUT.write_text(json.dumps(state, indent=2)+'\n')
with TRACE.open('x') as trace:
    while (Path('/proc')/str(runner)).exists():
        available = shutil.disk_usage(HERE).free
        state['observed_minimum_free_bytes'] = min(state['observed_minimum_free_bytes'] or available, available)
        trace.write(json.dumps(dict(epoch=time.time(), free_bytes=available))+'\n')
        trace.flush()
        if available < FLOOR:
            state['triggered'] = True
            # Stop the coordinator first so no next stage can start, terminate
            # only its direct active stage groups, then resume for failure receipt.
            os.kill(runner, signal.SIGSTOP)
            children = []
            for path in Path('/proc').iterdir():
                if not path.name.isdigit():
                    continue
                try:
                    fields = (path/'stat').read_text().rsplit(')',1)[1].split()
                    if int(fields[1]) == runner:
                        children.append(int(path.name))
                        os.killpg(int(fields[2]), signal.SIGTERM)
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    pass
            state['terminated_stage_pids'] = children
            os.kill(runner, signal.SIGCONT)
            state['status'] = 'TRIGGERED_ADDITIONAL_700MIB_FLOOR'
            break
        OUTPUT.write_text(json.dumps(state, indent=2)+'\n')
        time.sleep(1)
if not state['triggered']:
    state['status'] = 'PASS_ADDITIONAL_700MIB_FLOOR_NOT_TRIGGERED'
state['finished_at_epoch'] = time.time()
OUTPUT.write_text(json.dumps(state, indent=2)+'\n')
print(json.dumps(state))
