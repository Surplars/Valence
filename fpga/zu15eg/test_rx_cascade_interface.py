"""Short syntax/interface/guard check; stubs implement NO primitive behavior."""
import pathlib
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="rx-cascade-interface-") as directory:
    binary = str(pathlib.Path(directory) / "interface.vvp")
    for value in (-1, 0, 200, 550, 1100, 1101):
        subprocess.run([
            "iverilog", "-g2012", "-Wall", "-s", "native_rx_cascaded_input_delay",
            f"-Pnative_rx_cascaded_input_delay.STAGE_DELAY_PS={value}",
            "-o", binary, str(HERE / "native_rx_cascaded_input_delay.sv"),
            str(HERE / "rx_cascade_interface_stubs.sv.stub"),
        ], check=True)
        result = subprocess.run(["vvp", binary], capture_output=True, text=True)
        invalid = value in (-1, 1101)
        assert (result.returncode != 0) == invalid, (value, result.stdout, result.stderr)
        if invalid:
            assert "RX cascade requires an explicit stage delay" in result.stdout
        print(f"stage {value}: interface compile PASS, guard {'reject' if invalid else 'accept'} PASS")
print("No functional, UNISIM, calibration or native timing claim.")
