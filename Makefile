WORD_LEN = 64
# COMPILER = riscv64-linux-gnu-
COMPILER = riscv64-unknown-elf-
CC = $(COMPILER)gcc
AS = $(COMPILER)as
LD = $(COMPILER)ld
OBJCOPY = $(COMPILER)objcopy
VERILATOR = verilator
OPENOCD ?= /opt/openocd/bin/openocd
# Generated Verilator translation units are large; blindly using every logical
# CPU (168 on the bring-up host) can make the kernel OOM-kill the compiler.
# Keep interactive/debug builds bounded and cache unchanged units. Release/perf
# runs may override both knobs explicitly.
VERILATOR_BUILD_JOBS ?= 2
VERILATOR_OBJCACHE ?= $(shell command -v ccache 2>/dev/null)
VERILATOR_OPT_FAST ?= -O1
VERILATOR_OPT_SLOW ?=
LINUX_VERILATOR_CFLAGS ?= -DION_LINUX_PROFILE=1
# Verilator trace instrumentation materially slows compile and bloats generated
# C++, so normal smoke/perf runs build without it. Use `TRACE=1` together with
# `ION_TRACE_WAVE=1` when an FST waveform is actually needed.
TRACE ?= 0
ifeq ($(TRACE),1)
VERILATOR_TRACE_FLAGS = --trace-fst --trace-threads 1
VERILATOR_OBJ_SUFFIX = -trace
else
VERILATOR_TRACE_FLAGS =
VERILATOR_OBJ_SUFFIX =
endif
# The simulator harness still reads selected rootp internals for ROM loading
# and bring-up diagnostics. Keep those symbols public independently of wave
# tracing, so default builds avoid trace code but retain harness visibility.
VERILATOR_PUBLIC_FLAGS = --public-flat-rw
PAYLOAD_MARCH ?= rv$(WORD_LEN)imac_zicsr
PAYLOAD_MABI ?= lp$(WORD_LEN)

SIMULATOR_DIR = simulator
BUILD_DIR = $(SIMULATOR_DIR)/build
SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl
MCU_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-mcu
ICACHE_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-icache
FIRMWARE_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-firmware
LINUX_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-linux
DIFFTEST_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-difftest
LINUX_DIFFTEST_SYSTEM_VERILOG_DIR = $(BUILD_DIR)/../../build/rtl-difftest-linux
PAYLOAD_BUILD_DIR = $(BUILD_DIR)/payload
VERILATOR_OBJ_DIR = $(BUILD_DIR)/obj$(VERILATOR_OBJ_SUFFIX)
MCU_VERILATOR_OBJ_DIR = $(BUILD_DIR)/obj-mcu$(VERILATOR_OBJ_SUFFIX)
ICACHE_VERILATOR_OBJ_DIR = $(BUILD_DIR)/obj-icache$(VERILATOR_OBJ_SUFFIX)
FIRMWARE_VERILATOR_OBJ_DIR = $(BUILD_DIR)/obj-firmware$(VERILATOR_OBJ_SUFFIX)
LINUX_VERILATOR_OBJ_DIR = $(BUILD_DIR)/obj-linux$(VERILATOR_OBJ_SUFFIX)
SIM_HARNESS_DIR = $(SIMULATOR_DIR)/harness
SIM_RTL_DIR = $(SIMULATOR_DIR)/rtl
PAYLOAD_SRC_DIR = $(SIMULATOR_DIR)/payloads
FIRMWARE_DIR = $(SIMULATOR_DIR)/firmware
RUSTSBI_DIR ?= $(FIRMWARE_DIR)/rustsbi
OPENSBI_DIR ?= $(FIRMWARE_DIR)/opensbi
FILE_LIST = $(SYSTEM_VERILOG_DIR)/filelist.f
MCU_FILE_LIST = $(MCU_SYSTEM_VERILOG_DIR)/filelist.f
ICACHE_FILE_LIST = $(ICACHE_SYSTEM_VERILOG_DIR)/filelist.f
FIRMWARE_FILE_LIST = $(FIRMWARE_SYSTEM_VERILOG_DIR)/filelist.f
LINUX_FILE_LIST = $(LINUX_SYSTEM_VERILOG_DIR)/filelist.f
DIFFTEST_FILE_LIST = $(DIFFTEST_SYSTEM_VERILOG_DIR)/filelist.f
LINUX_DIFFTEST_FILE_LIST = $(LINUX_DIFFTEST_SYSTEM_VERILOG_DIR)/filelist.f
RTL_STAMP = $(SYSTEM_VERILOG_DIR)/.generated.stamp
MCU_RTL_STAMP = $(MCU_SYSTEM_VERILOG_DIR)/.generated.stamp
ICACHE_RTL_STAMP = $(ICACHE_SYSTEM_VERILOG_DIR)/.generated.stamp
FIRMWARE_RTL_STAMP = $(FIRMWARE_SYSTEM_VERILOG_DIR)/.generated.stamp
LINUX_RTL_STAMP = $(LINUX_SYSTEM_VERILOG_DIR)/.generated.stamp
DIFFTEST_RTL_STAMP = $(DIFFTEST_SYSTEM_VERILOG_DIR)/.generated.stamp
LINUX_DIFFTEST_RTL_STAMP = $(LINUX_DIFFTEST_SYSTEM_VERILOG_DIR)/.generated.stamp
TB = $(SIM_HARNESS_DIR)/verilator_main.cpp
PAYLOAD_SRC ?= $(PAYLOAD_SRC_DIR)/timer.S
PAYLOAD_LDS = $(PAYLOAD_SRC_DIR)/payload.ld
FIRMWARE_LDS = $(PAYLOAD_SRC_DIR)/firmware.ld
FIRMWARE_BSWAP_LDS = $(PAYLOAD_SRC_DIR)/firmware_bswap.ld
SBI_PAYLOAD_LDS = $(PAYLOAD_SRC_DIR)/sbi_payload.ld
PAYLOAD = $(PAYLOAD_BUILD_DIR)/payload
PAYLOAD_ELF = $(PAYLOAD_BUILD_DIR)/payload.elf
PAYLOAD_ROM_LO_HEX = $(PAYLOAD_BUILD_DIR)/payload_rom_lo.hex
PAYLOAD_ROM_HI_HEX = $(PAYLOAD_BUILD_DIR)/payload_rom_hi.hex
PAYLOAD_SRAM_BIN = $(PAYLOAD_BUILD_DIR)/payload_sram.bin
PAYLOAD_SRAM_HEX = $(PAYLOAD_BUILD_DIR)/payload_sram.hex
FIRMWARE_TRAMPOLINE_ELF = $(PAYLOAD_BUILD_DIR)/firmware_trampoline.elf
FIRMWARE_TRAMPOLINE_ROM_LO_HEX = $(PAYLOAD_BUILD_DIR)/firmware_trampoline_rom_lo.hex
FIRMWARE_TRAMPOLINE_ROM_HI_HEX = $(PAYLOAD_BUILD_DIR)/firmware_trampoline_rom_hi.hex
DIFFTEST_LINUX_TRAMPOLINE_ELF = $(PAYLOAD_BUILD_DIR)/difftest_linux_trampoline.elf
DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX = $(PAYLOAD_BUILD_DIR)/difftest_linux_trampoline_rom_lo.hex
DIFFTEST_LINUX_TRAMPOLINE_ROM_HI_HEX = $(PAYLOAD_BUILD_DIR)/difftest_linux_trampoline_rom_hi.hex
DIFFTEST_OPENSBI_TRAMPOLINE_ELF = $(PAYLOAD_BUILD_DIR)/difftest_opensbi_trampoline.elf
DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX = $(PAYLOAD_BUILD_DIR)/difftest_opensbi_trampoline_rom_lo.hex
DIFFTEST_OPENSBI_TRAMPOLINE_ROM_HI_HEX = $(PAYLOAD_BUILD_DIR)/difftest_opensbi_trampoline_rom_hi.hex
TIMER_ELF = $(PAYLOAD_BUILD_DIR)/timer.elf
BASIC_ELF = $(PAYLOAD_BUILD_DIR)/basic.elf
CLINT32_ELF = $(PAYLOAD_BUILD_DIR)/clint32.elf
TLERROR_ELF = $(PAYLOAD_BUILD_DIR)/tlerror.elf
AMO_ELF = $(PAYLOAD_BUILD_DIR)/amo.elf
HAZARD_ELF = $(PAYLOAD_BUILD_DIR)/hazard.elf
PIPELINE_REISSUE_ELF = $(PAYLOAD_BUILD_DIR)/pipeline_reissue.elf
LOAD_STALL_BYPASS_ELF = $(PAYLOAD_BUILD_DIR)/load_stall_bypass.elf
BSWAP_ELF = $(PAYLOAD_BUILD_DIR)/bswap.elf
FIRMWARE_BSWAP_ELF = $(PAYLOAD_BUILD_DIR)/firmware_bswap.elf
LDADDR_ELF = $(PAYLOAD_BUILD_DIR)/ldaddr.elf
MISALIGN_LD_ELF = $(PAYLOAD_BUILD_DIR)/misalign_ld.elf
PERF_ELF = $(PAYLOAD_BUILD_DIR)/perf.elf
BITMANIP_ELF = $(PAYLOAD_BUILD_DIR)/bitmanip.elf
PLIC_ELF = $(PAYLOAD_BUILD_DIR)/plic.elf
PLIC_S_ELF = $(PAYLOAD_BUILD_DIR)/plic_s.elf
UART_IRQ_ELF = $(PAYLOAD_BUILD_DIR)/uart_irq.elf
SBI_SMOKE_ELF = $(PAYLOAD_BUILD_DIR)/sbi_smoke.elf
FIRMWARE_PROBE_ELF = $(PAYLOAD_BUILD_DIR)/firmware_probe.elf
VSOC_BIN = $(VERILATOR_OBJ_DIR)/VSoc
MCU_VSOC_BIN = $(MCU_VERILATOR_OBJ_DIR)/VSoc
ICACHE_VSOC_BIN = $(ICACHE_VERILATOR_OBJ_DIR)/VSoc
FIRMWARE_VSOC_BIN = $(FIRMWARE_VERILATOR_OBJ_DIR)/VSoc
LINUX_VSOC_BIN = $(LINUX_VERILATOR_OBJ_DIR)/VSoc
IONSOC_DTS ?= $(BUILD_DIR)/ionsoc.dts
IONSOC_DTB ?= $(BUILD_DIR)/ionsoc.dtb
LINUX_DTS ?= $(BUILD_DIR)/ionsoc-linux.dts
LINUX_DTB ?= $(BUILD_DIR)/ionsoc-linux.dtb
LINUX_SRAM_BASE ?= 0x40000000
LINUX_SRAM_SIZE ?= 0x08000000
LINUX_DTB_ADDR ?= 0x47f00000
LINUX_KERNEL_ADDR ?= 0x40200000
LINUX_INITRAMFS_ADDR ?= 0x47000000
LINUX_BOOTARGS_EXTRA ?=
LINUX_EXPECT_UART ?= Initmem setup node 0
LINUX_MAX_CYCLES ?= 50000000
LINUX_PROBE_MAX_CYCLES ?= 20000000
LINUX_IMAGE ?= /home/openion/board/linux-build-ionsoc-tiny/arch/riscv/boot/Image
LINUX_IMAGE_ELF ?= $(BUILD_DIR)/linux/Image.elf
LINUX_KERNEL_ELF ?= $(LINUX_IMAGE_ELF)
RISCV_LINUX_CC ?= riscv64-linux-gnu-gcc
LINUX_INIT_SOURCE = $(SIMULATOR_DIR)/rootfs/init.c
LINUX_INIT = $(BUILD_DIR)/linux/rootfs/init
LINUX_INITRAMFS_PACKER = $(SIMULATOR_DIR)/rootfs/pack_initramfs.py
LINUX_INITRAMFS ?= $(BUILD_DIR)/linux/initramfs.cpio
LINUX_INIT_CFLAGS ?= -Os -march=rv64imac_zicsr_zifencei_zba_zbb_zbs -mabi=lp64 -nostdlib -static \
	-ffreestanding -fno-builtin -fno-stack-protector -fno-pie -no-pie -ffunction-sections \
	-fdata-sections -Wl,--build-id=none -Wl,--gc-sections -Wl,-e,_start
