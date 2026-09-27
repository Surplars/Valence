.PHONY: gsim-setup gsim-smoke gsim-backend-test gsim-backend-recovery4-test gsim-backend-recovery8-test gsim-backend-recovery16-test gsim-integer-test gsim-core-test gsim-test

# Downloads only the pinned toolchain source, never the upstream CPU/example submodules.
gsim-setup:
	python3 simulator/gsim/run.py setup

gsim-smoke:
	python3 simulator/gsim/run.py smoke

gsim-backend-test:
	python3 simulator/gsim/run.py backend

gsim-backend-recovery4-test:
	python3 simulator/gsim/run.py backend-recovery4

gsim-backend-recovery8-test:
	python3 simulator/gsim/run.py backend-recovery8

gsim-backend-recovery16-test:
	python3 simulator/gsim/run.py backend-recovery16

.PHONY: gsim-backend-move-alias-test
gsim-backend-move-alias-test:
	python3 simulator/gsim/run.py backend-move-alias

gsim-integer-test:
	python3 simulator/gsim/run.py integer

gsim-core-test:
	python3 simulator/gsim/run.py core

.PHONY: gsim-core-move-alias-test gsim-core-word-bypass-test gsim-core-indirect-test
gsim-core-move-alias-test:
	python3 simulator/gsim/run.py core-move-alias

gsim-core-word-bypass-test:
	python3 simulator/gsim/run.py core-word-bypass

gsim-core-indirect-test:
	python3 simulator/gsim/run.py core-indirect

gsim-test:
	python3 simulator/gsim/run.py test

.PHONY: gsim-ipc
gsim-ipc:
	python3 simulator/gsim/run.py ipc

.PHONY: coremark-setup gsim-coremark gsim-coremark-cache gsim-coremark-coherent gsim-coremark-delay12 gsim-coremark-cache-delay12
coremark-setup:
	python3 simulator/gsim/run.py coremark-setup

gsim-coremark:
	python3 simulator/gsim/run.py coremark

# Matched bare-platform profiles for 2/4-issue cycle comparisons.
.PHONY: gsim-coremark-2issue gsim-coremark-4issue gsim-coremark-4issue-recovery16 gsim-coremark-4issue-load-bypass gsim-coremark-4issue-move-alias gsim-coremark-4issue-word-bypass gsim-coremark-4issue-indirect
COREMARK_FAST_OPTIONS := --flow-tilelink-response --fast-buffered-store-retire --fast-head-load-retire --recovery-width 8
gsim-coremark-2issue:
	python3 simulator/gsim/run.py coremark-tune --issue-width 2 $(COREMARK_FAST_OPTIONS)

gsim-coremark-4issue:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 $(COREMARK_FAST_OPTIONS)

gsim-coremark-4issue-recovery16:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 --flow-tilelink-response \
		--fast-buffered-store-retire --fast-head-load-retire --recovery-width 16

gsim-coremark-4issue-load-bypass:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 --flow-tilelink-response \
		--fast-buffered-store-retire --fast-head-load-retire --recovery-width 16 \
		--load-completion-bypass

gsim-coremark-4issue-move-alias:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 --flow-tilelink-response \
		--fast-buffered-store-retire --fast-head-load-retire --recovery-width 16 \
		--load-completion-bypass --move-alias

gsim-coremark-4issue-word-bypass:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 --flow-tilelink-response \
		--fast-buffered-store-retire --fast-head-load-retire --recovery-width 16 \
		--load-completion-bypass --word-bypass

gsim-coremark-4issue-indirect:
	python3 simulator/gsim/run.py coremark-tune --issue-width 4 --flow-tilelink-response \
		--fast-buffered-store-retire --fast-head-load-retire --recovery-width 16 \
		--load-completion-bypass --word-bypass --indirect-entries 16

.PHONY: gsim-issue-peak-4issue
gsim-issue-peak-4issue:
	python3 simulator/gsim/run.py issue-peak-4

gsim-coremark-cache:
	python3 simulator/gsim/run.py coremark-cache

gsim-coremark-coherent:
	python3 simulator/gsim/run.py coremark-coherent

.PHONY: gsim-coremark-coherent-delay12
gsim-coremark-coherent-delay12:
	python3 simulator/gsim/run.py coremark-coherent-delay12

