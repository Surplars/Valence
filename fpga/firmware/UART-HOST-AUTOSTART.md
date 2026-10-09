# UART host compatibility: automatic start and legacy ROMs

Updated BootROMs automatically start a successfully downloaded image after all
launch-time checks pass. There is no separate `g`/`r` launch command on those ROMs.
The updated `uart_load.py` still supports older programmed ROMs; changing the host
script does not change the firmware already programmed on a board.

For an automatic-start ROM, use the board's matching baud and memory profile:

```sh
python3 fpga/firmware/uart_load.py /dev/ttyUSB0 image.bin \
  --baud 460800 --memory ddr2g-menu --console
```

On Windows, replace `/dev/ttyUSB0` with the appropriate `COM` port. The example
settings are for the 2 GiB menu profile with a 7,372,800 Hz UART reference and
divisor 1. Select the actual firmware profile, including its diagnostic scratch
reservation; do not copy these settings onto a differently configured board.

## Status contract

The binary VLD1 protocol, ACKs and CRC fields are unchanged:

1. Final `VACK` bounds the acknowledged upload phase.
2. `VDON` reports the downloaded length and successful RAM readback CRC. It does
   not prove that the guest has started. The existing upload/verification timing
   summary ends at this reply, including when the final `VACK` was lost.
3. `DOWNLOAD OK` is followed by launch-time checks. On the new firmware, a
   complete, standalone `AUTOBOOT\r\n` line announces automatic start after
   those checks pass. This announcement still does not prove guest execution;
   use the guest's UART output or another guest-specific observation.
4. If a launch-time check fails or is cancelled, `VDON` can have been received
   without a subsequent `AUTOBOOT`. The host reports known failure diagnostics
   or times out, and does not send `g` as a fallback.

The host forwards post-`VDON` text as it arrives, including failure diagnostics.
It reads only through the end of the recognized status marker, leaving the
following boot text and the very first guest byte for `--console`. Markers may
arrive across multiple UART reads; partial `AUTOBOOT` text is not accepted.

## Meaning of `--run`

- New ROM + `--run`: recognize `AUTOBOOT`; never send `g` into the running guest.
- New ROM without `--run`: the image still starts automatically. Omitting this
  flag is not a download-only mode.
- Legacy ROM + `--run`: wait for `ready to boot\r\n` or a legacy `> ` prompt,
  then send one `g`. Successful guest execution remains unconfirmed.
- Legacy ROM without `--run`: leave the verified image ready without sending
  a launch command.

`--console` is independent of `--run`. It displays following boot/guest output and
forwards keyboard input when the host has a TTY; redirected stdin remains
receive-only. Without `--console`, the host exits after reporting the status.

## Timeouts and recovery

`--verify-timeout` controls the final upload-to-`VDON` verification wait.
`--boot-status-timeout` separately controls the wait from `VDON` to the automatic
or legacy readiness marker, allowing for the final launch-time verification.
Each defaults independently to `max(30 seconds, image bytes / 16384)`.

A status timeout does not revoke an already received `VDON` and does not prove
that the guest failed to execute. The host never retries the final data frame or
sends an unconditional run command to resolve this ambiguity. Inspect the
displayed board output; reset the board before a new download if needed. An old
host that requires `ready to boot` is not compatible with automatic-start ROMs;
use this updated script rather than sending a manual `g`.

Focused, hardware-independent host verification (no pyserial required):

```sh
python3 fpga/firmware/test_uart_load.py
```
