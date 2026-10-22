"""Synthetic netlist tests, never physical qualification or Vivado evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import rom_audit as audit


def fixture():
    ports = {'clka': 'clk', 'clkb': 'clk', 'ena': 'one', 'enb': 'one'}
    constants = {'zero': 0, 'one': 1}; cells = []
    for side in 'ab':
        for i in range(15):
            ports[f'addr{side}[{i}]'] = f'{side}{i}'
    for bank in range(32):
        props = dict(READ_WIDTH_A=36, READ_WIDTH_B=36, WRITE_WIDTH_A=36, WRITE_WIDTH_B=36,
                     DOA_REG=0, DOB_REG=0, EN_ECC_READ='FALSE', EN_ECC_WRITE='FALSE', EN_ECC_PIPE='FALSE',
                     CASCADE_ORDER_A='NONE', CASCADE_ORDER_B='NONE', ENADDRENA='FALSE', ENADDRENB='FALSE',
                     RDADDRCHANGEA='FALSE', RDADDRCHANGEB='FALSE')
        # Distinguishable bank/address, includes zeros and all bit positions.
        data = sum(((bank * 0x93af17 + row * 0x1020305) & 0xffffffff) << (row*32) for row in range(1024))
        props.update({f'INIT_{i:02X}': f"256'h{(data >> (i*256)) & ((1<<256)-1):064x}" for i in range(128)})
        props.update({f'INITP_{i:02X}': "256'h"+'0'*64 for i in range(16)})
        pins = dict(CLKARDCLK='clk', CLKBWRCLK='clk', ENARDEN='one', ENBWREN='one',
                    RSTRAMARSTRAM='zero', RSTRAMB='zero', RSTREGARSTREG='zero', RSTREGB='zero', SLEEP='zero')
        for prefix, width in (('WEA', 4), ('WEBWE', 8)):
            pins.update({f'{prefix}[{i}]': 'zero' for i in range(width)})
        for side, addr, out in (('a', 'ADDRARDADDR', 'DOUTADOUT'), ('b', 'ADDRBWRADDR', 'DOUTBDOUT')):
            pins.update({f'{addr}[{i}]': 'zero' if i<5 else f'{side}{i-5}' for i in range(15)})
            pins.update({f'{out}[{i}]': f'b{bank}{side}d{i}' for i in range(32)})
        cells.append(dict(name=f'ram{bank}', ref='RAMB36E2', properties=props, pins=pins,
                          outputs=[f'{out}[{i}]' for out in ('DOUTADOUT','DOUTBDOUT') for i in range(32)]))
    for side in 'ab':
        for bit in range(32):
            current = [f'b{bank}{side}d{bit}' for bank in range(32)]
            for level in range(5):
                next_level = []
                for j in range(len(current)//2):
                    name = f'm{side}_{bit}_{level}_{j}'; output = name+'out'
                    cells.append(dict(name=name, ref='MUXF7', properties={}, outputs=['O'],
                                      pins={'I0':current[j*2], 'I1':current[j*2+1], 'S':f'{side}{10+level}', 'O':output}))
                    next_level.append(output)
                current = next_level
            ports[f'dout{side}[{bit}]'] = current[0]
    return dict(ports=ports, constants=constants, cells=cells)


def mixed_fixture(striped=False):
    """Independent word image packed as five x1 columns and three x9 columns.

    Each x9 column has eight depth banks. All parity bits carry ordinary ROM
    data, so omitting INITP, reversing bits/bytes, or aliasing banks is visible.
    This is synthetic coverage, not a claim about any Vivado checkpoint.
    """
    words = [((a * 0x9e3779b1) ^ (a << 17) ^ (a >> 7) ^ 0xa5c31f07) & 0xffffffff
             for a in range(32768)]
    golden = b''.join(w.to_bytes(4, 'little') for w in words)
    old = fixture()
    ports = {p: n for p, n in old['ports'].items() if not p.startswith('dout')}
    cells = []
    for column in range(8):
        width = 1 if column < 5 else 9
        first_bit = column if width == 1 else 5 + 9 * (column - 5)
        for bank in range(1 if width == 1 else 8):
            c = copy.deepcopy(old['cells'][0]); c['name'] = f'c{column}b{bank}'
            p = c['properties']; pins = c['pins']; c['outputs'] = []
            for side in 'AB':
                p['READ_WIDTH_' + side] = p['WRITE_WIDTH_' + side] = width
            if width == 1:
                data = sum(((w >> first_bit) & 1) << a for a, w in enumerate(words))
                parity = 0
            else:
                selected = words[bank*4096:(bank+1)*4096]
                data = sum(((w >> first_bit) & 255) << (a*8) for a, w in enumerate(selected))
                parity = sum(((w >> (first_bit+8)) & 1) << a for a, w in enumerate(selected))
            for prefix, value, count in [('INIT', data, 128), ('INITP', parity, 16)]:
                p.update({f'{prefix}_{i:02X}': f"256'h{value >> (i*256) & ((1<<256)-1):064x}"
                          for i in range(count)})
            for side, addr, out, pout in [('a', 'ADDRARDADDR', 'DOUTADOUT', 'DOUTPADOUTP'),
                                         ('b', 'ADDRBWRADDR', 'DOUTBDOUT', 'DOUTPBDOUTP')]:
                shift = 0 if width == 1 else 3
                pins.update({f'{addr}[{i}]': 'one' if i < shift else f'{side}{i-shift}'
                             for i in range(15)})
                for prefix, count in [(out, 32), (pout, 4)]:
                    for bit in range(count):
                        pn = f'{prefix}[{bit}]'; c['outputs'].append(pn)
                        active = bit < (1 if width == 1 else 8) if prefix == out else width == 9 and bit == 0
                        pins[pn] = f'{c["name"]}{side}_{prefix}{bit}' if active else None
                pins['CASDOUTA[31]'] = pins['CASDOUTB[31]'] = None
                for bit in range(width):
                    source = pins[f'{pout}[0]' if bit == 8 else f'{out}[{bit}]']
                    if width == 1:
                        ports[f'dout{side}[{first_bit}]'] = source
            c['outputs'] += ['CASDOUTA[31]', 'CASDOUTB[31]']
            cells.append(c)
        if width == 9:
            for side, out, pout in [('a', 'DOUTADOUT', 'DOUTPADOUTP'), ('b', 'DOUTBDOUT', 'DOUTPBDOUTP')]:
                for bit in range(9):
                    current = [f'c{column}b{bank}{side}_{pout if bit == 8 else out}{0 if bit == 8 else bit}'
                               for bank in range(8)]
                    for level in range(3):
                        following = []
                        for i in range(len(current)//2):
                            name = f'm{column}_{side}_{bit}_{level}_{i}'
                            cells.append(dict(name=name, ref='MUXF7', properties={}, outputs=['O'],
                                              pins=dict(I0=current[2*i], I1=current[2*i+1],
                                                        S=f'{side}{12+level}', O=name)))
                            following.append(name)
                        current = following
                    ports[f'dout{side}[{first_bit+bit}]'] = current[0]
    if striped:
        # Native aligned 64-bit read: A supplies even words, B odd words.
        # Both use the same 14 upper input nets, not two independent buses.
        replacements = {'a0': 'zero', 'b0': 'one'}
        replacements.update({f'{side}{i}': f'shared{i}' for side in 'ab' for i in range(1, 15)})
        ports = {p: replacements.get(n, n) for p, n in ports.items()}
        for c in cells:
            c['pins'] = {p: replacements.get(n, n) for p, n in c['pins'].items()}
    return dict(ports=ports, constants=old['constants'], cells=cells), golden


class Mapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = fixture()

    def test_physical_mapping_both_ports(self):
        model = audit.Model(self.document)
        for address in (0, 1, 1023, 1024, 31744, 32767):
            a = model.read(address, 'a'); b = model.read(address, 'b')
            self.assertEqual(a,b)
            self.assertEqual(a, [(f'ram{address//1024}', address%1024, i) for i in range(32)])
            value = sum(model.value(v)<<i for i,v in enumerate(a))
            self.assertEqual(value, (address//1024*0x93af17 + address%1024*0x1020305)&0xffffffff)

    def test_opposite_port_dependency_fails(self):
        d=copy.deepcopy(self.document)
        next(c for c in d['cells'] if c['name']=='ram0')['pins']['ADDRARDADDR[5]']='b0'
        with self.assertRaisesRegex(ValueError,'opposite-port'):
            audit.Model(d).read(0,'a')

    def test_extra_output_register_fails(self):
        d=copy.deepcopy(self.document); d['cells'][0]['properties']['DOA_REG']=1
        with self.assertRaisesRegex(ValueError,'extra ROM'):
            audit.Model(d)

    def test_write_enable_fails(self):
        d=copy.deepcopy(self.document); d['cells'][0]['pins']['WEA[0]']='one'
        with self.assertRaisesRegex(ValueError,'write enable'):
            audit.Model(d).read(0,'a')

    def test_unknown_logic_fails(self):
        d=copy.deepcopy(self.document); next(c for c in d['cells'] if c['name']=='ma_0_4_0')['ref']='UNKNOWN'
        with self.assertRaisesRegex(ValueError,'unsupported mapped'):
            audit.Model(d).read(0,'a')

    def test_short_golden_fails(self):
        with self.assertRaisesRegex(ValueError,'131072'):
            audit.audit(self.document,b'\0'*4096)


class MixedMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document, cls.golden = mixed_fixture()

    def test_full_content_mapping_both_ports(self):
        result = audit.audit(self.document, self.golden)
        self.assertEqual((result['status'], result['bytes'], result['physical_bits'], result['ram_primitives']),
                         ('PASS', 131072, 1048576, 29))
        self.assertEqual(result['port_words'], dict(a=32768, b=32768))

    def test_full_content_mapping_striped_ports(self):
        d, golden = mixed_fixture(striped=True)
        result = audit.audit(d, golden)
        self.assertEqual((result['status'], result['physical_bits']), ('PASS', 1048576))
        self.assertEqual(result['port_words'], dict(a=16384, b=16384))
        # Tying both ports even must not silently certify just half the image.
        d['ports']['addrb[0]'] = 'zero'
        for c in d['cells']:
            if c['ref'] == 'RAMB36E2':
                bit = 0 if c['properties']['READ_WIDTH_B'] == 1 else 3
                c['pins'][f'ADDRBWRADDR[{bit}]'] = 'zero'
        with self.assertRaisesRegex(ValueError, 'no accessible port at word 1'):
            audit.audit(d, golden)

    def test_width1_and9_init_boundaries(self):
        model = audit.Model(self.document)
        for a in (0, 1, 3, 4, 31, 32, 255, 256, 4095, 4096, 32767):
            source = model.read(a, 'a')
            self.assertEqual(source, model.read(a, 'b'))
            self.assertEqual(source[0], ('c0b0', a//32, a%32))
            self.assertEqual(source[5], (f'c5b{a//4096}', (a%4096)//4, (a%4)*8))
            self.assertEqual(source[13], (f'c5b{a//4096}', (a%4096)//4, 32+a%4))
            value = sum(model.value(s) << i for i, s in enumerate(source))
            self.assertEqual(value, int.from_bytes(self.golden[a*4:a*4+4], 'little'))

    def test_bad_init_and_initp_fail(self):
        for name, prefix in [('c0b0', 'INIT'), ('c5b0', 'INIT'), ('c5b0', 'INITP')]:
            with self.subTest(name=name, prefix=prefix):
                d = copy.deepcopy(self.document)
                p = next(c for c in d['cells'] if c['name'] == name)['properties']
                p[prefix+'_00'] = hex(audit.integer(p[prefix+'_00']) ^ 1)
                with self.assertRaisesRegex(ValueError, 'INIT mismatch word=0'):
                    audit.audit(d, self.golden)

    def test_address_swap_and_alias_fail(self):
        for alias in (False, True):
            d = copy.deepcopy(self.document)
            c = d['cells'][0]
            for addr, side in [('ADDRARDADDR', 'a'), ('ADDRBWRADDR', 'b')]:
                c['pins'][f'{addr}[0]'] = 'zero' if alias else side+'1'
                if not alias:
                    c['pins'][f'{addr}[1]'] = side+'0'
            with self.assertRaisesRegex(ValueError, 'INIT mismatch|physical bit alias'):
                audit.audit(d, self.golden)

    def test_bit_order_and_wrong_golden_fail(self):
        d = copy.deepcopy(self.document)
        for side in 'ab':
            p, q = f'dout{side}[0]', f'dout{side}[5]'
            d['ports'][p], d['ports'][q] = d['ports'][q], d['ports'][p]
        with self.assertRaisesRegex(ValueError, 'INIT mismatch'):
            audit.audit(d, self.golden)
        with self.assertRaisesRegex(ValueError, 'INIT mismatch'):
            audit.audit(self.document, bytes([self.golden[0] ^ 1]) + self.golden[1:])

    def test_unsupported_modes_fail(self):
        for key, value in [('READ_WIDTH_A', 72), ('WRITE_WIDTH_A', 36), ('CASCADE_ORDER_A', 'LAST'),
                           ('ENADDRENB', 'TRUE'), ('RDADDRCHANGEA', 'TRUE'), ('EN_ECC_PIPE', 'TRUE')]:
            with self.subTest(key=key):
                d = copy.deepcopy(self.document); d['cells'][0]['properties'][key] = value
                with self.assertRaises(ValueError):
                    audit.Model(d)

    def test_missing_or_null_live_pin_fail(self):
        for pin in ('ADDRARDADDR[0]', 'WEA[0]', 'SLEEP'):
            for null in (False, True):
                with self.subTest(pin=pin, null=null):
                    d = copy.deepcopy(self.document)
                    if null:
                        d['cells'][0]['pins'][pin] = None
                    else:
                        del d['cells'][0]['pins'][pin]
                    with self.assertRaisesRegex(ValueError, 'disconnected|missing primitive pin'):
                        audit.Model(d).read(0, 'a')

    def test_disconnected_output_is_not_zero_or_driver(self):
        d = copy.deepcopy(self.document)
        d['ports']['douta[0]'] = None
        with self.assertRaisesRegex(ValueError, 'disconnected ROM boundary'):
            audit.Model(d).read(0, 'a')
        d['ports']['douta[0]'] = 'missing-output-net'
        with self.assertRaisesRegex(ValueError, 'unbound input'):
            audit.Model(d).read(0, 'a')

    def test_boundary_input_cannot_override_constant(self):
        for port, address in [('ena', 0), ('addra[0]', 1)]:
            d = copy.deepcopy(self.document); d['ports'][port] = 'zero'
            with self.assertRaisesRegex(ValueError, 'constant contradicts'):
                audit.Model(d).read(address, 'a')

    def test_invalid_width_output_fails(self):
        for pin in ('DOUTADOUT[1]', 'DOUTPADOUTP[0]'):
            d = copy.deepcopy(self.document)
            d['cells'][0]['pins'][pin] = 'invalid-width-output'
            d['ports']['douta[0]'] = 'invalid-width-output'
            with self.assertRaisesRegex(ValueError, 'invalid BRAM output bit'):
                audit.Model(d).read(0, 'a')

    def test_missing_property_cli_is_blocked(self):
        d = copy.deepcopy(self.document)
        del d['cells'][0]['properties']['CASCADE_ORDER_A']
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            netlist, rom, output = [directory / name for name in ('net.json', 'rom.bin', 'out.json')]
            netlist.write_text(json.dumps(d)); rom.write_bytes(self.golden)
            run = subprocess.run([sys.executable, '-E', str(Path(audit.__file__)), '--netlist', str(netlist),
                                  '--rom', str(rom), '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn('Traceback', run.stderr)
            self.assertEqual(json.loads(output.read_text())['status'], 'BLOCKED')

if __name__=='__main__': unittest.main()