.PHONY: gsim-tilelink-coherent-platform-test
gsim-tilelink-coherent-platform-test:
	python3 simulator/gsim/run.py tilelink-coherent-platform

.PHONY: gsim-tilelink-dual-split-coherent-test
gsim-tilelink-dual-split-coherent-test:
	python3 simulator/gsim/run.py tilelink-dual-split-coherent

.PHONY: gsim-tilelink-two-hart-coherent-test
gsim-tilelink-two-hart-coherent-test:
	python3 simulator/gsim/run.py tilelink-two-hart-coherent

.PHONY: gsim-tilelink-coherent-evict-test
gsim-tilelink-coherent-evict-test:
	python3 simulator/gsim/run.py tilelink-coherent-evict

.PHONY: gsim-tilelink-coherent-fencei-test
gsim-tilelink-coherent-fencei-test:
	python3 simulator/gsim/run.py tilelink-coherent-fencei

.PHONY: coherent-platform-rtl
coherent-platform-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.CoherentPlatformRtlMain build/ip/coherent-platform "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

gsim-coremark-delay12:
	python3 simulator/gsim/run.py coremark-delay12

gsim-coremark-cache-delay12:
	python3 simulator/gsim/run.py coremark-cache-delay12

.PHONY: gsim-core-memory8-test
gsim-core-memory8-test:
	python3 simulator/gsim/run.py core-memory8

.PHONY: gsim-core-fast-store-test
gsim-core-fast-store-test:
	python3 simulator/gsim/run.py core-fast-store

.PHONY: gsim-core-fast-memory-test
gsim-core-fast-memory-test:
	python3 simulator/gsim/run.py core-fast-memory

.PHONY: gsim-machine-platform-memory8-test
gsim-machine-platform-memory8-test:
	python3 simulator/gsim/run.py machine-platform-memory8

.PHONY: gsim-machine-platform-latency-test
gsim-machine-platform-latency-test:
	python3 simulator/gsim/run.py machine-platform-latency

.PHONY: gsim-tilelink-dual-latency-test
gsim-tilelink-dual-latency-test:
	python3 simulator/gsim/run.py tilelink-dual-latency

.PHONY: gsim-tilelink-burst-ram-test
gsim-tilelink-burst-ram-test:
	python3 simulator/gsim/run.py tilelink-burst-ram

.PHONY: gsim-tilelink-line-fill-test
gsim-tilelink-line-fill-test:
	python3 simulator/gsim/run.py tilelink-line-fill

.PHONY: tilelink-line-fill-rtl
tilelink-line-fill-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkLineFillRtlMain build/ip/tilelink-line-fill

.PHONY: gsim-tilelink-line-write-test tilelink-line-write-rtl
gsim-tilelink-line-write-test:
	python3 simulator/gsim/run.py tilelink-line-write

tilelink-line-write-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkLineWriteRtlMain build/ip/tilelink-line-write

.PHONY: tilelink-line-transfer-rtl
tilelink-line-transfer-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkLineTransferRtlMain build/ip/tilelink-line-transfer

.PHONY: gsim-tilelink-line-probe-test tilelink-line-probe-rtl
gsim-tilelink-line-probe-test:
	python3 simulator/gsim/run.py tilelink-line-probe

tilelink-line-probe-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkLineProbeRtlMain build/ip/tilelink-line-probe

.PHONY: gsim-tilelink-line-acquire-test tilelink-line-acquire-rtl
gsim-tilelink-line-acquire-test:
	python3 simulator/gsim/run.py tilelink-line-acquire

tilelink-line-acquire-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkLineAcquireRtlMain build/ip/tilelink-line-acquire

.PHONY: gsim-delayed-ram-test
gsim-delayed-ram-test:
	python3 simulator/gsim/run.py delayed-ram

.PHONY: gsim-axi-bridge-test
gsim-axi-bridge-test:
	python3 simulator/gsim/run.py axi-bridge

.PHONY: gsim-tilelink-axi4-bridge-test
gsim-tilelink-axi4-bridge-test:
	python3 simulator/gsim/run.py tilelink-axi4-bridge

.PHONY: gsim-tilelink-bridge-test
gsim-tilelink-bridge-test:
	python3 simulator/gsim/run.py tilelink-bridge

.PHONY: gsim-tilelink-bridge-flow-test
gsim-tilelink-bridge-flow-test:
	python3 simulator/gsim/run.py tilelink-bridge-flow

