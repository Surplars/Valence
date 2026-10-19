#!/usr/bin/env python3
"""Short Icarus MMU-interface capacity traces, with an independent Sv39 oracle.

Requires already-compiled OrbitalI1.test sources and --classpath from Mill's
OrbitalI1.test.runClasspath. Never runs Verilator, Vivado, or installs tools.
All children are bounded to 1200 s and a hard 4 GiB free-disk floor.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

P = Path(__file__).resolve().parents[2]
E = P / "build" / "gsim" / "i1-tlb-capacity"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--classpath", required=True, type=Path)
parser.add_argument("--profiles", default="4:off,8:off,16:on,32:on")
parser.add_argument("--output", type=Path, default=E)
parser.add_argument("--java", type=Path, default=Path("java"))
parser.add_argument("--firtool", type=Path, default=Path("firtool"))
parser.add_argument("--iverilog", type=Path, default=Path("iverilog"))
parser.add_argument("--vvp", type=Path, default=Path("vvp"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
cp = args.classpath.read_text().strip()
# Accept a JSON array from `mill show ...runClasspath`, or a colon-joined classpath.
if cp.startswith("["):
    cp = ":".join(re.sub(r"^(?:q?ref):v\d+:[^:]+:", "", x) for x in json.loads(cp))
files = [Path(__file__).resolve(), P / "src/test/scala/inorder/I1TlbCapacityMain.scala", P / "simulator/gsim/harness/i1_tlb_capacity.sv",
         *sorted((P / "src/main/scala/core/inorder").glob("*.scala"))]
source_hashes = {str(p.relative_to(P)): sha(p) for p in files}
receipt = {"status": "RUNNING", "cycle_scope": "MMU-interface CPU-clock-domain trace cycles; no complete CPU program, cache or DDR timing",
           "service_law": "CPU-private three-user round-robin single physical D owner, coherentBandwidth=false; fixed 2-cycle response; no performance-phase stalls",
           "traffic": "copy loads page i offset0 then stores page (i+N/2)%N offset8; N is total VPN footprint; each I request overlaps the first D operation only, then drain; 4 KiB Sv39 leaves; 1/4/8/16/32/64 pages; VPN stride 1 or 1024; load/store/copy; optional concurrent I translation; cold one sweep, warm three sweeps",
           "source_sha256": source_hashes, "commands": [], "profiles": {}, "physical_timing_qualified": False}

def save():
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

def run(label, cmd, expected=0):
    log = args.output / (label + ".log")
    start = time.monotonic(); minimum = os.statvfs(args.output).f_bavail * os.statvfs(args.output).f_frsize
    if minimum < 4 * 1024**3:
        raise RuntimeError("4 GiB free-disk floor reached before " + label)
    with log.open("w") as out:
        child = subprocess.Popen(list(map(str, cmd)), cwd=P, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while child.poll() is None:
                fs = os.statvfs(args.output); minimum = min(minimum, fs.f_bavail * fs.f_frsize)
                if minimum < 4 * 1024**3:
                    raise RuntimeError("4 GiB free-disk floor reached during " + label)
                if time.monotonic() - start > 1200:
                    raise RuntimeError("1200 s bound exceeded during " + label)
                time.sleep(.2)
        except BaseException:
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
            raise
    receipt["commands"].append({"label": label, "command": list(map(str, cmd)), "exit": child.returncode,
        "seconds": time.monotonic()-start, "minimum_free_bytes": minimum, "log_sha256": sha(log)})
    save()
    if child.returncode != expected:
        raise RuntimeError(f"{label}: exit {child.returncode}, expected {expected}\n{log.read_text()[-5000:]}")
    return log.read_text()

def signals(rtl, directory):
    header = re.search(r"module I1TlbCapacityHarness\((.*?)\);", rtl, re.S).group(1)
    header = re.sub(r"//[^\n]*", "", header)
    direction = width = ""; declarations=[]; inputs=[]
    for entry in header.split(","):
        entry=entry.strip()
        match=re.match(r"(input|output)\s*(\[[^]]+\])?\s*(\w+)$", entry)
        if match: direction,width,name=match.group(1),match.group(2) or "",match.group(3)
        else:
            assert re.fullmatch(r"\w+", entry), entry
            name=entry
        declarations.append(f"    {'reg' if direction=='input' else 'wire'} {width} {name};")
        if direction=="input": inputs.append(f"        {name}='0;")
    declarations.append("    I1TlbCapacityHarness dut (.*);")
    (directory/"signals.svh").write_text("\n".join(declarations)+"\n")
    (directory/"initialize.svh").write_text("\n".join(inputs)+"\n")

columns = "phase,pages,stride_pages,operation,competing_instruction,cycles,d_accepted,i_accepted,d_hit,i_hit,d_miss,i_miss,d_slow_admission,i_slow_admission,d_pte_reads,i_pte_reads,d_physical,i_physical,memory_latency".split(",")
rows=[]
save()
try:
    for profile in args.profiles.split(","):
        count,bank=profile.split(":"); n=int(count); banked=bank=="on"
        label=f"tlb{n}-bank{int(banked)}"; directory=args.output/label; directory.mkdir(exist_ok=True)
        run(label+"-emit", [args.java,"-Xmx2g","-XX:ActiveProcessorCount=2",f"-Dchisel.project.root={P}","-cp",cp,
            "inorder.I1TlbCapacityMain",directory,f"--tlb={n}", *(["--banked-tlb-proofs"] if banked else [])])
        fir=directory/"I1TlbCapacityHarness.fir"; sv=directory/"I1TlbCapacityHarness.sv"
        run(label+"-lower", [args.firtool,fir,"--disable-all-randomization","--strip-debug-info","--verification-flavor=if-else-fatal", "--default-layer-specialization=enable",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays", "-o",sv])
        signals(sv.read_text(),directory)
        binary=directory/"capacity.vvp"
        run(label+"-compile", [args.iverilog,"-g2012","-s","tb","-I",directory,"-o",binary,sv,
            P/"simulator/gsim/harness/i1_tlb_capacity.sv"])
        positive=run(label+"-positive",[args.vvp,binary])
        assert "I1_TLB_CAPACITY_PASS" in positive
        negative=run(label+"-negative",[args.vvp,binary,"+negative"],1)
        assert "independent D physical address/operation oracle" in negative
        profile_rows=[]
        for line in positive.splitlines():
            if not line.startswith("CAPACITY,"): continue
            values=line.split(",")[1:]; assert len(values)==len(columns),(line,len(values))
            row=dict(zip(columns,[values[0],*map(int,values[1:])]))
            row={"tlb_entries":n,"banked":banked,**row}
            profile_rows.append(row);rows.append(row)
            # Exact event accounting independent of lookup implementation.
            assert row["d_pte_reads"]==3*row["d_miss"] and row["i_pte_reads"]==3*row["i_miss"], row
            assert row["d_hit"]+row["d_miss"]==row["d_accepted"],row
            assert row["i_hit"]+row["i_miss"]==row["i_accepted"],row
            assert row["d_physical"]==row["d_accepted"] and row["i_physical"]==row["i_accepted"],row
            if row["phase"]=="warm" and row["stride_pages"]==1 and row["pages"]<=n:
                assert row["d_miss"]==row["i_miss"]==row["d_pte_reads"]==row["i_pte_reads"]==0,row
                assert row["d_slow_admission"]==row["i_slow_admission"]==0,row
            if row["phase"]=="cold" and (row["operation"]!=2 or (row["stride_pages"]==1 and row["pages"]<=n) or row["pages"]==1):
                assert row["d_miss"]==row["pages"] and row["i_miss"]==row["pages"]*row["competing_instruction"],row
        assert len(profile_rows)==144,len(profile_rows)
        receipt["profiles"][label]={"status":"PASS", "fir_sha256":sha(fir),"rtl_sha256":sha(sv),
            "binary_sha256":sha(binary),"rows":len(profile_rows),"result":next(line for line in positive.splitlines() if line.startswith("I1_TLB_CAPACITY_PASS")),"negative_oracle":"PA perturbation rejected"}
        with (args.output/"capacity.csv").open("w") as out:
            writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        save();print(label,"PASS",flush=True)
    assert source_hashes=={str(p.relative_to(P)):sha(p) for p in files}, "source changed during test"
    receipt["status"]="PASS"
except BaseException as e:
    receipt["status"]="FAIL";receipt["error"]=str(e);raise
finally:
    save()
