.DEFAULT_GOAL := help
MILL ?= mill
RISCV_PREFIX ?= riscv64-unknown-elf-
PAYLOAD_SRC ?= legacy/simulator/payloads/timer.S
PAYLOAD_DIR := simulator/build/payload

.PHONY: help compile test test-scala regress sim-verilog payload clean
help:
	@echo "Active GSIM: make compile | test-scala | gsim-smoke | gsim-backend-test | gsim-integer-test | gsim-core-test | test"
	@echo "Arcilator Windows pilot: make arcilator-smoke-export"
	@echo "make test (or regress): Scala parameter/elaboration checks, then the full GSIM suite with NEMU differential checks"

compile:
	$(MILL) -i IonSoC.compile

test-scala:
	$(MILL) -i IonSoC.test

# Sequence these explicitly: concurrent Mill invocations would contend for its lock.
test: test-scala
	$(MAKE) gsim-test

regress: test

# RTL export is independent of simulation; no simulator is invoked here.
sim-verilog:
	$(MILL) -i IonSoC.test.runMain sim.TopMain

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
	cp fpga/vivado-ooc.tcl fpga/run-current-soc-timing.bat "$(FPGA_CURRENT_SOC_OUT)/"

.PHONY: arcilator-smoke-export
arcilator-smoke-export:
	python3 simulator/arcilator/export_smoke.py