.PHONY: gsim-tilelink-platform-test
gsim-tilelink-platform-test:
	python3 simulator/gsim/run.py tilelink-platform

.PHONY: gsim-tilelink-platform-flow-test
gsim-tilelink-platform-flow-test:
	python3 simulator/gsim/run.py tilelink-platform-flow

.PHONY: gsim-tilelink-split-platform-test
gsim-tilelink-split-platform-test:
	python3 simulator/gsim/run.py tilelink-split-platform

.PHONY: gsim-tilelink-dual-platform-test
gsim-tilelink-dual-platform-test:
	python3 simulator/gsim/run.py tilelink-dual-platform

.PHONY: gsim-tilelink-dual-split-platform-test
gsim-tilelink-dual-split-platform-test:
	python3 simulator/gsim/run.py tilelink-dual-split-platform

.PHONY: gsim-tilelink-router-test
gsim-tilelink-router-test:
	python3 simulator/gsim/run.py tilelink-router

.PHONY: gsim-tilelink-arbiter-test
gsim-tilelink-arbiter-test:
	python3 simulator/gsim/run.py tilelink-arbiter

.PHONY: gsim-tilelink-fetch-test
gsim-tilelink-fetch-test:
	python3 simulator/gsim/run.py tilelink-fetch

.PHONY: gsim-tilelink-crossbar-test
gsim-tilelink-crossbar-test:
	python3 simulator/gsim/run.py tilelink-crossbar

.PHONY: tilelink-fetch-rtl
tilelink-fetch-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.InstructionTileLinkBridgeRtlMain build/ip/tilelink-fetch

.PHONY: tilelink-rom-adapter-rtl
tilelink-rom-adapter-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkInstructionRomAdapterRtlMain build/ip/tilelink-rom-adapter

.PHONY: tilelink-crossbar-rtl
tilelink-crossbar-rtl:
	$(MILL) -i IonSoC.test.runMain ip.TileLinkCrossbarRtlMain build/ip/tilelink-crossbar

.PHONY: tilelink-arbiter-rtl
tilelink-arbiter-rtl:
	$(MILL) -i IonSoC.test.runMain ip.TileLinkArbiterRtlMain build/ip/tilelink-arbiter

.PHONY: tilelink-router-rtl
tilelink-router-rtl:
	$(MILL) -i IonSoC.test.runMain ip.TileLinkRouterRtlMain build/ip/tilelink-router

.PHONY: tilelink-machine-platform-rtl
tilelink-machine-platform-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkMachinePlatformRtlMain build/ip/tilelink-machine-platform "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

.PHONY: tilelink-split-platform-rtl
tilelink-split-platform-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.SplitTileLinkMachinePlatformRtlMain build/ip/tilelink-split-platform "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

.PHONY: tilelink-bridge-rtl
tilelink-bridge-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.OrderedTileLinkBridgeRtlMain build/ip/tilelink-bridge

.PHONY: axi-bridge-rtl
axi-bridge-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.OrderedAxi4BridgeRtlMain build/ip/axi-bridge

.PHONY: tilelink-axi4-bridge-rtl
tilelink-axi4-bridge-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkAxi4BridgeRtlMain build/ip/tilelink-axi4-bridge

.PHONY: tilelink-axi4-bridge32-rtl
tilelink-axi4-bridge32-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.TileLinkAxi4BridgeRtlMain build/ip/tilelink-axi4-bridge32 32

.PHONY: axi-bridge32-rtl
axi-bridge32-rtl:
	$(MILL) -i IonSoC.test.runMain ooo.OrderedAxi4BridgeRtlMain build/ip/axi-bridge32 32

.PHONY: gsim-predictor-test
gsim-predictor-test:
	python3 simulator/gsim/run.py predictor

.PHONY: gsim-store-buffer-test
gsim-store-buffer-test:
	python3 simulator/gsim/run.py store-buffer

.PHONY: gsim-fpga-fetch-test
gsim-fpga-fetch-test:
	python3 simulator/gsim/run.py fpga-fetch

.PHONY: gsim-instruction-cache-test
gsim-instruction-cache-test:
	python3 simulator/gsim/run.py instruction-cache

.PHONY: gsim-instruction-line-cache-test
gsim-instruction-line-cache-test:
	python3 simulator/gsim/run.py instruction-line-cache

