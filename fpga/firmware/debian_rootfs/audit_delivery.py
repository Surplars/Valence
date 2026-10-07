#!/usr/bin/env python3
"""Read-only content audit of packed VL100 BSP; writes only an independent receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import netboot_host

def sha(data):
    return hashlib.sha256(data).hexdigest()

def newc(data):
    entries, offset = {}, 0
    while data[offset:offset+6] == b"070701":
        fields = [int(data[offset+6+n*8:offset+14+n*8],16) for n in range(13)]
        mode, size, name_size = fields[1], fields[6], fields[11]
        start = offset + 110
        name = data[start:start+name_size-1].decode()
        body = (start + name_size + 3) & ~3
        if name == "TRAILER!!!":
            return entries
        entries[name.removeprefix("./")] = (mode, data[body:body+size])
        offset = (body + size + 3) & ~3
    raise RuntimeError("invalid/truncated newc archive")

def check(value, message):
    if not value: raise RuntimeError(message)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--delivery",type=Path,required=True)
    p.add_argument("--ddr-receipt",type=Path,required=True)
    p.add_argument("--pressure-receipt",type=Path,required=True)
    p.add_argument("--rom",type=Path,required=True)
    p.add_argument("--rootfs-out",type=Path,required=True)
    p.add_argument("--receipt",default="bsp-audit.json",help="new basename; completed receipts are immutable")
    args = p.parse_args()
    output = args.delivery.resolve()
    check((ROOT/"build/fpga").resolve() in output.parents, "audit output outside BSP build")
    check(Path(args.receipt).name==args.receipt and args.receipt.endswith(".json"),"unsafe receipt name")
    target = output/args.receipt
    check(not target.exists(),"completed audit receipt cannot be overwritten")
    manifest = json.loads((output/"manifest.json").read_text())
    check(manifest["memory_bytes"] == 0x80000000 and manifest["rootfs_embedded"] and
          manifest["smp"] is False and manifest["board_verified"] is False,"wrong candidate identity")
    for name,row in manifest["files"].items():
        data = (output/name).read_bytes()
        check(len(data)==row["bytes"] and sha(data)==row["sha256"],"delivery drift: "+name)
    root = manifest["rootfs"]
    archive = args.rootfs_out.resolve()/root["archive"]["path"]
    data = archive.read_bytes()
    check(sha(data)==root["archive"]["sha256"],"rootfs archive drift")
    entries = newc(data)
    for module,digest in manifest["modules"].items():
        path = "usr/lib/modules/"+manifest["linux_version"]+"/extra/"+module
        check(sha(entries[path][1])==digest,"packed module mismatch: "+module)
    check("VALENCE_RAM_BYTES=2147483648" in entries["etc/valence-release"][1].decode(),"rootfs RAM identity")
    init = entries["init"][1].decode()
    order = [init.index("modprobe "+m) for m in ("valence_soc","valence_aia","valence_cmu","valence_dma")]
    check(order==sorted(order) and init.index("valence-net-up")>order[-1],"driver init order")
    check("dma-bench" in entries["usr/local/sbin/dma-bench"][1].decode(),"DMA benchmark missing")
    for name in ("usr/bin/bash","usr/lib/riscv64-linux-gnu/libc.so.6",
                 "usr/lib/riscv64-linux-gnu/ld-linux-riscv64-lp64d.so.1","usr/bin/iperf3"):
        elf = entries[name][1]
        check(elf[:6]==b"\x7fELF\x02\x01" and struct.unpack_from("<H",elf,18)[0]==243 and
              struct.unpack_from("<I",elf,48)[0]&6==4,"not RV64 LP64D ELF: "+name)
    console = entries["dev/console"]
    check(console[0]&0o170000==0o020000,"missing console character device")
    kernel = Path(root["kernel_build"])/"linux"
    dtc = kernel/"scripts/dtc/dtc"
    decoded = subprocess.check_output([str(dtc),"-q","-I","dtb","-O","dts",
                                      str(output/"valence-vl100.dtb")],text=True)
    check("0x80200000 0x00 0x80000000" in decoded and "monitor@ffff8000" in decoded,
          "compiled DT missing full DDR/reservation")
    for driver in ("valence-cmu-v1","valence-memcpy-dma-v1","valence-native-gmac-v1","valence-dma-bench-v1"):
        check(driver in decoded,"compiled DT missing "+driver)
    check(netboot_host.validate(output/"valence.vld",netboot_host.LIMITS["ddr2g"])==
          (output/"opensbi_debian13_riscv64_vl100_cpu100_u460800.bin").stat().st_size,"vld header/CRC")
    receipts = {}
    for name,path in (("ddr2g",args.ddr_receipt),("network_pressure",args.pressure_receipt)):
        record = json.loads(path.read_text())
        check(record["status"]=="passed","failed hardware short receipt")
        for source,digest in record["source_sha256"].items():
            check(sha((ROOT/source).read_bytes())==digest,"hardware source drift: "+source)
        receipts[name] = dict(path=str(path.resolve()),sha256=sha(path.read_bytes()))
    symbols = {line.split()[2]:int(line.split()[0],16) for line in
               subprocess.check_output(["riscv64-unknown-elf-nm",args.rom/"bootrom.elf"],text=True).splitlines()
               if len(line.split())==3}
    check(symbols["__boot_stack_top"]==0xffffc000 and symbols["__app_stack_top"]==0xffff8000 and
          0xffff8000<=symbols["__bss_start"]<=symbols["__bss_end"]<=0xffffa000,"ROM reservation/link mismatch")
    result = dict(status="software_and_affected_short_checks_passed",vendor="OpenIon",soc="VL100",
        cpu="Orbital-A1",memory_bytes=0x80000000,ram_base="0x80200000",end_exclusive="0x100200000",
        monitor_reserved=["0xffff8000","0xffffc000"],cpu_hz=100000000,uart_baud=460800,
        delivery_manifest_sha256=sha((output/"manifest.json").read_bytes()),receipts=receipts,
        archive_path=str(archive),archive_entries=len(entries),matched_modules=list(manifest["modules"]),
        rom={p.name:sha(p.read_bytes()) for p in args.rom.glob("bootrom.*")},
        board_verified=False,routed_timing_verified=False,bit_generated=False,
        required_new_bit=["full 2 GiB physical address translation","Home stalled direct read retention",
                          "matched 2 GiB BootROM monitor layout"],
        userland_check_scope="QEMU-user only, not Valence CPU runtime",
        audit_source_sha256=sha(Path(__file__).read_bytes()))
    target.write_text(json.dumps(result,indent=2)+"\n")
    print("VL100_BSP_AUDIT_PASS "+str(target))

if __name__=="__main__":
    main()