LINUX_DTS_CONFIG_STAMP = $(BUILD_DIR)/linux/.dts-config.$(shell printf '%s\n%s\n%s\n' \
	'$(LINUX_BOOTARGS_EXTRA)' '$(LINUX_INITRAMFS_ADDR)' '$(LINUX_DTB_ADDR)' | sha1sum | cut -d' ' -f1)
RUSTSBI_TARGET_DIR = $(RUSTSBI_DIR)/target/riscv64gc-unknown-none-elf/release
DEFAULT_RUSTSBI_FW_ELF = $(RUSTSBI_TARGET_DIR)/rustsbi-prototyper-jump.elf
RUSTSBI_FW_ELF ?= $(DEFAULT_RUSTSBI_FW_ELF)
RUSTSBI_CONFIG ?= prototyper/prototyper/config/ionsoc.toml
OPENSBI_FW_JUMP_ELF ?= $(OPENSBI_DIR)/build/platform/generic/firmware/fw_jump.elf
OPENSBI_FW_JUMP_ADDR ?= 0x40100000
OPENSBI_FW_JUMP_FDT_ADDR ?= 0x40f00000
LINUX_OPENSBI_BUILD_DIR ?= $(OPENSBI_DIR)/build-ionsoc-linux
LINUX_OPENSBI_FW_JUMP_ELF ?= $(LINUX_OPENSBI_BUILD_DIR)/platform/generic/firmware/fw_jump.elf
OPENSBI_PLATFORM ?= generic
# OpenSBI links its firmware as a static PIE. Prefer the Linux-targeting GNU
# toolchain when available because some bare-metal linker builds omit PIE.
OPENSBI_CROSS_COMPILE ?= $(shell if command -v riscv64-linux-gnu-gcc >/dev/null 2>&1; then echo riscv64-linux-gnu-; else echo $(COMPILER); fi)
# Keep OpenSBI within the hardware ISA profile. Generic OpenSBI defaults to
# rv64gc on many toolchains, which pulls in F/D instructions that this MCU
# profile does not implement.
OPENSBI_PLATFORM_RISCV_ISA ?= rv64imac_zicsr_zifencei_zba_zbb_zbs
RTL_SCALA_SOURCES = $(shell find src/main/scala -name '*.scala') src/test/scala/sim.scala

RUN_ARGS := $(filter-out verilator verilator-jtag,$(MAKECMDGOALS))

NEMU_HOME ?= $(CURDIR)/NEMU
NOOP_HOME ?= $(CURDIR)
DIFFTEST_EMU ?= $(NOOP_HOME)/build/emu
LINUX_DIFFTEST_WORK_DIR ?= $(NOOP_HOME)/build/difftest-linux-work
LINUX_DIFFTEST_WORK_EMU = $(LINUX_DIFFTEST_WORK_DIR)/build/emu
LINUX_DIFFTEST_EMU ?= $(NOOP_HOME)/build/emu-linux
DIFFTEST_CONFIG_OVERRIDE = $(SIMULATOR_DIR)/difftest/ionsoc_config_override.cpp
DIFFTEST_MERGE_ELF = $(SIMULATOR_DIR)/difftest/merge_elf.py
NEMU_BUILD_SO = $(NEMU_HOME)/build/riscv64-nemu-interpreter-so
NEMU_SO ?= $(BUILD_DIR)/difftest/riscv64-ionsoc-ref.so
LINUX_NEMU_SO ?= $(BUILD_DIR)/difftest/riscv64-ionsoc-linux-ref.so
NEMU_DEFCONFIG ?= riscv64-ionsoc-ref_defconfig
NEMU_LOCAL_DEFCONFIG ?= $(SIMULATOR_DIR)/difftest/$(NEMU_DEFCONFIG)
LINUX_NEMU_DEFCONFIG ?= riscv64-ionsoc-linux-ref_defconfig
LINUX_NEMU_LOCAL_DEFCONFIG = $(BUILD_DIR)/difftest/$(LINUX_NEMU_DEFCONFIG)
NEMU_LDFLAGS ?= -rdynamic -shared -fPIC -Wl,--no-undefined -lz -Wl,--gc-sections -Wl,--exclude-libs,ALL
DIFFTEST_PMEM_BASE ?= 0x10000000UL
DIFFTEST_FIRST_INST_ADDRESS ?= 0x80000000UL
DIFFTEST_MAX_CYCLES ?= 1000000
DIFFTEST_MAX_INSTR ?= 100000
DIFFTEST_BUILD_JOBS ?= 2
# Optimize for the edit/compile/debug loop. Verilator's generated C++ is much
# cheaper to compile at -O1 than -O3, while short DiffTest probes remain fast.
# ccache recovers unchanged generated translation units after RTL regeneration.
# Release/performance runs can override with DIFFTEST_CXX_OPT=-O3.
DIFFTEST_CXX_OPT ?= -O1
DIFFTEST_OBJCACHE ?= $(shell command -v ccache 2>/dev/null)
DIFFTEST_REGRESS_PAYLOADS ?= basic timer clint32 tlerror amo muldiv loadstore_widths compressed_mix hazard pipeline_reissue load_stall_bypass bswap ldaddr misalign_ld perf bitmanip plic plic_s uart_irq sv39
DIFFTEST_REGRESS_LOG_DIR ?= $(BUILD_DIR)/difftest-matrix
DIFFTEST_SIM_VFLAGS ?= +define+DIFFTEST
DIFFTEST_PGO_CFLAGS ?= -Wno-error -DDIFFTEST_PMEM_BASE=$(DIFFTEST_PMEM_BASE) -DDIFFTEST_FIRST_INST_ADDRESS=$(DIFFTEST_FIRST_INST_ADDRESS)
DIFFTEST_MAKE_ARGS = WITH_CHISELDB=0 WITH_CONSTANTIN=0 NO_ZSTD_COMPRESSION=1 \
	NEMU_HOME=$(NEMU_HOME) NOOP_HOME=$(NOOP_HOME) RTL_DIR=$(abspath $(DIFFTEST_SYSTEM_VERILOG_DIR)) \
	VERILATOR_BUILD_JOBS=$(DIFFTEST_BUILD_JOBS) SIM_VFLAGS="$(DIFFTEST_SIM_VFLAGS) $(SIM_VFLAGS)" \
	OPT_FAST="$(DIFFTEST_CXX_OPT)" OBJCACHE="$(DIFFTEST_OBJCACHE)" \
	PGO_CFLAGS="$(DIFFTEST_PGO_CFLAGS)" LLVM_BOLT=
