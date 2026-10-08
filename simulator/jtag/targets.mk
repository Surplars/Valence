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
