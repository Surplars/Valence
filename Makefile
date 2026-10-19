.DEFAULT_GOAL := help
MILL ?= mill
RISCV_PREFIX ?= riscv64-unknown-elf-
PAYLOAD_SRC ?= legacy/simulator/payloads/timer.S
PAYLOAD_DIR := simulator/build/payload

.PHONY: help compile test test-scala regress sim-verilog legacy-compile legacy-elaboration legacy-rtl payload clean
help:
	@echo "Active GSIM: make compile | test-scala | gsim-smoke | gsim-backend-test | gsim-integer-test | gsim-core-test | test"
	@echo "Functional bring-up first: make bringup-plan; make bringup-test BRINGUP_PROFILE=<name> BRINGUP_OUT=<fresh-dir> BRINGUP_ARGS='<explicit tools>'"
	@echo "Opt-in two-clock transport only: make cpu-fabric-cdc-rtl | cpu-fabric-cdc-test (see simulator/cdc/README.md)"
	@echo "Actual I1 independent-clock short boot: make i1-independent-boot-guest | i1-independent-boot-rtl | i1-independent-boot-test (explicit profile required)"
	@echo "Arcilator Windows pilot: make arcilator-smoke-export"
	@echo "Historical module only: make legacy-compile | legacy-elaboration | legacy-rtl"
	@echo "make test (or regress): Scala parameter/elaboration checks, then the full GSIM suite with NEMU differential checks"

compile:
	$(MILL) -i IonSoC.compile

# Named functional profiles only. A plan does not run hardware or select a timing candidate.
.PHONY: bringup-plan bringup-test
bringup-plan:
	@python3 -B simulator/gsim/bringup.py --plan

bringup-test:
	@test -n "$(BRINGUP_PROFILE)" || (echo "Set BRINGUP_PROFILE explicitly; see make bringup-plan"; exit 1)
	@test -n "$(BRINGUP_OUT)" || (echo "Set a fresh BRINGUP_OUT directory"; exit 1)
	python3 -B simulator/gsim/bringup.py --run "$(BRINGUP_PROFILE)" --output "$(BRINGUP_OUT)" $(BRINGUP_ARGS)

# Independent-edge digital CDC component check; it does not attach either CPU or select a board profile.
.PHONY: cpu-fabric-cdc-rtl cpu-fabric-cdc-test
cpu-fabric-cdc-rtl:
	@test -n "$(CPU_FABRIC_CDC_RTL)" || (echo "Set a fresh CPU_FABRIC_CDC_RTL directory"; exit 1)
	@test ! -e "$(CPU_FABRIC_CDC_RTL)" || (echo "Refusing to overwrite CPU_FABRIC_CDC_RTL"; exit 1)
	@test "$(CPU_FABRIC_CDC_STORAGE)" = baseline -o "$(CPU_FABRIC_CDC_STORAGE)" = held || (echo "Set CPU_FABRIC_CDC_STORAGE=held (II1) or baseline (comparison only)"; exit 1)
	$(MILL) -i IonSoC.test.runMain ip.TileLinkClockDomainBoundaryMain "$(CPU_FABRIC_CDC_RTL)" "$(CPU_FABRIC_CDC_STORAGE)"

cpu-fabric-cdc-test:
	@test -n "$(CPU_FABRIC_CDC_RTL)" -a -n "$(CPU_FABRIC_CDC_OUT)" || (echo "Set CPU_FABRIC_CDC_RTL and fresh CPU_FABRIC_CDC_OUT"; exit 1)
	@test "$(CPU_FABRIC_CDC_STORAGE)" = baseline -o "$(CPU_FABRIC_CDC_STORAGE)" = held || (echo "Select CPU_FABRIC_CDC_STORAGE explicitly"; exit 1)
	python3 -B simulator/cdc/test_tilelink_boundary.py "$(CPU_FABRIC_CDC_RTL)" "$(CPU_FABRIC_CDC_OUT)" --storage "$(CPU_FABRIC_CDC_STORAGE)" $(CPU_FABRIC_CDC_ARGS)

# Bounded native independent-edge exception. No board profile or reduced fixture is implicit.
.PHONY: i1-independent-boot-guest i1-independent-boot-rtl i1-independent-boot-test
i1-independent-boot-guest:
	@test -n "$(I1_CDC_GUEST)" -a -n "$(I1_CDC_CROSS_PREFIX)" || (echo "Set fresh I1_CDC_GUEST and explicit I1_CDC_CROSS_PREFIX"; exit 1)
	python3 -B simulator/cdc/test_i1_independent_boot.py "$(I1_CDC_GUEST)" --prepare-only --cross-prefix "$(I1_CDC_CROSS_PREFIX)"

i1-independent-boot-rtl:
	@test -n "$(I1_CDC_RTL)" -a -n "$(I1_CDC_ROM)" || (echo "Set fresh I1_CDC_RTL and checked I1_CDC_ROM"; exit 1)
	@test "$(I1_CDC_MODE)" = single -o "$(I1_CDC_MODE)" = independent || (echo "Set I1_CDC_MODE=single or independent"; exit 1)
	@test "$(I1_CDC_PROFILE)" = test-only -o "$(I1_CDC_PROFILE)" = full-cpu || (echo "Set I1_CDC_PROFILE=test-only or full-cpu; neither is a board release"; exit 1)
	$(MILL) -i IonSoC.test.runMain inorder.I1IndependentClockSocMain "$(I1_CDC_RTL)" "$(I1_CDC_MODE)" "$(I1_CDC_PROFILE)" "$(I1_CDC_ROM)"

i1-independent-boot-test:
	@test -n "$(I1_CDC_OUT)" -a -n "$(I1_CDC_GUEST)" -a -n "$(I1_CDC_SINGLE_RTL)" -a -n "$(I1_CDC_INDEPENDENT_RTL)" || (echo "Set fresh I1_CDC_OUT, I1_CDC_GUEST and both I1_CDC_*_RTL paths"; exit 1)
	@test "$(I1_CDC_PROFILE)" = test-only -o "$(I1_CDC_PROFILE)" = full-cpu || (echo "Select I1_CDC_PROFILE explicitly"; exit 1)
	python3 -B simulator/cdc/test_i1_independent_boot.py "$(I1_CDC_OUT)" --guest-dir "$(I1_CDC_GUEST)" --single-rtl "$(I1_CDC_SINGLE_RTL)" --independent-rtl "$(I1_CDC_INDEPENDENT_RTL)" --profile "$(I1_CDC_PROFILE)" $(I1_CDC_TEST_ARGS)

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

# Actual MAC/CDC boundary, independent clocks, no SoC/CAD/full GSIM.
MAC_CDC_OUTPUT ?= build/mac-boundary-cdc
.PHONY: native-mac-boundary-cdc
.PHONY: native-mac-netlist-contract
native-mac-netlist-contract:
	python3 -m unittest discover -s fpga/next -p test_mac_netlist_review.py -v
	python3 -m unittest discover -s fpga/next -p test_media_integration.py -v

native-mac-boundary-cdc:
	python3 fpga/next/check_mac_boundary.py --output "$(MAC_CDC_OUTPUT)" --mill "$(MILL)"