LINUX_DIFFTEST_PMEM_BASE ?= 0x40000000UL
LINUX_DIFFTEST_FIRST_INST_ADDRESS ?= 0x80000000UL
LINUX_DIFFTEST_ENTRY ?= 0x80000000
# The REF memory must cover SRAM at 0x4000_0000 and the reset ROM at
# 0x8000_0000. mmap/MAP_NORESERVE keeps the untouched gap virtual-only.
LINUX_DIFFTEST_RAM_SIZE ?= 1073807360
LINUX_DIFFTEST_MAX_CYCLES ?= $(LINUX_MAX_CYCLES)
LINUX_DIFFTEST_MAX_INSTR ?= 10000000
LINUX_DIFFTEST_IMAGE ?= $(BUILD_DIR)/difftest/ionsoc-linux.elf
DIFFTEST_OPENSBI_SMOKE_IMAGE ?= $(BUILD_DIR)/difftest/ionsoc-opensbi-smoke.elf
DIFFTEST_OPENSBI_SMOKE_MAX_INSTR ?= 4500000
DIFFTEST_OPENSBI_SMOKE_MAX_CYCLES ?= 9000000
LINUX_DIFFTEST_PGO_CFLAGS ?= -Wno-error -DDIFFTEST_PMEM_BASE=$(LINUX_DIFFTEST_PMEM_BASE) -DDIFFTEST_FIRST_INST_ADDRESS=$(LINUX_DIFFTEST_FIRST_INST_ADDRESS)
LINUX_DIFFTEST_MAKE_ARGS = WITH_CHISELDB=0 WITH_CONSTANTIN=0 NO_ZSTD_COMPRESSION=1 \
	NEMU_HOME=$(NEMU_HOME) NOOP_HOME=$(NOOP_HOME) DESIGN_DIR=$(LINUX_DIFFTEST_WORK_DIR) \
	RTL_DIR=$(abspath $(LINUX_DIFFTEST_SYSTEM_VERILOG_DIR)) VERILATOR_BUILD_JOBS=$(DIFFTEST_BUILD_JOBS) \
	SIM_VFLAGS="$(DIFFTEST_SIM_VFLAGS) $(SIM_VFLAGS)" OPT_FAST="$(DIFFTEST_CXX_OPT)" \
	OBJCACHE="$(DIFFTEST_OBJCACHE)" PGO_CFLAGS="$(LINUX_DIFFTEST_PGO_CFLAGS)" LLVM_BOLT=
RISCV_TESTS_ISA_DIR ?= riscv-tests/isa
RISCV_TEST ?= rv64ui-p-simple
RISCV_TESTS ?= rv64ui-p-simple rv64ui-p-add rv64ui-p-addi rv64ui-p-lw rv64ui-p-ld rv64ui-p-sd rv64um-p-mul rv64um-p-div rv64ua-p-amoadd_w rv64ua-p-lrsc rv64uc-p-rvc
RISCV_TESTS_ALL_DIRS = rv64ui rv64um rv64ua rv64uc
RISCV_TESTS_ALL = $(sort $(foreach d,$(RISCV_TESTS_ALL_DIRS),$(patsubst $(RISCV_TESTS_ISA_DIR)/$(d)/%.S,$(d)-p-%,$(wildcard $(RISCV_TESTS_ISA_DIR)/$(d)/*.S))))
RISCV_TESTS_BUILD_DIR ?= $(BUILD_DIR)/riscv-tests
RISCV_TESTS_LOG_DIR ?= $(BUILD_DIR)/riscv-tests-matrix
RISCV_TEST_ELF = $(RISCV_TESTS_BUILD_DIR)/elf/$(RISCV_TEST)
RISCV_TEST_ROM_LO_HEX = $(RISCV_TESTS_BUILD_DIR)/$(RISCV_TEST)-rom-lo.hex
RISCV_TEST_ROM_HI_HEX = $(RISCV_TESTS_BUILD_DIR)/$(RISCV_TEST)-rom-hi.hex
RISCV_TEST_SRAM_HEX = $(RISCV_TESTS_BUILD_DIR)/$(RISCV_TEST)-sram.hex
RISCV_TEST_GCC_OPTS ?= -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles
RISCV_TEST_MARCH ?= rv$(WORD_LEN)imac_zicsr_zifencei
RISCV_TEST_MABI ?= lp$(WORD_LEN)
RISCV_TEST_LDS ?= $(PAYLOAD_SRC_DIR)/riscv_tests.ld
RISCV_TEST_TRAMPOLINE ?= $(PAYLOAD_SRC_DIR)/riscv_tests_trampoline.S
SIM_TOP = sim.TopMain

# Scala test groups are deliberately split so edit loops can target the block
# that changed instead of paying for every Chisel simulator suite.
SCALA_PROFILE_TESTS = config.ConfigSpec
SCALA_BUS_TESTS = bus.TLXbarSpec bus.TLSystemXbarSpec bus.TLCoherenceHubSpec
SCALA_CLINT_TESTS = device.CLINTSpec
SCALA_UART_TESTS = device.UartSpec
SCALA_PLIC_TESTS = device.PLICSpec
SCALA_DEBUG_TESTS = debug.DebugModuleSpec debug.JtagTapSpec
SCALA_DEVICE_TESTS = $(SCALA_CLINT_TESTS) device.TLDeviceSpec $(SCALA_UART_TESTS) $(SCALA_PLIC_TESTS)
SCALA_CACHE_TESTS = memory.L1CacheSpec
SCALA_CORE_FAST_TESTS = core.CSRFileSpec core.BranchPredictorSpec core.InstrFetchSpec core.InstrDecodeSpec core.ALUSpec core.StoreBufferSpec
SCALA_CORE_MEM_TESTS = core.LSUSpec
SCALA_FAST_TESTS = $(SCALA_PROFILE_TESTS) $(SCALA_BUS_TESTS) $(SCALA_DEVICE_TESTS) $(SCALA_CACHE_TESTS) core.CSRFileSpec core.InstrFetchSpec
SCALA_SLOW_TESTS = system.IonSoCSpec debug.JtagTapSpec

all: clean emu

emu: payload-rom-hex payload-sram-hex sim-verilog-difftest
	@$(MAKE) -C difftest -j$(DIFFTEST_BUILD_JOBS) emu $(DIFFTEST_MAKE_ARGS)

difftest-emu: sim-verilog-difftest
	@$(MAKE) -C difftest -j$(DIFFTEST_BUILD_JOBS) emu $(DIFFTEST_MAKE_ARGS)
	@touch $(DIFFTEST_EMU)

$(DIFFTEST_EMU): $(DIFFTEST_RTL_STAMP) Makefile
	@$(MAKE) -C difftest -j$(DIFFTEST_BUILD_JOBS) emu $(DIFFTEST_MAKE_ARGS)
	@touch $(DIFFTEST_EMU)

# Build the NEMU shared-object reference used by OpenXiangShan DiffTest. The
# default config matches the expected output name in $(NEMU_SO).
nemu-so: $(NEMU_SO)

$(NEMU_SO): $(NEMU_LOCAL_DEFCONFIG)
	@mkdir -p $(dir $@)
	cp $(NEMU_LOCAL_DEFCONFIG) $(NEMU_HOME)/configs/$(NEMU_DEFCONFIG)
	NEMU_HOME=$(NEMU_HOME) $(MAKE) -C $(NEMU_HOME) $(NEMU_DEFCONFIG)
	NEMU_HOME=$(NEMU_HOME) $(MAKE) -C $(NEMU_HOME) -j$(DIFFTEST_BUILD_JOBS) LDFLAGS="$(NEMU_LDFLAGS)"
	cp $(NEMU_BUILD_SO) $@

$(LINUX_NEMU_LOCAL_DEFCONFIG): $(NEMU_LOCAL_DEFCONFIG) Makefile
	@mkdir -p $(dir $@)
	sed -e 's/^CONFIG_MBASE=.*/CONFIG_MBASE=0x40000000/' \
		-e 's/^CONFIG_MSIZE=.*/CONFIG_MSIZE=0x40010000/' \
		-e 's/^CONFIG_RV_PMA_CHECK=y/# CONFIG_RV_PMA_CHECK is not set/' $< > $@

$(LINUX_NEMU_SO): $(LINUX_NEMU_LOCAL_DEFCONFIG)
	@mkdir -p $(dir $@)
	cp $(LINUX_NEMU_LOCAL_DEFCONFIG) $(NEMU_HOME)/configs/$(LINUX_NEMU_DEFCONFIG)
	NEMU_HOME=$(NEMU_HOME) $(MAKE) -C $(NEMU_HOME) $(LINUX_NEMU_DEFCONFIG)
	NEMU_HOME=$(NEMU_HOME) $(MAKE) -C $(NEMU_HOME) -j$(DIFFTEST_BUILD_JOBS) LDFLAGS="$(NEMU_LDFLAGS)"
	cp $(NEMU_BUILD_SO) $@

nemu-so-linux: $(LINUX_NEMU_SO)

difftest-run-payload: payload-rom-hex payload-sram-hex $(DIFFTEST_EMU) nemu-so
	$(DIFFTEST_EMU) --diff=$(NEMU_SO) --image=$(PAYLOAD_ELF) --max-instr=$(DIFFTEST_MAX_INSTR) --max-cycles=$(DIFFTEST_MAX_CYCLES) -- +ion_rom_lo=$(PAYLOAD_ROM_LO_HEX) +ion_rom_hi=$(PAYLOAD_ROM_HI_HEX)

$(LINUX_DIFFTEST_IMAGE): $(DIFFTEST_LINUX_TRAMPOLINE_ELF) $(LINUX_OPENSBI_FW_JUMP_ELF) $(LINUX_KERNEL_ELF) $(LINUX_DTB) $(LINUX_INITRAMFS) $(DIFFTEST_MERGE_ELF)
	python3 $(DIFFTEST_MERGE_ELF) --output $@ --entry $(LINUX_DIFFTEST_ENTRY) \
		--elf $(LINUX_OPENSBI_FW_JUMP_ELF) --elf $(LINUX_KERNEL_ELF) \
		--blob $(LINUX_INITRAMFS_ADDR):$(LINUX_INITRAMFS) --blob $(LINUX_DTB_ADDR):$(LINUX_DTB) \
		--elf $(DIFFTEST_LINUX_TRAMPOLINE_ELF)

difftest-run-linux: $(LINUX_DIFFTEST_IMAGE) $(DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_LINUX_TRAMPOLINE_ROM_HI_HEX) $(LINUX_DIFFTEST_EMU) nemu-so-linux
	$(LINUX_DIFFTEST_EMU) --diff=$(LINUX_NEMU_SO) --image=$(LINUX_DIFFTEST_IMAGE) \
		--ram-size=$(LINUX_DIFFTEST_RAM_SIZE) --max-instr=$(LINUX_DIFFTEST_MAX_INSTR) \
		--max-cycles=$(LINUX_DIFFTEST_MAX_CYCLES) -- \
		+ion_rom_lo=$(DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX) +ion_rom_hi=$(DIFFTEST_LINUX_TRAMPOLINE_ROM_HI_HEX)

$(DIFFTEST_OPENSBI_SMOKE_IMAGE): $(DIFFTEST_OPENSBI_TRAMPOLINE_ELF) $(OPENSBI_FW_JUMP_ELF) $(SBI_SMOKE_ELF) $(IONSOC_DTB) $(DIFFTEST_MERGE_ELF)
	@mkdir -p $(dir $@)
	python3 $(DIFFTEST_MERGE_ELF) --output $@ --entry $(LINUX_DIFFTEST_ENTRY) \
		--elf $(OPENSBI_FW_JUMP_ELF) --elf $(SBI_SMOKE_ELF) \
		--blob $(OPENSBI_FW_JUMP_FDT_ADDR):$(IONSOC_DTB) --elf $(DIFFTEST_OPENSBI_TRAMPOLINE_ELF)

# Reproducible architectural checkpoint before a real Linux image: ROM ->
# OpenSBI -> MRET -> S-mode SBI console -> stable self-loop.
difftest-run-opensbi-smoke: $(DIFFTEST_OPENSBI_SMOKE_IMAGE) $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_HI_HEX) $(LINUX_DIFFTEST_EMU) nemu-so-linux
	$(LINUX_DIFFTEST_EMU) --diff=$(LINUX_NEMU_SO) --image=$(DIFFTEST_OPENSBI_SMOKE_IMAGE) \
		--ram-size=$(LINUX_DIFFTEST_RAM_SIZE) --max-instr=$(DIFFTEST_OPENSBI_SMOKE_MAX_INSTR) \
		--max-cycles=$(DIFFTEST_OPENSBI_SMOKE_MAX_CYCLES) -- \
		+ion_rom_lo=$(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX) +ion_rom_hi=$(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_HI_HEX)

difftest-regress: $(DIFFTEST_EMU) nemu-so
	@mkdir -p $(DIFFTEST_REGRESS_LOG_DIR)
	@set -e; \
	for p in $(DIFFTEST_REGRESS_PAYLOADS); do \
		log="$(DIFFTEST_REGRESS_LOG_DIR)/$$p.log"; \
		echo "[DIFFTEST] $$p -> $$log"; \
		$(MAKE) --no-print-directory difftest-run-payload PAYLOAD_SRC="$(PAYLOAD_SRC_DIR)/$$p.S" \
			DIFFTEST_MAX_CYCLES=$(DIFFTEST_MAX_CYCLES) DIFFTEST_MAX_INSTR=$(DIFFTEST_MAX_INSTR) > "$$log" 2>&1 || { \
				status=$$?; \
				tail -n 220 "$$log"; \
				exit $$status; \
			}; \
		grep -E "HIT GOOD TRAP|ABORT|instrCnt|cycleCnt|Core 0:" "$$log" | tail -n 8; \
	done

difftest-run-matrix: difftest-regress

.PRECIOUS: $(RISCV_TESTS_BUILD_DIR)/elf/rv64ui-p-%
.PRECIOUS: $(RISCV_TESTS_BUILD_DIR)/elf/rv64um-p-%
.PRECIOUS: $(RISCV_TESTS_BUILD_DIR)/elf/rv64ua-p-%
.PRECIOUS: $(RISCV_TESTS_BUILD_DIR)/elf/rv64uc-p-%

$(RISCV_TESTS_BUILD_DIR)/elf/rv64ui-p-%: $(RISCV_TESTS_ISA_DIR)/rv64ui/%.S $(RISCV_TEST_LDS) $(RISCV_TEST_TRAMPOLINE)
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)/elf
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -D_start=__riscv_test_start -I$(RISCV_TESTS_ISA_DIR)/../env/p -I$(RISCV_TESTS_ISA_DIR)/macros/scalar -c $< -o $@.test.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) -nostdlib -nostartfiles -c $(RISCV_TEST_TRAMPOLINE) -o $@.boot.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -T$(RISCV_TEST_LDS) $@.boot.o $@.test.o -o $@

$(RISCV_TESTS_BUILD_DIR)/elf/rv64um-p-%: $(RISCV_TESTS_ISA_DIR)/rv64um/%.S $(RISCV_TEST_LDS) $(RISCV_TEST_TRAMPOLINE)
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)/elf
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -D_start=__riscv_test_start -I$(RISCV_TESTS_ISA_DIR)/../env/p -I$(RISCV_TESTS_ISA_DIR)/macros/scalar -c $< -o $@.test.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) -nostdlib -nostartfiles -c $(RISCV_TEST_TRAMPOLINE) -o $@.boot.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -T$(RISCV_TEST_LDS) $@.boot.o $@.test.o -o $@

