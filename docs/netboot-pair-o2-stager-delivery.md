# I1 pair/O2 through the frozen r6 RAM stager

Static/host validation only, 2026-10-23. No board access, new bitstream, network
setting change, full DUT run or claim of measured download speed.

## Bound image and addresses

- Final I1 `valence.vld`: 142,386,892 bytes, SHA256
  `d46762eb312579cd305909690dcb95a5f6c0de6e6fd66eb232ad1dff86a2d0b9`.
- Its 36-byte checked header describes 142,386,856 payload bytes at/entering
  `0x80200000`, exclusive end `0x889ca6a8`. Header CRC32 `8acdd757`,
  payload CRC32 `70e0080a`. Full CRC and byte identity to the packaged OpenSBI
  BIN were independently checked, as were all three ELF load segments.
- Linux Image's runtime extent ends at `0x88ae5890`; DTB resides at
  `0x80300000` with a 64 KiB reservation. Neither reaches the live stager.
- Frozen stager reservation is `[0xffe00000,0xffe20000)`, with BSS/RX ending
  below `0xffe06498` and stack `[0xffe1c000,0xffe20000)`. Its download acceptance
  is `[0x80200000,0xffe00000)`, not the larger generic menu-ROM limit.
- The LZ4-compressed initramfs is embedded in the raw Linux Image, not a second
  bootloader decompression destination. Linux allocates unpacked rootfs memory
  after the stager has stopped DMA and handed off permanently. The rootfs
  archive is 278,493,696 bytes (file contents total 280,483,179 bytes); these
  numbers do not establish Linux's peak allocator consumption. The temporary
  high stager need not remain live during Linux unpacking. No board boot or
  peak-memory measurement is claimed.

## Receive arithmetic and protocol

The firmware caps size at `0x7fc00000`; received bytes start at zero and advance
only after `payload <= size - received`. Board stores additionally require
`offset <= IMAGE_LIMIT` and `n <= IMAGE_LIMIT - offset`. Thus neither unsigned
32-bit received/offset nor the physical destination can wrap for this image.
The entry-range comparison uses 64-bit addition and requires four-byte alignment.

At 1024-byte DATA blocks this exact wire image needs 139,050 DATA packets:
two 16-bit block-number wraps, then block 7978 containing 716 bytes. A short
DATA packet terminates it. Exact-multiple images instead require the final
zero-length DATA packet. `next`/`previous` are uint16_t; completion is governed
by exact byte length and CRC, never block count alone.

The existing 208 MiB logical host fixture was rerun in 0.718 s: both tests PASS,
including three wraps, dropped DATA65535/ACK0 and zero-length EOF. Existing
actual firmware protocol evidence covers rollover, stream and independent RAM
CRC, duplicate and malformed traffic. This is not a new 142 MB DUT simulation.
Firmware refuses launch after length/stream CRC/RAM CRC/range/quiet failures.

## Windows two-file command

Use the existing I1 bit and its ROM netboot menu `n`; this stager's real CPU
relocation/handoff qualification is I1 only, not A1. Keep the two source
artifacts unchanged. In PowerShell, create a new payload folder and copy the
final ordinary checked VLD under its required second-stage filename:

```powershell
Copy-Item '<I1-pair-O2-folder>\valence.vld' '<new-payload-folder>\linux.vld'
Get-FileHash '<new-payload-folder>\linux.vld' -Algorithm SHA256
python '<frozen-host-folder>\netboot_host.py' serve '<r6-stager-folder>\valence.vld' --second-image '<new-payload-folder>\linux.vld' --memory ddr2g-menu --bind 192.168.137.1 --board 192.168.137.30 --packet-delay-us 100 --once
```

These IPs are the **compiled r6 stager settings**, not a discovery of the user's
current network. Before running, confirm the existing ROM/board and host NIC
already use this pair. If they differ, stop: changing only host CLI arguments
cannot retarget the compiled stager. A separately built matching candidate is
needed; do not silently reconfigure the host network or replace the bit.

The exact basename allowlist is `valence.vld` plus `linux.vld`. The latter is
an unchanged copy of the final checked VLD, including its header, NOT raw Image
or an internal stage2 payload. The host validates both before opening a socket.
Use the frozen host with `--second-image` support, not an older single-file host.

Default/explicit pacing is 100 microseconds minimum between DATA packets in
multi-block windows. Windows scheduling can oversleep this delay; it is not a
precise throughput guarantee. A zero-pacing experiment is optional and separate,
not a silent default change. No firewall, NIC, IP or privilege change is made
by this command. If binding or reachability fails, stop and diagnose explicitly.

## Stop conditions and success evidence

- Stop before serving if the copied image's size/hash differs, the files have
  wrong basenames, header/CRC validation fails, or network bindings differ.
- Do not modify either file while serving. Do not start a competing TFTP server.
- On `STAGER FAILED`, a trap, CRC failure or sustained retries/no progress,
  preserve both logs and reset the board before another stager attempt.
- Host `--once` exits only after both files' EOF ACKs. That is transport evidence,
  not independent RAM CRC verification or Linux boot success.
- Require the UART `STAGER RAM CRC VERIFIED; DMA quiet; launching checked payload.`
  and then the expected OpenSBI/Linux boot messages for a successful board run.
  Preserve both TFTP STATS and board NB lines for phase comparison. Clock changes
  made by the later Linux boot do not speed the preceding download.

Evidence: `build/netboot-pair-o2-boundary-r1/receipt.json` and `large.log`, plus
frozen stager `layout-proof.json` and prior `build/netboot-performance-r1` logs.
