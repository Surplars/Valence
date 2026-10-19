"""Synthetic netlist tests, never physical qualification or Vivado evidence."""
import copy
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
                     DOA_REG=0, DOB_REG=0, EN_ECC_READ='FALSE', EN_ECC_WRITE='FALSE')
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

if __name__=='__main__': unittest.main()