$(RISCV_TESTS_BUILD_DIR)/elf/rv64ua-p-%: $(RISCV_TESTS_ISA_DIR)/rv64ua/%.S $(RISCV_TEST_LDS) $(RISCV_TEST_TRAMPOLINE)
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)/elf
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -D_start=__riscv_test_start -I$(RISCV_TESTS_ISA_DIR)/../env/p -I$(RISCV_TESTS_ISA_DIR)/macros/scalar -c $< -o $@.test.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) -nostdlib -nostartfiles -c $(RISCV_TEST_TRAMPOLINE) -o $@.boot.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -T$(RISCV_TEST_LDS) $@.boot.o $@.test.o -o $@

$(RISCV_TESTS_BUILD_DIR)/elf/rv64uc-p-%: $(RISCV_TESTS_ISA_DIR)/rv64uc/%.S $(RISCV_TEST_LDS) $(RISCV_TEST_TRAMPOLINE)
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)/elf
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -D_start=__riscv_test_start -I$(RISCV_TESTS_ISA_DIR)/../env/p -I$(RISCV_TESTS_ISA_DIR)/macros/scalar -c $< -o $@.test.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) -nostdlib -nostartfiles -c $(RISCV_TEST_TRAMPOLINE) -o $@.boot.o
	$(CC) -march=$(RISCV_TEST_MARCH) -mabi=$(RISCV_TEST_MABI) $(RISCV_TEST_GCC_OPTS) -T$(RISCV_TEST_LDS) $@.boot.o $@.test.o -o $@

$(RISCV_TESTS_BUILD_DIR)/%-rom-lo.hex $(RISCV_TESTS_BUILD_DIR)/%-rom-hi.hex &: $(RISCV_TESTS_BUILD_DIR)/elf/%
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.text.boot $< $(RISCV_TESTS_BUILD_DIR)/$*.bin
	@od -An -v -tx4 -w4 $(RISCV_TESTS_BUILD_DIR)/$*.bin | awk '{ print $$1 }' > $(RISCV_TESTS_BUILD_DIR)/$*-rom-lo.hex
	@cp $(RISCV_TESTS_BUILD_DIR)/$*-rom-lo.hex $(RISCV_TESTS_BUILD_DIR)/$*-rom-hi.hex