.PHONY: gsim-instruction-prefetch-test
gsim-instruction-prefetch-test:
	python3 simulator/gsim/run.py instruction-line-cache --instruction-prefetch

.PHONY: gsim-instruction-ipc
INSTRUCTION_CACHE_LINES ?= 32
FRONTEND_CACHE_SETS ?= $(if $(filter 4,$(ISSUE_WIDTH)),128,64)
INSTRUCTION_IPC_OPTIONS ?=
gsim-instruction-ipc:
	python3 simulator/gsim/run.py instruction-ipc --issue-width $(ISSUE_WIDTH) \
		--instruction-cache-lines $(INSTRUCTION_CACHE_LINES) \
		--frontend-cache-sets $(FRONTEND_CACHE_SETS) $(INSTRUCTION_IPC_OPTIONS)

.PHONY: gsim-vm-instruction-wide-test
gsim-vm-instruction-wide-test:
	python3 simulator/gsim/run.py vm-instruction-wide

.PHONY: gsim-aia-supervisor-uart-test
gsim-aia-supervisor-uart-test:
	python3 simulator/gsim/run.py aia-supervisor-uart

.PHONY: gsim-machine-aia-s-uart-test
gsim-machine-aia-s-uart-test:
	python3 simulator/gsim/run.py machine-aia-s-uart

.PHONY: gsim-platform-test
gsim-platform-test:
	python3 simulator/gsim/run.py platform

.PHONY: gsim-muldiv-test
gsim-muldiv-test:
	python3 simulator/gsim/run.py muldiv

.PHONY: gsim-pipelined-mul-test
gsim-pipelined-mul-test:
	python3 simulator/gsim/run.py pipelined-mul

.PHONY: gsim-imsic-test imsic-rtl
gsim-imsic-test:
	python3 simulator/gsim/run.py imsic

imsic-rtl:
	mill -i IonSoC.test.runMain ip.ImsicRtlMain build/ip/imsic

.PHONY: gsim-machine-test machine-core-rtl
gsim-machine-test:
	python3 simulator/gsim/run.py machine

machine-core-rtl:
	mill -i IonSoC.test.runMain ooo.MachineCoreRtlMain build/ip/machine-core

.PHONY: gsim-aplic-test aplic-rtl
gsim-aplic-test:
	python3 simulator/gsim/run.py aplic

aplic-rtl:
	mill -i IonSoC.test.runMain ip.AplicRtlMain build/ip/aplic

.PHONY: gsim-wired-machine-test wired-machine-rtl
gsim-wired-machine-test:
	python3 simulator/gsim/run.py wired-machine

wired-machine-rtl:
	mill -i IonSoC.test.runMain ooo.WiredMachineCoreRtlMain build/ip/wired-machine

.PHONY: gsim-router-test gsim-mapped-machine-test mapped-machine-rtl
gsim-router-test:
	python3 simulator/gsim/run.py router

gsim-mapped-machine-test:
	python3 simulator/gsim/run.py mapped-machine

mapped-machine-rtl:
	mill -i IonSoC.test.runMain ooo.MappedMachineCoreRtlMain build/ip/mapped-machine

.PHONY: machine-boot gsim-machine-platform-test gsim-sstc-platform-test machine-platform-rtl
machine-boot:
	python3 simulator/gsim/run.py machine-boot
gsim-machine-platform-test:
	python3 simulator/gsim/run.py machine-platform
gsim-sstc-platform-test:
	python3 simulator/gsim/run.py sstc-platform
.PHONY: gsim-privilege-uart-platform-test
gsim-privilege-uart-platform-test:
	python3 simulator/gsim/run.py privilege-uart-platform
.PHONY: gsim-pmp-test
gsim-pmp-test:
	python3 simulator/gsim/run.py pmp

.PHONY: gsim-pmp-fetch-platform-test
gsim-pmp-fetch-platform-test:
	python3 simulator/gsim/run.py pmp-fetch-platform
.PHONY: gsim-sv-walker-test
gsim-sv-walker-test:
	python3 simulator/gsim/run.py sv-walker
.PHONY: gsim-soc-translation-test
gsim-soc-translation-test:
	python3 simulator/gsim/run.py soc-translation
.PHONY: gsim-vm-data-platform-test
gsim-vm-data-platform-test:
	python3 simulator/gsim/run.py vm-data-platform

