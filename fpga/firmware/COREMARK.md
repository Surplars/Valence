# CoreMark on the ZU15EG board

This is a bare-metal RAM application for the existing 40 MHz Valence ROM
monitor. It uses the pinned upstream EEMBC CoreMark source already fetched by
the GSIM setup, without modifying benchmark files. The board port provides
the UART formatter and a configurable `rdtime` frequency (40 MHz by default). Code and data are linked
at `0x80200000` and fit below the application's reserved stack.

From the Valence repository in WSL:

```sh
make coremark-setup                 # only if simulator/build/coremark-src is absent
python3 fpga/firmware/build_coremark.py
```

For the DDR50 / 115200 board, explicitly select the real clock and memory:

```sh
python3 fpga/firmware/build_coremark.py --clock-hz 50000000 --memory ddr
```

Then copy the resulting BIN to the DDR board directory and upload with
`uart_load.py COM4 coremark_board.bin --memory ddr --baud 115200 --run --console`.
Do not use the default 40 MHz timer conversion on the 50 MHz board.

The default output is
`build/fpga/firmware/coremark_board.bin`; an ELF and map file accompany it.
The default iteration count is zero, so CoreMark calibrates itself to a run
of at least ten seconds. To force a count, use `--iterations N`, but runs
shorter than ten seconds are not valid scores.
Copy the newly built binary to the Windows board directory after each rebuild:

```sh
cp build/fpga/firmware/coremark_board.bin /mnt/d/TOOLS/projects/vivadoProjects/ZU15EG/src/board40/coremark_board.bin
```

Close other serial terminals. On Windows, use the existing board uploader,
changing `COM5` and the binary path as needed:

```powershell
python "D:\TOOLS\projects\vivadoProjects\ZU15EG\src\board40\uart_load.py" COM5 "D:\TOOLS\projects\vivadoProjects\ZU15EG\src\board40\coremark_board.bin" --run --console
```

`--console` displays UART output and forwards keyboard input in an interactive
terminal. Without it, the uploader closes the port immediately after starting
the application. CoreMark ignores input while running; it prints a start message,
then may be quiet during calibration and the timed run. A valid result includes
`Correct operation validated` and a `CoreMark 1.0` line; after the app
returns, the ROM monitor prints `APP RETURN` and its menu, which can now accept
keyboard commands in the same console. Press Ctrl-C to close the host console.

The timer frequency must match the actual clock wizard configuration; 40 MHz
remains the build default for the historical UltraRAM board, while DDR50 needs
`--clock-hz 50000000 --memory ddr`. The frequency/label options do not change the
ISA flags, link address or startup protocol. No new Vivado run is needed for
this downloadable application.

`GSIM_CXX=clang++-19 python3 simulator/gsim/board_coremark.py` compares compact
two-/four-wide BoardSoc configurations using one identical DDR application and
independent AXI backing/latency/backpressure. It intentionally runs only one
iteration: the expected "at least 10 secs" error remains visible, reference
list/matrix/state CRCs must pass, and only timed cycles are compared. This is
not a valid CoreMark score or a physical FPGA measurement.