$(RISCV_TESTS_BUILD_DIR)/%-sram.hex: $(RISCV_TESTS_BUILD_DIR)/elf/%
	@mkdir -p $(RISCV_TESTS_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.tohost --only-section=.text.init --only-section=.text --only-section=.data --only-section=.sdata --only-section=.rodata $< $(RISCV_TESTS_BUILD_DIR)/$*-sram.bin
	@od -An -v -tx1 $(RISCV_TESTS_BUILD_DIR)/$*-sram.bin | awk ' \
	    { for (i = 1; i <= NF; i++) bytes[n++] = $$i } \
	    END { \
	        for (w = 0; w < 8192; w++) { \
	            line = ""; \
	            for (b = 7; b >= 0; b--) { \
	                idx = w * 8 + b; \
	                line = line (idx in bytes ? bytes[idx] : "00"); \
	            } \
	            print line; \
	        } \
	    }' > $@

difftest-run-riscv-test: $(RISCV_TEST_ROM_LO_HEX) $(RISCV_TEST_ROM_HI_HEX) $(RISCV_TEST_SRAM_HEX) $(DIFFTEST_EMU) nemu-so
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	@backup="$(PAYLOAD_SRAM_HEX).bak"; \
	had_sram=0; \
	if [ -f "$(PAYLOAD_SRAM_HEX)" ]; then cp "$(PAYLOAD_SRAM_HEX)" "$$backup"; had_sram=1; fi; \
	cp "$(RISCV_TEST_SRAM_HEX)" "$(PAYLOAD_SRAM_HEX)"; \
	set +e; \
	$(DIFFTEST_EMU) --diff=$(NEMU_SO) --image=$(RISCV_TEST_ELF) --max-instr=$(DIFFTEST_MAX_INSTR) --max-cycles=$(DIFFTEST_MAX_CYCLES) -- +ion_rom_lo=$(RISCV_TEST_ROM_LO_HEX) +ion_rom_hi=$(RISCV_TEST_ROM_HI_HEX); \
	status=$$?; \
	if [ "$$had_sram" -eq 1 ]; then mv "$$backup" "$(PAYLOAD_SRAM_HEX)"; else rm -f "$(PAYLOAD_SRAM_HEX)" "$$backup"; fi; \
	exit $$status

difftest-riscv-tests: $(DIFFTEST_EMU) nemu-so
	@mkdir -p $(RISCV_TESTS_LOG_DIR)
	@set -e; \
	for t in $(RISCV_TESTS); do \
		log="$(RISCV_TESTS_LOG_DIR)/$$t.log"; \
		echo "[RISCV-TEST] $$t -> $$log"; \
		$(MAKE) --no-print-directory difftest-run-riscv-test RISCV_TEST=$$t \
			DIFFTEST_MAX_CYCLES=$(DIFFTEST_MAX_CYCLES) DIFFTEST_MAX_INSTR=$(DIFFTEST_MAX_INSTR) > "$$log" 2>&1 || { \
				status=$$?; \
				tail -n 220 "$$log"; \
				exit $$status; \
			}; \
		grep -E "HIT GOOD TRAP|ABORT|instrCnt|cycleCnt|Core 0:" "$$log" | tail -n 8; \
	done

difftest-riscv-tests-all:
	@$(MAKE) --no-print-directory difftest-riscv-tests RISCV_TESTS="$(RISCV_TESTS_ALL)"

print-riscv-tests-all:
	@printf '%s\n' $(RISCV_TESTS_ALL)

$(RTL_STAMP) $(FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill
	mill -i IonSoC.test.runMain $(SIM_TOP)
	@touch $(RTL_STAMP)

sim-verilog: $(RTL_STAMP)

# The MCU RTL is the default platform contract made explicit: RV64IMAC(+small B
# subset), no MMU, CLINT+PLIC+UART, and default 64 KiB SRAM.
$(MCU_RTL_STAMP) $(MCU_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill
	mill -i IonSoC.test.runMain sim.McuTopMain
	@touch $(MCU_RTL_STAMP)

sim-verilog-mcu: $(MCU_RTL_STAMP)

$(ICACHE_RTL_STAMP) $(ICACHE_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill
	mill -i IonSoC.test.runMain sim.ICacheTopMain
	@touch $(ICACHE_RTL_STAMP)

sim-verilog-icache: $(ICACHE_RTL_STAMP)

$(FIRMWARE_RTL_STAMP) $(FIRMWARE_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill
	mill -i IonSoC.test.runMain sim.FirmwareTopMain
	@touch $(FIRMWARE_RTL_STAMP)

sim-verilog-firmware: $(FIRMWARE_RTL_STAMP)

$(LINUX_RTL_STAMP) $(LINUX_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill
	mill -i IonSoC.test.runMain sim.LinuxTopMain
	@touch $(LINUX_RTL_STAMP)

sim-verilog-linux: $(LINUX_RTL_STAMP)

# DiffTest RTL generation emits the official OpenXiangShan probe wrappers and
# generated C++ state headers under build/generated-src. Keep it separate from
# normal Verilator flows so ordinary bring-up does not require NEMU/libdifftest.
$(DIFFTEST_RTL_STAMP) $(DIFFTEST_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill $(DIFFTEST_CONFIG_OVERRIDE)
	NOOP_HOME=$(NOOP_HOME) mill -i IonSoC.test.runMain sim.DifftestTopMain
	@cp $(DIFFTEST_CONFIG_OVERRIDE) $(NOOP_HOME)/build/generated-src/ionsoc-config-override.cpp
	@touch $(DIFFTEST_RTL_STAMP)

sim-verilog-difftest: $(DIFFTEST_RTL_STAMP)

$(LINUX_DIFFTEST_RTL_STAMP) $(LINUX_DIFFTEST_FILE_LIST) &: $(RTL_SCALA_SOURCES) build.mill $(DIFFTEST_CONFIG_OVERRIDE)
	NOOP_HOME=$(NOOP_HOME) mill -i IonSoC.test.runMain sim.LinuxDifftestTopMain
	@cp $(DIFFTEST_CONFIG_OVERRIDE) $(NOOP_HOME)/build/generated-src/ionsoc-config-override.cpp
	@touch $(LINUX_DIFFTEST_RTL_STAMP)

sim-verilog-difftest-linux: $(LINUX_DIFFTEST_RTL_STAMP)

$(LINUX_DIFFTEST_WORK_DIR)/build/.generated-src.stamp: $(LINUX_DIFFTEST_RTL_STAMP) $(DIFFTEST_CONFIG_OVERRIDE)
	@mkdir -p $(LINUX_DIFFTEST_WORK_DIR)/build/generated-src
	@cp -a $(NOOP_HOME)/build/generated-src/. $(LINUX_DIFFTEST_WORK_DIR)/build/generated-src/
	@touch $@

$(LINUX_DIFFTEST_EMU): $(LINUX_DIFFTEST_WORK_DIR)/build/.generated-src.stamp Makefile
	@$(MAKE) -C difftest -j$(DIFFTEST_BUILD_JOBS) emu $(LINUX_DIFFTEST_MAKE_ARGS)
	@cp $(LINUX_DIFFTEST_WORK_EMU) $@

difftest-emu-linux: $(LINUX_DIFFTEST_EMU)

test-fast:
	mill -i IonSoC.test.testOnly $(SCALA_FAST_TESTS)

test-profile:
	mill -i IonSoC.test.testOnly $(SCALA_PROFILE_TESTS)

test-bus:
	mill -i IonSoC.test.testOnly $(SCALA_BUS_TESTS)

test-devices:
	mill -i IonSoC.test.testOnly $(SCALA_DEVICE_TESTS)

test-clint:
	mill -i IonSoC.test.testOnly $(SCALA_CLINT_TESTS)

test-uart:
	mill -i IonSoC.test.testOnly $(SCALA_UART_TESTS)

test-plic:
	mill -i IonSoC.test.testOnly $(SCALA_PLIC_TESTS)

test-debug:
	mill -i IonSoC.test.testOnly $(SCALA_DEBUG_TESTS)

test-cache:
	mill -i IonSoC.test.testOnly $(SCALA_CACHE_TESTS)

test-core-fast:
	mill -i IonSoC.test.testOnly $(SCALA_CORE_FAST_TESTS)

test-core-mem:
	mill -i IonSoC.test.testOnly $(SCALA_CORE_MEM_TESTS)

test-slow:
	mill -i IonSoC.test.testOnly $(SCALA_SLOW_TESTS)

# help:
# 	mill -i IonSoC.test.runMain $(SIM_TOP) --help

payload:
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $(PAYLOAD_ELF) $(PAYLOAD_SRC)
	$(OBJCOPY) -O binary --only-section=.text $(PAYLOAD_ELF) $(PAYLOAD)

payload-rom-hex: $(PAYLOAD_ROM_LO_HEX) $(PAYLOAD_ROM_HI_HEX)

$(PAYLOAD_ROM_LO_HEX) $(PAYLOAD_ROM_HI_HEX) &: payload
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	@od -An -v -tx4 -w4 $(PAYLOAD) | awk '{ print $$1 }' > $(PAYLOAD_ROM_LO_HEX)
	@cp $(PAYLOAD_ROM_LO_HEX) $(PAYLOAD_ROM_HI_HEX)

payload-sram-hex: $(PAYLOAD_SRAM_HEX)

$(PAYLOAD_SRAM_HEX): payload
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.data $(PAYLOAD_ELF) $(PAYLOAD_SRAM_BIN)
	@od -An -v -tx1 $(PAYLOAD_SRAM_BIN) | awk ' \
	    { for (i = 1; i <= NF; i++) bytes[n++] = $$i } \
	    END { \
	        for (w = 0; w < 8192; w++) { \
	            line = ""; \
	            for (b = 7; b >= 0; b--) { \
	                idx = w * 8 + b; \
	                line = line (idx in bytes ? bytes[idx] : "00"); \
	            } \
	            print line; \
	        } \
	    }' > $(PAYLOAD_SRAM_HEX)

$(TIMER_ELF): $(PAYLOAD_SRC_DIR)/timer.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(BASIC_ELF): $(PAYLOAD_SRC_DIR)/basic.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(CLINT32_ELF): $(PAYLOAD_SRC_DIR)/clint32.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(TLERROR_ELF): $(PAYLOAD_SRC_DIR)/tlerror.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(AMO_ELF): $(PAYLOAD_SRC_DIR)/amo.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(HAZARD_ELF): $(PAYLOAD_SRC_DIR)/hazard.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(PIPELINE_REISSUE_ELF): $(PAYLOAD_SRC_DIR)/pipeline_reissue.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=rv$(WORD_LEN)imac_zicsr -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(LOAD_STALL_BYPASS_ELF): $(PAYLOAD_SRC_DIR)/load_stall_bypass.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=rv$(WORD_LEN)imac_zicsr -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(BSWAP_ELF): $(PAYLOAD_SRC_DIR)/bswap.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=rv$(WORD_LEN)imac_zicsr -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(FIRMWARE_BSWAP_ELF): $(PAYLOAD_SRC_DIR)/bswap.S $(FIRMWARE_BSWAP_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=rv$(WORD_LEN)imac_zicsr -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(FIRMWARE_BSWAP_LDS) -o $@ $<

$(LDADDR_ELF): $(PAYLOAD_SRC_DIR)/ldaddr.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(MISALIGN_LD_ELF): $(PAYLOAD_SRC_DIR)/misalign_ld.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(PERF_ELF): $(PAYLOAD_SRC_DIR)/perf.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(BITMANIP_ELF): $(PAYLOAD_SRC_DIR)/bitmanip.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=rv$(WORD_LEN)imac_zba_zbb_zbs_zicsr -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(PLIC_ELF): $(PAYLOAD_SRC_DIR)/plic.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(PLIC_S_ELF): $(PAYLOAD_SRC_DIR)/plic_s.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(UART_IRQ_ELF): $(PAYLOAD_SRC_DIR)/uart_irq.S $(PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(SBI_SMOKE_ELF): $(PAYLOAD_SRC_DIR)/sbi_smoke.S $(SBI_PAYLOAD_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(SBI_PAYLOAD_LDS) -o $@ $<

$(FIRMWARE_PROBE_ELF): $(PAYLOAD_SRC_DIR)/firmware_probe.S $(FIRMWARE_LDS)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(FIRMWARE_LDS) -o $@ $<

$(FIRMWARE_TRAMPOLINE_ELF): $(PAYLOAD_SRC_DIR)/firmware_trampoline.S
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles -T$(PAYLOAD_LDS) -o $@ $<

$(FIRMWARE_TRAMPOLINE_ROM_LO_HEX) $(FIRMWARE_TRAMPOLINE_ROM_HI_HEX) &: $(FIRMWARE_TRAMPOLINE_ELF)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.text $< $(PAYLOAD_BUILD_DIR)/firmware_trampoline.bin
	@od -An -v -tx4 -w4 $(PAYLOAD_BUILD_DIR)/firmware_trampoline.bin | awk '{ print $$1 }' > $(FIRMWARE_TRAMPOLINE_ROM_LO_HEX)
	@cp $(FIRMWARE_TRAMPOLINE_ROM_LO_HEX) $(FIRMWARE_TRAMPOLINE_ROM_HI_HEX)

$(DIFFTEST_LINUX_TRAMPOLINE_ELF): $(PAYLOAD_SRC_DIR)/firmware_trampoline.S
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles \
		-DION_DEFAULT_BOOT_ARGS -DION_DEFAULT_DTB_ADDR=$(LINUX_DTB_ADDR) \
		-DION_DEFAULT_PAYLOAD_ADDR=$(LINUX_KERNEL_ADDR) -T$(PAYLOAD_LDS) -o $@ $<

$(DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_LINUX_TRAMPOLINE_ROM_HI_HEX) &: $(DIFFTEST_LINUX_TRAMPOLINE_ELF)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.text $< $(PAYLOAD_BUILD_DIR)/difftest_linux_trampoline.bin
	@od -An -v -tx4 -w4 $(PAYLOAD_BUILD_DIR)/difftest_linux_trampoline.bin | awk '{ print $$1 }' > $(DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX)
	@cp $(DIFFTEST_LINUX_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_LINUX_TRAMPOLINE_ROM_HI_HEX)

$(DIFFTEST_OPENSBI_TRAMPOLINE_ELF): $(PAYLOAD_SRC_DIR)/firmware_trampoline.S
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(CC) -march=$(PAYLOAD_MARCH) -mabi=$(PAYLOAD_MABI) -nostdlib -nostartfiles \
		-DION_DEFAULT_BOOT_ARGS -DION_DEFAULT_DTB_ADDR=$(OPENSBI_FW_JUMP_FDT_ADDR) \
		-DION_DEFAULT_PAYLOAD_ADDR=$(OPENSBI_FW_JUMP_ADDR) -T$(PAYLOAD_LDS) -o $@ $<

$(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_HI_HEX) &: $(DIFFTEST_OPENSBI_TRAMPOLINE_ELF)
	@mkdir -p $(PAYLOAD_BUILD_DIR)
	$(OBJCOPY) -O binary --only-section=.text $< $(PAYLOAD_BUILD_DIR)/difftest_opensbi_trampoline.bin
	@od -An -v -tx4 -w4 $(PAYLOAD_BUILD_DIR)/difftest_opensbi_trampoline.bin | awk '{ print $$1 }' > $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX)
	@cp $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_LO_HEX) $(DIFFTEST_OPENSBI_TRAMPOLINE_ROM_HI_HEX)

$(IONSOC_DTS): $(RTL_SCALA_SOURCES) build.mill
	@mkdir -p $(dir $@)
	mill -i IonSoC.test.runMain sim.DeviceTreeMain $@ firmware

$(IONSOC_DTB): $(IONSOC_DTS)
	@mkdir -p $(BUILD_DIR)
	dtc -I dts -O dtb -o $@ $<

sim-dts: $(IONSOC_DTS)

sim-dtb: $(IONSOC_DTB)

$(LINUX_DTS_CONFIG_STAMP): Makefile
	@mkdir -p $(dir $@)
	@rm -f $(BUILD_DIR)/linux/.dts-config.*
	@touch $@

$(LINUX_INIT): $(LINUX_INIT_SOURCE)
	@mkdir -p $(dir $@)
	$(RISCV_LINUX_CC) $(LINUX_INIT_CFLAGS) -o $@ $<

$(LINUX_INITRAMFS): $(LINUX_INIT) $(LINUX_INITRAMFS_PACKER)
	python3 $(LINUX_INITRAMFS_PACKER) --init $(LINUX_INIT) --output $@

linux-initramfs: $(LINUX_INITRAMFS)

$(LINUX_DTS): $(RTL_SCALA_SOURCES) build.mill $(LINUX_DTS_CONFIG_STAMP) $(LINUX_INITRAMFS)
	@mkdir -p $(dir $@)
	@initrd_size=$$(stat -c%s $(LINUX_INITRAMFS)); \
		initrd_end=$$(printf '0x%x' $$(( $(LINUX_INITRAMFS_ADDR) + initrd_size ))); \
		if [ $$((initrd_end)) -ge $$(( $(LINUX_DTB_ADDR) )) ]; then \
			echo "initramfs overlaps DTB: $$initrd_end >= $(LINUX_DTB_ADDR)"; exit 1; \
		fi; \
		mill -i IonSoC.test.runMain sim.DeviceTreeMain $@ linux "$(LINUX_BOOTARGS_EXTRA)" \
			$(LINUX_INITRAMFS_ADDR) $$initrd_end

$(LINUX_DTB): $(LINUX_DTS)
	@mkdir -p $(BUILD_DIR)
	dtc -I dts -O dtb -o $@ $<

sim-dts-linux: $(LINUX_DTS)

sim-dtb-linux: $(LINUX_DTB)

$(LINUX_IMAGE_ELF):
	@if [ ! -f "$(LINUX_IMAGE)" ]; then \
		echo "Linux raw Image not found: $(LINUX_IMAGE)"; \
		echo "Set LINUX_IMAGE=/path/to/arch/riscv/boot/Image or LINUX_KERNEL_ELF=/path/to/kernel.elf."; \
		exit 1; \
	fi
	@mkdir -p $(dir $@)
	$(COMPILER)ld -Ttext=$(LINUX_KERNEL_ADDR) -b binary "$(LINUX_IMAGE)" -o $@

linux-image-elf: $(LINUX_IMAGE_ELF)

$(RUSTSBI_FW_ELF): $(IONSOC_DTB)
	@if [ "$@" != "$(DEFAULT_RUSTSBI_FW_ELF)" ]; then \
		echo "RustSBI prebuilt ELF not found at $@."; \
		echo "Provide an existing RUSTSBI_FW_ELF path, or use the default RustSBI source tree at $(RUSTSBI_DIR)."; \
		exit 1; \
	fi
	@if [ ! -d "$(RUSTSBI_DIR)" ]; then \
		echo "RustSBI source not found at $(RUSTSBI_DIR)."; \
		echo "Clone or copy RustSBI there, or run with RUSTSBI_FW_ELF=/path/to/rustsbi-prototyper-jump.elf."; \
		exit 1; \
	fi
	@if [ ! -f "$(RUSTSBI_DIR)/$(RUSTSBI_CONFIG)" ]; then \
		echo "RustSBI IonSoC config not found at $(RUSTSBI_DIR)/$(RUSTSBI_CONFIG)."; \
		echo "Set RUSTSBI_CONFIG=relative/path/to/ionsoc.toml or RUSTSBI_FW_ELF=/path/to/prebuilt.elf."; \
		exit 1; \
	fi
	cd $(RUSTSBI_DIR) && PROTOTYPER_LINK_START_ADDRESS=0x40000000 PROTOTYPER_PAYLOAD_START_ADDRESS=0x40100000 cargo prototyper --jump -c $(RUSTSBI_CONFIG) --fdt ../../build/ionsoc.dtb

$(OPENSBI_FW_JUMP_ELF):
	@if [ ! -d "$(OPENSBI_DIR)" ]; then \
		echo "OpenSBI source not found at $(OPENSBI_DIR)."; \
		echo "Clone or copy OpenSBI there, or run with OPENSBI_FW_JUMP_ELF=/path/to/fw_jump.elf."; \
		exit 1; \
	fi
	$(MAKE) -C $(OPENSBI_DIR) PLATFORM=$(OPENSBI_PLATFORM) CROSS_COMPILE=$(OPENSBI_CROSS_COMPILE) PLATFORM_RISCV_ISA=$(OPENSBI_PLATFORM_RISCV_ISA) FW_TEXT_START=0x40000000 FW_JUMP_ADDR=$(OPENSBI_FW_JUMP_ADDR) FW_JUMP_FDT_ADDR=$(OPENSBI_FW_JUMP_FDT_ADDR) FW_OPTIONS=0

$(LINUX_OPENSBI_FW_JUMP_ELF):
	@if [ ! -d "$(OPENSBI_DIR)" ]; then \
		echo "OpenSBI source not found at $(OPENSBI_DIR)."; \
		echo "Clone or copy OpenSBI there, or run with LINUX_OPENSBI_FW_JUMP_ELF=/path/to/fw_jump.elf."; \
		exit 1; \
	fi
	$(MAKE) -C $(OPENSBI_DIR) O=$(abspath $(LINUX_OPENSBI_BUILD_DIR)) PLATFORM=$(OPENSBI_PLATFORM) CROSS_COMPILE=$(OPENSBI_CROSS_COMPILE) PLATFORM_RISCV_ISA=$(OPENSBI_PLATFORM_RISCV_ISA) FW_TEXT_START=0x40000000 FW_JUMP_ADDR=$(LINUX_KERNEL_ADDR) FW_JUMP_FDT_ADDR=$(LINUX_DTB_ADDR) FW_OPTIONS=0

$(VSOC_BIN): $(RTL_STAMP) $(TB) $(FILE_LIST) $(SIM_RTL_DIR)/filelist.f Makefile
	$(VERILATOR) --cc -I$(SIM_RTL_DIR) -I$(SYSTEM_VERILOG_DIR) -f $(FILE_LIST) -f $(SIM_RTL_DIR)/filelist.f --exe $(TB) $(VERILATOR_PUBLIC_FLAGS) $(VERILATOR_TRACE_FLAGS) --Mdir $(VERILATOR_OBJ_DIR) --top-module SimTop --prefix VSoc
	@$(MAKE) -C $(VERILATOR_OBJ_DIR) -f VSoc.mk VSoc -j $(VERILATOR_BUILD_JOBS) OBJCACHE="$(VERILATOR_OBJCACHE)" OPT_FAST="$(VERILATOR_OPT_FAST)" OPT_SLOW="$(VERILATOR_OPT_SLOW)"

$(MCU_VSOC_BIN): $(MCU_RTL_STAMP) $(TB) $(MCU_FILE_LIST) $(SIM_RTL_DIR)/filelist.f Makefile
	$(VERILATOR) --cc -I$(SIM_RTL_DIR) -I$(MCU_SYSTEM_VERILOG_DIR) -f $(MCU_FILE_LIST) -f $(SIM_RTL_DIR)/filelist.f --exe $(TB) $(VERILATOR_PUBLIC_FLAGS) $(VERILATOR_TRACE_FLAGS) --Mdir $(MCU_VERILATOR_OBJ_DIR) --top-module SimTop --prefix VSoc
	@$(MAKE) -C $(MCU_VERILATOR_OBJ_DIR) -f VSoc.mk VSoc -j $(VERILATOR_BUILD_JOBS) OBJCACHE="$(VERILATOR_OBJCACHE)" OPT_FAST="$(VERILATOR_OPT_FAST)" OPT_SLOW="$(VERILATOR_OPT_SLOW)"

$(ICACHE_VSOC_BIN): $(ICACHE_RTL_STAMP) $(TB) $(ICACHE_FILE_LIST) $(SIM_RTL_DIR)/filelist.f Makefile
	$(VERILATOR) --cc -I$(SIM_RTL_DIR) -I$(ICACHE_SYSTEM_VERILOG_DIR) -f $(ICACHE_FILE_LIST) -f $(SIM_RTL_DIR)/filelist.f --exe $(TB) $(VERILATOR_PUBLIC_FLAGS) $(VERILATOR_TRACE_FLAGS) --Mdir $(ICACHE_VERILATOR_OBJ_DIR) --top-module SimTop --prefix VSoc
	@$(MAKE) -C $(ICACHE_VERILATOR_OBJ_DIR) -f VSoc.mk VSoc -j $(VERILATOR_BUILD_JOBS) OBJCACHE="$(VERILATOR_OBJCACHE)" OPT_FAST="$(VERILATOR_OPT_FAST)" OPT_SLOW="$(VERILATOR_OPT_SLOW)"

$(FIRMWARE_VSOC_BIN): $(FIRMWARE_RTL_STAMP) $(TB) $(FIRMWARE_FILE_LIST) $(SIM_RTL_DIR)/filelist.f Makefile
	$(VERILATOR) --cc -I$(SIM_RTL_DIR) -I$(FIRMWARE_SYSTEM_VERILOG_DIR) -f $(FIRMWARE_FILE_LIST) -f $(SIM_RTL_DIR)/filelist.f --exe $(TB) $(VERILATOR_PUBLIC_FLAGS) $(VERILATOR_TRACE_FLAGS) --Mdir $(FIRMWARE_VERILATOR_OBJ_DIR) --top-module SimTop --prefix VSoc
	@$(MAKE) -C $(FIRMWARE_VERILATOR_OBJ_DIR) -f VSoc.mk VSoc -j $(VERILATOR_BUILD_JOBS) OBJCACHE="$(VERILATOR_OBJCACHE)" OPT_FAST="$(VERILATOR_OPT_FAST)" OPT_SLOW="$(VERILATOR_OPT_SLOW)"

$(LINUX_VSOC_BIN): $(LINUX_RTL_STAMP) $(TB) $(LINUX_FILE_LIST) $(SIM_RTL_DIR)/filelist.f Makefile
	$(VERILATOR) --cc -I$(SIM_RTL_DIR) -I$(LINUX_SYSTEM_VERILOG_DIR) -f $(LINUX_FILE_LIST) -f $(SIM_RTL_DIR)/filelist.f --exe $(TB) $(VERILATOR_PUBLIC_FLAGS) $(VERILATOR_TRACE_FLAGS) -CFLAGS "$(LINUX_VERILATOR_CFLAGS)" --Mdir $(LINUX_VERILATOR_OBJ_DIR) --top-module SimTop --prefix VSoc
	@$(MAKE) -C $(LINUX_VERILATOR_OBJ_DIR) -f VSoc.mk VSoc -j $(VERILATOR_BUILD_JOBS) OBJCACHE="$(VERILATOR_OBJCACHE)" OPT_FAST="$(VERILATOR_OPT_FAST)" OPT_SLOW="$(VERILATOR_OPT_SLOW)"

verilator-build: $(VSOC_BIN)

verilator-build-mcu: $(MCU_VSOC_BIN)

verilator-build-icache: $(ICACHE_VSOC_BIN)

verilator-build-firmware: $(FIRMWARE_VSOC_BIN)

verilator-build-linux: $(LINUX_VSOC_BIN)

verilator: payload $(VSOC_BIN)
	./$(VSOC_BIN) $(RUN_ARGS)

verilator-jtag: payload $(VSOC_BIN)
	env ION_JTAG_ONLY=1 ION_JTAG_RBB_PORT=$${ION_JTAG_RBB_PORT:-9824} ./$(VSOC_BIN) $(RUN_ARGS)

openocd-smoke: payload $(VSOC_BIN)
	@mkdir -p $(BUILD_DIR)
	@set -e; \
	port=$${ION_JTAG_RBB_PORT:-9824}; \
	log="$(BUILD_DIR)/openocd-smoke.log"; \
	simlog="$(BUILD_DIR)/verilator-jtag-smoke.log"; \
	env ION_JTAG_ONLY=1 ION_JTAG_RBB_PORT=$$port ION_MAX_CYCLES=0 ./$(VSOC_BIN) > $$simlog 2>&1 & \
	sim_pid=$$!; \
	trap 'kill $$sim_pid >/dev/null 2>&1 || true' EXIT; \
	for i in $$(seq 1 50); do \
		if grep -q "remote-bitbang listening" $$simlog; then break; fi; \
		sleep 0.1; \
	done; \
	$(OPENOCD) -s . -f openocd/ionsoc-rbb-smoke.cfg > $$log 2>&1; \
	kill $$sim_pid >/dev/null 2>&1 || true; \
	trap - EXIT; \
	grep -q "ION_OPENOCD_SBA_OK" $$log; \
	! grep -q "Unexpected error during fence" $$log; \
	echo "OpenOCD smoke passed. Logs: $$log $$simlog"

verilator-run-timer: $(TIMER_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload timer S!!P $(TIMER_ELF)

verilator-run-clint32: $(CLINT32_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload clint32 CP $(CLINT32_ELF)

verilator-run-tlerror: $(TLERROR_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload tlerror EP $(TLERROR_ELF)

verilator-run-amo: $(AMO_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload amo AP $(AMO_ELF)

verilator-run-hazard: $(HAZARD_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload hazard HP $(HAZARD_ELF)

verilator-run-pipeline-reissue: $(PIPELINE_REISSUE_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload pipeline_reissue RP $(PIPELINE_REISSUE_ELF)

verilator-run-load-stall-bypass: $(LOAD_STALL_BYPASS_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload load_stall_bypass BP $(LOAD_STALL_BYPASS_ELF)

verilator-run-bswap: $(BSWAP_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload bswap BP $(BSWAP_ELF)

verilator-run-firmware-bswap: $(FIRMWARE_BSWAP_ELF) $(FIRMWARE_VSOC_BIN)
	ION_SRAM_BASE=0x40000000 ION_SRAM_SIZE=0x01000000 ION_MAX_CYCLES=20000 ./$(FIRMWARE_VSOC_BIN) --payload-firmware bswap BP $(FIRMWARE_BSWAP_ELF)

verilator-run-ldaddr: $(LDADDR_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload ldaddr LP $(LDADDR_ELF)

verilator-run-misalign-ld: $(MISALIGN_LD_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload misalign_ld MP $(MISALIGN_LD_ELF)

verilator-run-perf: $(PERF_ELF) $(VSOC_BIN)
	ION_PERF=1 ION_MAX_CYCLES=2000000 ./$(VSOC_BIN) --payload perf P $(PERF_ELF)

verilator-run-bitmanip: $(BITMANIP_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload bitmanip BP $(BITMANIP_ELF)

verilator-run-plic: $(PLIC_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload plic XP $(PLIC_ELF)

verilator-run-plic-s: $(PLIC_S_ELF) $(VSOC_BIN)
	./$(VSOC_BIN) --payload plic_s SIP $(PLIC_S_ELF)

verilator-run-uart-irq: $(UART_IRQ_ELF) $(VSOC_BIN)
	ION_UART_RX_CYCLE=160 ION_UART_RX_BYTE=0x5a ./$(VSOC_BIN) --payload uart_irq UP $(UART_IRQ_ELF)

# Firmware profile smoke: ROM trampoline -> M-mode SBI firmware in SRAM -> S-mode payload.
# The harness checks UART output, exit sentinel, and that execution reached both
# firmware SRAM and the S-mode payload window.
verilator-run-rustsbi: $(RUSTSBI_FW_ELF) $(SBI_SMOKE_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(IONSOC_DTB) $(FIRMWARE_VSOC_BIN)
	ION_SRAM_BASE=0x40000000 ION_SRAM_SIZE=0x01000000 ION_DTB_ADDR=0x40f00000 ION_BOOT_A1=0x40f00000 ION_BOOT_A2=0x40100000 ION_MAX_CYCLES=8000000 ION_EXPECT_UART="IonSoC SBI smoke" ./$(FIRMWARE_VSOC_BIN) --rustsbi $(FIRMWARE_TRAMPOLINE_ELF) $(RUSTSBI_FW_ELF) $(SBI_SMOKE_ELF) $(IONSOC_DTB)

rustsbi-smoke: verilator-run-rustsbi

verilator-run-opensbi: $(OPENSBI_FW_JUMP_ELF) $(SBI_SMOKE_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(IONSOC_DTB) $(FIRMWARE_VSOC_BIN)
	ION_SRAM_BASE=0x40000000 ION_SRAM_SIZE=0x01000000 ION_DTB_ADDR=0x40f00000 ION_BOOT_A1=0x40f00000 ION_BOOT_A2=0x40100000 ION_MAX_CYCLES=20000000 ION_EXPECT_UART="IonSoC SBI smoke" ION_ACCEPT_UART_MATCH=1 ION_STOP_ON_UART_MATCH=1 ./$(FIRMWARE_VSOC_BIN) --sbi-firmware $(FIRMWARE_TRAMPOLINE_ELF) $(OPENSBI_FW_JUMP_ELF) $(SBI_SMOKE_ELF) $(IONSOC_DTB)

opensbi-smoke: verilator-run-opensbi

verilator-run-firmware-probe: $(FIRMWARE_PROBE_ELF) $(SBI_SMOKE_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(IONSOC_DTB) $(FIRMWARE_VSOC_BIN)
	ION_EXPECT_UART="IonSoC firmware probe" ION_REQUIRE_PAYLOAD_ENTRY=0 ION_TRACE_BOOT=1 ION_SRAM_BASE=0x40000000 ION_SRAM_SIZE=0x01000000 ION_DTB_ADDR=0x40f00000 ION_BOOT_A1=0x40f00000 ION_BOOT_A2=0x40100000 ION_MAX_CYCLES=200000 ./$(FIRMWARE_VSOC_BIN) --rustsbi $(FIRMWARE_TRAMPOLINE_ELF) $(FIRMWARE_PROBE_ELF) $(SBI_SMOKE_ELF) $(IONSOC_DTB)

verilator-run-linux-profile-probe: $(FIRMWARE_PROBE_ELF) $(SBI_SMOKE_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(LINUX_DTB) $(LINUX_VSOC_BIN)
	ION_EXPECT_UART="IonSoC firmware probe" ION_REQUIRE_PAYLOAD_ENTRY=0 ION_TRACE_BOOT=1 ION_SRAM_BASE=$(LINUX_SRAM_BASE) ION_SRAM_SIZE=$(LINUX_SRAM_SIZE) ION_DTB_ADDR=$(LINUX_DTB_ADDR) ION_INITRD_PATH=$(LINUX_INITRAMFS) ION_INITRD_ADDR=$(LINUX_INITRAMFS_ADDR) ION_BOOT_A1=$(LINUX_DTB_ADDR) ION_BOOT_A2=0x40100000 ION_MAX_CYCLES=200000 ./$(LINUX_VSOC_BIN) --rustsbi $(FIRMWARE_TRAMPOLINE_ELF) $(FIRMWARE_PROBE_ELF) $(SBI_SMOKE_ELF) $(LINUX_DTB)

verilator-run-linux: $(LINUX_KERNEL_ELF)
	@if [ -z "$(LINUX_KERNEL_ELF)" ]; then \
		echo "Set LINUX_KERNEL_ELF=/path/to/riscv64 Linux ELF before running this target."; \
		exit 1; \
	fi
	@if [ ! -f "$(LINUX_KERNEL_ELF)" ]; then \
		echo "Linux kernel ELF not found: $(LINUX_KERNEL_ELF)"; \
		exit 1; \
	fi
	@$(MAKE) --no-print-directory $(LINUX_OPENSBI_FW_JUMP_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(LINUX_DTB) $(LINUX_VSOC_BIN)
	ION_REQUIRE_PAYLOAD_ENTRY=1 ION_TRACE_BOOT=1 ION_DISABLE_EXIT_CHECK=1 ION_EXPECT_UART="$(LINUX_EXPECT_UART)" ION_ACCEPT_UART_MATCH=1 ION_STOP_ON_UART_MATCH=1 ION_SRAM_BASE=$(LINUX_SRAM_BASE) ION_SRAM_SIZE=$(LINUX_SRAM_SIZE) ION_DTB_ADDR=$(LINUX_DTB_ADDR) ION_INITRD_PATH=$(LINUX_INITRAMFS) ION_INITRD_ADDR=$(LINUX_INITRAMFS_ADDR) ION_BOOT_A1=$(LINUX_DTB_ADDR) ION_BOOT_A2=$(LINUX_KERNEL_ADDR) ION_MAX_CYCLES=$(LINUX_MAX_CYCLES) ./$(LINUX_VSOC_BIN) --sbi-firmware $(FIRMWARE_TRAMPOLINE_ELF) $(LINUX_OPENSBI_FW_JUMP_ELF) $(LINUX_KERNEL_ELF) $(LINUX_DTB)

verilator-run-linux-probe: $(LINUX_KERNEL_ELF)
	@$(MAKE) --no-print-directory $(LINUX_OPENSBI_FW_JUMP_ELF) $(FIRMWARE_TRAMPOLINE_ELF) $(LINUX_DTB) $(LINUX_VSOC_BIN)
	ION_REQUIRE_PAYLOAD_ENTRY=0 ION_STOP_ON_PAYLOAD_ENTRY=1 ION_TRACE_BOOT=1 ION_DISABLE_EXIT_CHECK=1 ION_SRAM_BASE=$(LINUX_SRAM_BASE) ION_SRAM_SIZE=$(LINUX_SRAM_SIZE) ION_DTB_ADDR=$(LINUX_DTB_ADDR) ION_INITRD_PATH=$(LINUX_INITRAMFS) ION_INITRD_ADDR=$(LINUX_INITRAMFS_ADDR) ION_BOOT_A1=$(LINUX_DTB_ADDR) ION_BOOT_A2=$(LINUX_KERNEL_ADDR) ION_MAX_CYCLES=$(LINUX_PROBE_MAX_CYCLES) ./$(LINUX_VSOC_BIN) --sbi-firmware $(FIRMWARE_TRAMPOLINE_ELF) $(LINUX_OPENSBI_FW_JUMP_ELF) $(LINUX_KERNEL_ELF) $(LINUX_DTB)

verilator-clint32: verilator-run-clint32

verilator-tlerror: verilator-run-tlerror

regress: $(VSOC_BIN) $(TIMER_ELF) $(CLINT32_ELF) $(TLERROR_ELF) $(AMO_ELF) $(HAZARD_ELF) $(PIPELINE_REISSUE_ELF) $(BITMANIP_ELF) $(PLIC_ELF) $(PLIC_S_ELF) $(UART_IRQ_ELF)
	./$(VSOC_BIN) --payload timer S!!P $(TIMER_ELF)
	./$(VSOC_BIN) --payload clint32 CP $(CLINT32_ELF)
	./$(VSOC_BIN) --payload tlerror EP $(TLERROR_ELF)
	./$(VSOC_BIN) --payload amo AP $(AMO_ELF)
	./$(VSOC_BIN) --payload hazard HP $(HAZARD_ELF)
	./$(VSOC_BIN) --payload pipeline_reissue RP $(PIPELINE_REISSUE_ELF)
	./$(VSOC_BIN) --payload bitmanip BP $(BITMANIP_ELF)
	./$(VSOC_BIN) --payload plic XP $(PLIC_ELF)
	./$(VSOC_BIN) --payload plic_s SIP $(PLIC_S_ELF)
	ION_UART_RX_CYCLE=160 ION_UART_RX_BYTE=0x5a ./$(VSOC_BIN) --payload uart_irq UP $(UART_IRQ_ELF)

regress-mcu: $(MCU_VSOC_BIN) $(TIMER_ELF) $(CLINT32_ELF) $(TLERROR_ELF) $(AMO_ELF) $(HAZARD_ELF) $(PIPELINE_REISSUE_ELF) $(BITMANIP_ELF) $(PLIC_ELF) $(PLIC_S_ELF) $(UART_IRQ_ELF)
	./$(MCU_VSOC_BIN) --payload timer S!!P $(TIMER_ELF)
	./$(MCU_VSOC_BIN) --payload clint32 CP $(CLINT32_ELF)
	./$(MCU_VSOC_BIN) --payload tlerror EP $(TLERROR_ELF)
	./$(MCU_VSOC_BIN) --payload amo AP $(AMO_ELF)
	./$(MCU_VSOC_BIN) --payload hazard HP $(HAZARD_ELF)
	./$(MCU_VSOC_BIN) --payload pipeline_reissue RP $(PIPELINE_REISSUE_ELF)
	./$(MCU_VSOC_BIN) --payload bitmanip BP $(BITMANIP_ELF)
	./$(MCU_VSOC_BIN) --payload plic XP $(PLIC_ELF)
	./$(MCU_VSOC_BIN) --payload plic_s SIP $(PLIC_S_ELF)
	ION_UART_RX_CYCLE=160 ION_UART_RX_BYTE=0x5a ./$(MCU_VSOC_BIN) --payload uart_irq UP $(UART_IRQ_ELF)

regress-icache: $(ICACHE_VSOC_BIN) $(BASIC_ELF) $(TIMER_ELF) $(HAZARD_ELF)
	./$(ICACHE_VSOC_BIN) --payload basic "Hello, World!" $(BASIC_ELF)
	./$(ICACHE_VSOC_BIN) --payload timer S!!P $(TIMER_ELF)
	./$(ICACHE_VSOC_BIN) --payload hazard HP $(HAZARD_ELF)

regress-icache-basic: $(ICACHE_VSOC_BIN) $(BASIC_ELF)
	./$(ICACHE_VSOC_BIN) --payload basic "Hello, World!" $(BASIC_ELF)

regress-icache-hazard: $(ICACHE_VSOC_BIN) $(HAZARD_ELF)
	./$(ICACHE_VSOC_BIN) --payload hazard HP $(HAZARD_ELF)

gtkwave:
	gtkwave $(BUILD_DIR)/wave.fst

clean:
	@$(MAKE) -C difftest clean NEMU_HOME=$(NEMU_HOME) NOOP_HOME=$(NOOP_HOME)
	mill -i clean
	rm -rf $(PAYLOAD_BUILD_DIR)/*
# 	rm -rf $(SYSTEM_VERILOG_DIR)/*

ifneq ($(filter verilator verilator-jtag,$(MAKECMDGOALS)),)
$(RUN_ARGS):
	@:
endif