.PHONY: gsim-vm-data-coherent-platform-test
gsim-vm-data-coherent-platform-test:
	python3 simulator/gsim/run.py vm-data-coherent-platform

.PHONY: gsim-vm-instruction-platform-test
gsim-vm-instruction-platform-test:
	python3 simulator/gsim/run.py vm-instruction-platform

.PHONY: gsim-vm-instruction-coherent-platform-test
gsim-vm-instruction-coherent-platform-test:
	python3 simulator/gsim/run.py vm-instruction-coherent-platform
machine-platform-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.MachinePlatformRtlMain build/ip/machine-platform "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

.PHONY: machine-platform-memory8-rtl
machine-platform-memory8-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.Memory8MachinePlatformRtlMain build/ip/machine-platform-memory8 "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

.PHONY: gsim-uart-test
gsim-uart-test:
	python3 simulator/gsim/run.py uart

.PHONY: gsim-dma-test gsim-shared-data-test
gsim-dma-test:
	python3 simulator/gsim/run.py dma
gsim-shared-data-test:
	python3 simulator/gsim/run.py shared-data

.PHONY: dma-rtl
dma-rtl:
	$(MILL) -i IonSoC.test.runMain ip.DmaRtlMain build/ip/dma

.PHONY: gsim-timer-test timer-rtl
gsim-timer-test:
	python3 simulator/gsim/run.py timer
timer-rtl:
	$(MILL) -i IonSoC.test.runMain ip.TimerRtlMain build/ip/timer

.PHONY: gsim-atomic-test atomic-rtl
gsim-atomic-test:
	python3 simulator/gsim/run.py atomic
.PHONY: gsim-atomic-memory8-test
gsim-atomic-memory8-test:
	python3 simulator/gsim/run.py atomic-memory8
.PHONY: gsim-atomic8-platform-test
gsim-atomic8-platform-test:
	python3 simulator/gsim/run.py atomic8-platform
atomic-rtl:
	$(MILL) -i IonSoC.test.runMain ip.AtomicRtlMain build/ip/atomic

.PHONY: gsim-atomic-core-test
gsim-atomic-core-test:
	python3 simulator/gsim/run.py atomic-core

.PHONY: gsim-cache-test
gsim-cache-test:
	python3 simulator/gsim/run.py cache

.PHONY: gsim-cache-core-test gsim-cache-platform-test
gsim-cache-core-test:
	python3 simulator/gsim/run.py cache-core
gsim-cache-platform-test:
	python3 simulator/gsim/run.py cache-platform

.PHONY: cached-platform-rtl
cached-platform-rtl: machine-boot
	$(MILL) -i IonSoC.test.runMain ooo.CachedMachinePlatformRtlMain build/ip/cached-platform "$(CURDIR)/build/gsim/machine-boot-bank0.hex" "$(CURDIR)/build/gsim/machine-boot-bank1.hex"

.PHONY: gsim-opensbi-setup gsim-opensbi-test gsim-opensbi-console
gsim-opensbi-setup:
	python3 simulator/gsim/run.py opensbi-setup

gsim-opensbi-test:
	python3 simulator/gsim/run.py opensbi-platform

gsim-opensbi-console:
	python3 simulator/gsim/run.py opensbi-console

.PHONY: gsim-linux-setup gsim-linux-test gsim-linux-console gsim-linux-profile
ISSUE_WIDTH ?= 2
LINUX_CACHE_MODE ?= direct
LINUX_CACHE_LINES ?= 128
LINUX_PROFILE_CYCLES ?= 10000000
gsim-linux-setup:
	python3 simulator/gsim/linux_boot.py setup

gsim-linux-test:
	python3 simulator/gsim/linux_boot.py test --issue-width $(ISSUE_WIDTH) --cache-mode $(LINUX_CACHE_MODE) --cache-lines $(LINUX_CACHE_LINES)

gsim-linux-console:
	python3 simulator/gsim/linux_boot.py console --issue-width $(ISSUE_WIDTH) --cache-mode $(LINUX_CACHE_MODE) --cache-lines $(LINUX_CACHE_LINES)

gsim-linux-profile:
	python3 simulator/gsim/linux_boot.py profile --issue-width $(ISSUE_WIDTH) --cache-mode $(LINUX_CACHE_MODE) --cache-lines $(LINUX_CACHE_LINES) --profile-cycles $(LINUX_PROFILE_CYCLES)
