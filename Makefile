.DEFAULT_GOAL := help
MILL ?= mill
RISCV_PREFIX ?= riscv64-unknown-elf-
PAYLOAD_SRC ?= legacy/simulator/payloads/timer.S
PAYLOAD_DIR := simulator/build/payload

.PHONY: help compile test test-scala regress sim-verilog legacy-compile legacy-elaboration legacy-rtl payload clean
help:
	@echo "Active GSIM: make compile | test-scala | gsim-smoke | gsim-backend-test | gsim-integer-test | gsim-core-test | test"
	@echo "Arcilator Windows pilot: make arcilator-smoke-export"
	@echo "Historical module only: make legacy-compile | legacy-elaboration | legacy-rtl"
	@echo "make test (or regress): Scala parameter/elaboration checks, then the full GSIM suite with NEMU differential checks"

compile:
	$(MILL) -i IonSoC.compile

test-scala:
	$(MILL) -i IonSoC.test

# Sequence these explicitly: concurrent Mill invocations would contend for its lock.
test: test-scala
	$(MAKE) gsim-test

regress: test

# Explicit historical compatibility entry; never invokes a retired simulator.
legacy-compile:
	$(MILL) -i LegacySoC.compile

legacy-elaboration:
	$(MILL) -i LegacySoC.test

legacy-rtl:
	$(MILL) -i LegacySoC.test.runMain sim.TopMain

# Backward-compatible alias, not the current VL100 board export.
sim-verilog: legacy-rtl

# Historical payload assembly remains available; GSIM program tests build their own supported images.
payload:
	mkdir -p $(PAYLOAD_DIR)
	$(RISCV_PREFIX)gcc -march=rv64imac_zicsr -mabi=lp64 -nostdlib -nostartfiles -Tlegacy/simulator/payloads/payload.ld -o $(PAYLOAD_DIR)/payload.elf $(PAYLOAD_SRC)
	$(RISCV_PREFIX)objcopy -O binary --only-section=.text $(PAYLOAD_DIR)/payload.elf $(PAYLOAD_DIR)/payload

clean:
	$(MILL) -i clean
	rm -rf build/gsim build/arcilator simulator/build/payload

include simulator/gsim/targets.mk

# IP-level synchronous-ROM core export, independent of the legacy SoC.
FPGA_OUT ?= build/fpga
FPGA_ROM_WORDS ?= 4096
.PHONY: fpga-rtl
fpga-rtl:
	@test -n "$(FPGA_IMAGE)" || (echo "Set FPGA_IMAGE to a supported RV64I binary"; exit 1)
	$(MILL) -i IonSoC.test.runMain ooo.FpgaRomMain "$(FPGA_OUT)" "$(FPGA_IMAGE)" "$(FPGA_ROM_WORDS)"

FPGA_PLATFORM_OUT ?= build/fpga-platform
.PHONY: fpga-platform-rtl
fpga-platform-rtl:
	@test -n "$(FPGA_IMAGE)" || (echo "Set FPGA_IMAGE to a supported RV64I binary"; exit 1)
	$(MILL) -i IonSoC.test.runMain ooo.FpgaRomMain "$(FPGA_PLATFORM_OUT)" "$(FPGA_IMAGE)" "$(FPGA_ROM_WORDS)" platform

FPGA_CURRENT_SOC_OUT ?= build/fpga-current-soc
.PHONY: fpga-current-soc-rtl
fpga-current-soc-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.CurrentSocTimingMain "$(FPGA_CURRENT_SOC_OUT)"
	cp fpga/vivado-ooc.tcl fpga/vivado-module-ooc.tcl fpga/vivado-hierarchy-audit.tcl fpga/run-current-soc-timing.bat "$(FPGA_CURRENT_SOC_OUT)/"

FPGA_COMPACT_SOC_OUT ?= build/fpga-compact-soc
.PHONY: fpga-compact-soc-rtl
fpga-compact-soc-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.CurrentSocTimingMain "$(FPGA_COMPACT_SOC_OUT)" compact
	cp fpga/vivado-ooc.tcl fpga/vivado-module-ooc.tcl fpga/vivado-hierarchy-audit.tcl fpga/run-current-soc-timing.bat "$(FPGA_COMPACT_SOC_OUT)/"

.PHONY: arcilator-smoke-export
arcilator-smoke-export:
	python3 simulator/arcilator/export_smoke.py

# PL board profile: initialized 128 KiB BMG ROM, 1 MiB XPM UltraRAM, 40 MHz.
FPGA_BOARD_OUT ?= build/fpga-board-40m
FPGA_BOARD_FIRMWARE_OUT ?= build/fpga/firmware
FPGA_BOARD_CLOCK_HZ ?= 40000000
.PHONY: fpga-board-firmware fpga-board-rtl
fpga-board-firmware:
	python3 fpga/firmware/build.py --out "$(FPGA_BOARD_FIRMWARE_OUT)" --cpu-hz "$(FPGA_BOARD_CLOCK_HZ)"

fpga-board-rtl: fpga-board-firmware
	$(MILL) -i IonSoC.test.runMain ooo.BoardSocMain "$(FPGA_BOARD_OUT)" "$(FPGA_BOARD_CLOCK_HZ)"
	cp fpga/zu15eg/configure_project.tcl fpga/zu15eg/README.md "$(FPGA_BOARD_OUT)/"

# Focused behavior check: make gsim-board-boot-test (no full acceptance suite).

# Independent DDR50 candidate; does not overwrite the Board40 RTL/firmware.
FPGA_DDR_OUT ?= build/fpga-board-ddr50
FPGA_DDR_FIRMWARE_OUT ?= build/fpga/firmware-ddr50
FPGA_DDR_CLOCK_HZ ?= 50000000
FPGA_DDR_UART_BAUD ?= 1500000
FPGA_DDR_TIMING_PROFILE ?= early-issue
.PHONY: fpga-board-ddr-rtl
fpga-board-ddr-rtl:
	python3 fpga/firmware/build.py --out "$(FPGA_DDR_FIRMWARE_OUT)" --cpu-hz "$(FPGA_DDR_CLOCK_HZ)" --ddr
	$(MILL) -i IonSoC.test.runMain ooo.BoardSocMain "$(FPGA_DDR_OUT)" "$(FPGA_DDR_CLOCK_HZ)" ddr "$(FPGA_DDR_TIMING_PROFILE)" "$(FPGA_DDR_UART_BAUD)"
	cp fpga/zu15eg/soc_top_ddr.sv fpga/zu15eg/board_ddr.xdc fpga/zu15eg/pl_ddr4_pins.xdc fpga/zu15eg/prepare_ddr_project.tcl fpga/zu15eg/pl-ddr4-integration.md "$(FPGA_DDR_OUT)/"
