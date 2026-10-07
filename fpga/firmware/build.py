#!/usr/bin/env python3
"""Build fixed 128 KiB BMG ROM images and a relocatable RAM-program example."""
import argparse
from pathlib import Path
import shutil
import subprocess
import ipaddress
import hashlib
import json
from memory_layout import MemoryLayout

ROM_BYTES = 128 * 1024


def memory_images(data, output):
    if len(data) > ROM_BYTES:
        raise ValueError("boot firmware exceeds 128 KiB ROM")
    padded = data + bytes(ROM_BYTES - len(data))
    words = [int.from_bytes(padded[n:n + 4], "little")
             for n in range(0, ROM_BYTES, 4)]
    (output / "bootrom.coe").write_text(
        "memory_initialization_radix=16;\nmemory_initialization_vector=\n" +
        ",\n".join(f"{word:08x}" for word in words) + ";\n", encoding="ascii")
    for bank, name in enumerate(("even", "odd")):
        (output / f"bootrom.{name}.hex").write_text(
            "".join(f"{word:08x}\n" for word in words[bank::2]), encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--uart-divisor", type=int, default=1)
    parser.add_argument("--uart-reference-hz", type=int,
                        help="16550 baud-generator reference, NOT CPU or raw peripheral clock")
    parser.add_argument("--uart-baud", type=int, help="Expected baud; requires --uart-reference-hz")
    parser.add_argument("--ddr", action="store_true", help="512 MiB AXI DDR; reserve the final 16 KiB for the ROM monitor")
    parser.add_argument("--ddr-bytes", type=lambda s: int(s, 0), default=0x20000000,
                        choices=(0x20000000, 0x40000000, 0x80000000))
    parser.add_argument("--netboot", action="store_true", help="native GMAC TFTP boot; requires DDR, DMA RX_STOP and MAC admission-stop/drain-capable new RTL")
    parser.add_argument("--netboot-ip", default="192.168.137.30")
    parser.add_argument("--netboot-server", default="192.168.137.1")
    parser.add_argument("--netboot-file", default="valence.vld")
    parser.add_argument("--prefix", default="riscv64-unknown-elf-")
    parser.add_argument("--cpu-hz", type=int, default=40_000_000)
    args = parser.parse_args()
    if args.netboot and not args.ddr:
        parser.error("--netboot requires --ddr and the native GMAC")
    try:
        net_ip = int(ipaddress.IPv4Address(args.netboot_ip))
        net_server = int(ipaddress.IPv4Address(args.netboot_server))
    except ValueError as error:
        parser.error(str(error))
    if not args.netboot_file or len(args.netboot_file) > 127 or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in args.netboot_file):
        parser.error("netboot filename must be a safe ASCII basename, <=127 characters")
    if not 1 <= args.uart_divisor <= 65535:
        parser.error("UART divisor must be in 1..65535")
    if (args.uart_reference_hz is None) != (args.uart_baud is None):
        parser.error("--uart-reference-hz and --uart-baud must be specified together")
    if args.uart_reference_hz is not None:
        if args.uart_baud <= 0 or args.uart_reference_hz <= 0 or (
                args.uart_reference_hz != 16 * args.uart_baud * args.uart_divisor):
            parser.error("UART contract mismatch: baud = reference_hz / (16 * divisor); "
                         "ManagedUart 460800 uses reference 7372800 and divisor 1, not 7")
    if not 6_000_000 <= args.cpu_hz <= 200_000_000:
        parser.error("CPU clock must be in 6..200 MHz")
    source = Path(__file__).resolve().parent
    output = (args.out or source.parents[1] / "build/fpga/firmware").resolve()
    output.mkdir(parents=True, exist_ok=True)
    gcc, objcopy, size = [args.prefix + tool for tool in ("gcc", "objcopy", "size")]
    for tool in (gcc, objcopy, size):
        if not shutil.which(tool):
            parser.error(f"missing tool: {tool}")
    flags = ["-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany",
             "-mno-relax", "-msmall-data-limit=0", "-Os", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-ffunction-sections",
             "-fdata-sections", "-nostdlib", "-nostartfiles", "-Wall", "-Wextra",
             "-Werror", "-Wl,--gc-sections", "-Wl,--no-relax"]
    layout = MemoryLayout(args.ddr_bytes if args.ddr else 1024 * 1024)
    ram_bytes = layout.ram_bytes
    for name, inputs, linker in (
        ("bootrom", ("start.S", "bootrom.c", "crc32.c"), "bootrom.ld"),
        ("sample_app", ("sample_start.S", "sample_app.c"), "sample_app.ld"),
    ):
        elf = output / f"{name}.elf"
        net_flags = (["-DBOARD_NETBOOT=1", f"-DNETBOOT_IP={net_ip}U", f"-DNETBOOT_SERVER={net_server}U",
                      f'-DNETBOOT_FILE="{args.netboot_file}"'] if args.netboot and name == "bootrom" else [])
        if net_flags:
            inputs = (*inputs, "netboot.c", "netboot_board.c")
        command = [gcc, *flags, *net_flags, f"-DUART_DIVISOR={args.uart_divisor}", f"-DCPU_HZ={args.cpu_hz}ULL",
                   f"-DBOARD_CLOCK_MHZ={args.cpu_hz // 1_000_000}",
                   *(["-DBOARD_DDR=1"] if args.ddr else []),
                   f"-DBOARD_RAM_BYTES={ram_bytes}UL",
                   f"-DBOARD_MONITOR_BASE={layout.monitor}UL",
                   f"-Wl,--defsym=BOARD_RAM_BYTES={ram_bytes}",
                   f"-Wl,--defsym=BOARD_MONITOR_BASE={layout.monitor}",
                   f"-T{source / linker}", f"-Wl,-Map,{output / (name + '.map')}",
                   *(str(source / item) for item in inputs), "-o", str(elf)]
        subprocess.run(command, check=True)
        subprocess.run([objcopy, "-O", "binary", str(elf),
                        str(output / f"{name}.bin")], check=True)
        subprocess.run([size, str(elf)], check=True)
    data = (output / "bootrom.bin").read_bytes()
    memory_images(data, output)
    (output / "bootrom-contract.json").write_text(json.dumps(dict(
        schema=1, cpu_hz=args.cpu_hz, timebase_hz=args.cpu_hz,
        timebase_source="BoardSocTop.timerTick=true; MachineTimer.timeValue -> TIME CSR",
        netboot_rx_stop_abi=2 if args.netboot else None, uart_divisor=args.uart_divisor,
        uart_reference_hz=args.uart_reference_hz, uart_baud=args.uart_baud,
        uart_contract_checked=args.uart_baud is not None,
        ddr_bytes=ram_bytes if args.ddr else None, netboot=args.netboot,
        bootrom_sha256=hashlib.sha256(data).hexdigest()), indent=2) + "\n")
    print(f"ROM: {len(data)} bytes / {ROM_BYTES}; UART divisor {args.uart_divisor}")
    print(f"Outputs: {output}")


if __name__ == "__main__":
    main()
