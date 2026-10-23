#!/usr/bin/env python3
"""Supplemental native fault-injection check against freshly emitted I1 RTL.

Stall only live privateDrained after normal protocol qualification. This is not
an architectural traffic substitute: run i1_runtime_cdc_native.py as well.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TB = ROOT / 'simulator/gsim/common/i1_runtime_cdc_tb.sv'
MARKER = '''    cpuPaused = 0;
    terminal(0, 32'hc0de0028, 8'd1, 0, 0, 1);'''
INJECTION = '''    force dut.tile.privateDrained = 1'b0;
    cpuPaused = 0;
    while (!dut.tile.applyResume_resumePending) tick();
    @(negedge alwaysOnClock);
    cancel_bits[0] = 32'hc0de0028; cancel_epoch[0] = 8'd1;
    resume_bits[0] = 32'hc0de0028; resume_epoch[0] = 8'd1;
    cancel_valid[0] = 1; resume_valid[0] = 1;
    repeat (12) begin
      tick();
      if (!dut.tile.runtimeActive || !dut.tile.applyResume_resumePending ||
          dut.tile.io_bus_maintenanceResume_ready || dut.tile.io_bus_maintenanceResumed_valid ||
          cpuResumed != oldCpuResumed || cancel_ready[0] || resume_ready[0] || result_valid != 0)
        $fatal(1, "pending resume admitted duplicate/cancel or released before live drain");
    end
    cancel_valid[0] = 0; resume_valid[0] = 0;
    if ($test$plusargs("reset-pending")) begin
      #1; reset = 1;
      repeat (8) tick();
      if (dut.tile.applyResume_resumePending || dut.tile.runtimeActive ||
          dut.tile.releasePending || dut.tile.io_bus_maintenanceResumed_valid)
        $fatal(1, "coordinated reset leaked pending resume ownership");
      $display("RESUME_OWNER_NATIVE_PASS reset_pending=1"); $finish;
    end
    @(negedge cpuClock); release dut.tile.privateDrained;
    @(posedge cpuClock); #1;
    if (dut.tile.runtimeActive || !dut.tile.releasePending || dut.tile.io_bus_maintenanceResumed_valid)
      $fatal(1, "actual release did not start fresh response-edge proof");
    @(posedge cpuClock); #1;
    if (dut.tile.io_bus_maintenanceResumed_valid)
      $fatal(1, "resume acknowledgement preceded two real release edges");
    @(posedge cpuClock); #1;
    if (!dut.tile.io_bus_maintenanceResumed_valid)
      $fatal(1, "resume acknowledgement missing after two real release edges");
    terminal(0, 32'hc0de0028, 8'd1, 0, 0, 1);
    $display("RESUME_OWNER_NATIVE_PASS drain_stall=1 late_cancel_duplicate=1 release_edges=2");
    $finish;'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-out', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    runtime = a.runtime_out.resolve()
    out = a.out.resolve()
    qualification = json.loads((runtime / 'receipt.json').read_text())
    assert qualification['status'] == 'PASS', 'passing real runtime qualification required'
    for name, digest in qualification['source_sha256'].items():
        assert sha(ROOT / name) == digest, 'qualification source drift: ' + name
    out.mkdir(exist_ok=False)
    text = TB.read_text()
    assert text.count(MARKER) == 1
    tb = out / 'resume_owner_tb.sv'
    tb.write_text(text.replace(MARKER, INJECTION))
    rtl = sorted((runtime / 'rtl').glob('*.sv'))
    assert rtl
    assert {f.name: sha(f) for f in rtl} == qualification['rtl_sha256'], 'qualification RTL drift'
    record = {'status': 'RUNNING', 'source_tb_sha256': sha(TB),
              'qualification_receipt_sha256': sha(runtime / 'receipt.json'),
              'runner_sha256': sha(Path(__file__).resolve()),
              'injected_tb_sha256': sha(tb), 'rtl_sha256': {f.name: sha(f) for f in rtl},
              'scope': 'same real I1 RTL, explicit internal drain-stall injection; supplement, not traffic qualification',
              'cases': []}
    try:
        binary = out / 'sim.vvp'
        commands = [('compile', ['iverilog', '-g2012', '-I', str(runtime), '-s', 'i1_runtime_cdc_tb',
                    '-o', str(binary), *map(str, rtl), str(tb)])]
        run = ['vvp', str(binary), '+rom=' + str(runtime / 'guest.hex')]
        commands += [('pending-drain', run), ('pending-reset', run + ['+reset-pending'])]
        for name, command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            log = result.stdout + result.stderr
            (out / (name + '.log')).write_text(log)
            record['cases'].append({'name': name, 'exit_code': result.returncode})
            assert result.returncode == 0, name + ' failed'
            if name != 'compile':
                assert 'RESUME_OWNER_NATIVE_PASS' in log, name + ' missing pass marker'
        assert record['rtl_sha256'] == {f.name: sha(f) for f in rtl}
        record['status'] = 'PASS'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {f.name: sha(f) for f in out.glob('*.log')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    print('PASS receipt=' + str(out / 'receipt.json'))


if __name__ == '__main__':
    main()
