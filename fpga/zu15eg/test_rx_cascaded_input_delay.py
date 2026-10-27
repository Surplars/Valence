"""Offline wiring contract only; not an HDL parser, simulation, or timing proof."""
import pathlib
import re
import unittest

SOURCE = pathlib.Path(__file__).with_name("native_rx_cascaded_input_delay.sv")


def validate(source):
    source = re.sub(r"//[^\n]*", "", source)
    blocks = re.findall(r'(IDELAYE3|ODELAYE3)\s*#\((.*?)\)\s*(master|slave)\s*\((.*?)\);', source, re.S)
    assert len(blocks) == 2, "exactly two primitives"
    expected = {
        "master": ("IDELAYE3", {"CASCADE": '"MASTER"', "DELAY_SRC": '"IDATAIN"'},
                   {"IDATAIN": "pad_data", "DATAIN": "1'b0", "DATAOUT": "delayed_data",
                    "CASC_IN": "1'b0", "CASC_OUT": "cascade", "CASC_RETURN": "returned"}),
        "slave": ("ODELAYE3", {"CASCADE": '"SLAVE_END"'},
                  {"ODATAIN": "1'b0", "DATAOUT": "returned", "CASC_IN": "cascade",
                   "CASC_OUT": "", "CASC_RETURN": "1'b0"}),
    }
    assert {b[2] for b in blocks} == set(expected)
    for primitive, parameters, name, ports in blocks:
        kind, params, pins = expected[name]
        params = dict(params, DELAY_FORMAT='"TIME"', DELAY_TYPE='"FIXED"',
                      DELAY_VALUE="STAGE_DELAY_PS", REFCLK_FREQUENCY="500.0",
                      SIM_DEVICE='"ULTRASCALE_PLUS"')
        pins = dict(pins, CLK="1'b0", CE="1'b0", INC="1'b0", LOAD="1'b0",
                    CNTVALUEIN="9'b0", CNTVALUEOUT="", RST="delay_reset", EN_VTC="1'b1")
        extract = lambda s: dict(re.findall(r'\.(\w+)\(\s*([^()]*)\s*\)', s))
        assert primitive == kind and extract(parameters) == params, name + " parameters"
        assert extract(ports) == pins, name + " ports"
    assert len(re.findall(r'IODELAY_GROUP\s*=\s*"VALENCE_RGMII"', source)) == 2
    assert re.search(r'parameter integer STAGE_DELAY_PS\s*=\s*-1', source)
    assert re.search(r'STAGE_DELAY_PS < 0 \|\| STAGE_DELAY_PS > 1100', source)
    assert "$fatal" in source
    assert "IDELAYCTRL" not in source


class Contract(unittest.TestCase):
    def test_candidate(self):
        validate(SOURCE.read_text())

    def test_reject_mutations(self):
        source = SOURCE.read_text()
        for before, after in [
            ('.CASC_RETURN(returned)', ".CASC_RETURN(1'b0)"),
            ('.CASC_IN(cascade)', ".CASC_IN(1'b0)"),
            ('.DATAOUT(delayed_data)', '.DATAOUT(returned)'),
            ('.DELAY_VALUE(STAGE_DELAY_PS)', '.DELAY_VALUE(1101)'),
            ('.EN_VTC(1\'b1)', '.EN_VTC(1\'b0)'),
            ('.RST(delay_reset)', '.RST(1\'b0)'),
            ('.REFCLK_FREQUENCY(500.0)', '.REFCLK_FREQUENCY(300.0)'),
            ('"FIXED"', '"VARIABLE"'), ('"TIME"', '"COUNT"'),
            ('"VALENCE_RGMII"', '"OTHER_GROUP"'),
            ('STAGE_DELAY_PS > 1100', 'STAGE_DELAY_PS > 1250'),
            ('STAGE_DELAY_PS = -1', 'STAGE_DELAY_PS = 650'),
        ]:
            with self.subTest(mutation=before):
                self.assertIn(before, source)
                with self.assertRaises(AssertionError):
                    validate(source.replace(before, after, 1))


if __name__ == "__main__":
    unittest.main()
