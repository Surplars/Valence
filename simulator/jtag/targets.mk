# Standalone entry points: make -f simulator/jtag/targets.mk jtag-test
# Existing main Makefile/SoC ABI is intentionally untouched.
MILL ?= mill
PYTHON ?= python3
.PHONY: jtag-test jtag-scala-test jtag-export jtag-native-test jtag-mutation-test jtag-constraints-test
jtag-test: jtag-scala-test jtag-export jtag-constraints-test
	$(PYTHON) simulator/jtag/run.py
	$(PYTHON) simulator/jtag/mutations.py
jtag-scala-test:
	$(MILL) -i IonSoC.test.testOnly debug.JtagDebugReservationSpec
jtag-export:
	$(MILL) -i IonSoC.test.runMain debug.JtagDebugReservationExport off build/jtag/off
	$(MILL) -i IonSoC.test.runMain debug.JtagDebugReservationExport stub build/jtag/stub
	$(MILL) -i IonSoC.test.runMain debug.JtagDebugReservationExport external build/jtag/external
	$(PYTHON) simulator/jtag/check_export.py build/jtag/off --mode off
	$(PYTHON) simulator/jtag/check_export.py build/jtag/stub --mode stub
	$(PYTHON) simulator/jtag/check_export.py build/jtag/external --mode external
jtag-native-test:
	$(PYTHON) simulator/jtag/run.py
jtag-mutation-test:
	$(PYTHON) simulator/jtag/mutations.py
jtag-constraints-test:
	tclsh simulator/jtag/test_constraints.tcl

# Deliberately separate source/one-clock acceptance from native TCK/primitive gates.
.PHONY: jtag-ram-source-test jtag-ram-native-test
jtag-ram-source-test:
	$(MILL) -i IonSoC.test.testOnly debug.JtagRamLoaderSpec debug.JtagDebugReservationSpec ooo.FpgaNextConfigSpec
	$(PYTHON) simulator/gsim/jtag_ram_loader.py
	$(PYTHON) fpga/firmware/check_jtag_download.py
	tclsh simulator/jtag/ram-loader-test.tcl
	tclsh simulator/jtag/ram-loader-bscan-test.tcl
	tclsh simulator/jtag/ram-loader-config-test.tcl
	tclsh simulator/jtag/test_chain_guard.tcl
	$(PYTHON) simulator/jtag/test_export_contract.py
	$(PYTHON) simulator/jtag/bscan_check.py
jtag-ram-native-test:
	$(PYTHON) simulator/jtag/run.py
	$(PYTHON) simulator/jtag/bscan_run.py
