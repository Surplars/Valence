# SBI console handoff correction

The unpatched I1 boot-pair/O2 image is superseded by the verified prefix
correction below and must not be recommended as a working startup image. The
corrected firmware has passed build and host artifact/admission checks; its
board retest remains pending.

The sealed I1 boot-pair/O2 Debian candidate contains a real contract mismatch:
its firmware DT enables the `ns16550a` UART, while the clock-control driver's
closed-image pair policy requires Linux's UART node to be disabled. The kernel
also has built-in `SERIAL_8250` and `SERIAL_OF_PLATFORM`; an enabled node is not
proof of exclusive SBI ownership. On cold50 this causes `-EINVAL`, leaves the
fabric target at its initial50, and the platform script rejects the mismatched
expected125 target. This is independent of the separate foreign-epoch rejection
when a pre-Linux clock transaction has occurred.

Do not remove the driver safety gate or mark the initial firmware UART disabled.
OpenSBI needs the initial enabled UART to select and initialize its console.
The explicit `openion,sbi-console-exclusive` marker instead requests a late
handoff operation. Pinned OpenSBI first initializes the console and retains its
UART base and getc/putc callbacks. At the end of `generic_final_init`, after the
normal DT pack/open_into expansion, the new bounded helper checks the exact
UART, its initial status and selected stdout path, then changes only its status
to disabled for Linux. Pack/open_into failures are propagated. There are no
UART register writes in the fixup, and Linux HVC continues through SBI DBCN.

The regression consumes the real delivered DTB, original libfdt and production
clock admission/topology bodies. It reproduces the old EINVAL/fabric-target50
failure and tests the final transformed DT. Hardware registers are mocked cold
state, not a real board; no board success is implied. Tight packed DT tests
reject insufficient space without altering bytes, then succeed with the actual
generic4KiB expansion. Both write-safety and unrelated malformed-DT tests remain.

`build_sbi_console_prefix.py` rebuilds only OpenSBI plus its initial DT from the
exact pinned source. It extracts the original Image from the reviewed archive,
checks its hash, and requires the entire body after the2MiB firmware prefix to
remain byte-identical. It independently validates ELF/load layout and VLD CRC.
The small delivery contains a replacement prefix and `apply_sbi_console_prefix.py`.
That tool validates the original full VLD identity, both CRCs, prefix/body hashes,
and resulting full VLD identity before writing a new output file. It never
modifies the original or touches a board. A fresh normal ROM download still
transfers the complete VLD; the small patch avoids downloading the distribution
again from the chat, not the normal board transfer.

This patch is only for the exact sealed I1 boot-pair/O2 candidate. It does not
change Linux, Debian rootfs, modules, frequency whitelist or bitstream. A board
retest must confirm platform success, independent CPU/fabric control results,
HVC input/output and actual network/IRQ initialization. Host tests alone cannot
establish those outcomes.
