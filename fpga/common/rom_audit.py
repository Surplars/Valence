#!/usr/bin/env python3
"""Prove a dumped dual-port 128-KiB ROM against bytes; fail on unknown mapping.

Input is a read-only Vivado primitive/net/INIT dump, never source RTL or a cell
count certificate. Supported shape: RAMB36E2 x1/x9/x36 TDP, synchronous read with
no BRAM output register; LUT/MUXF combinational selection and at most one FF
stage on address selection. Every logical bit must select one real physical
INIT bit, independent of its value. No physical bit may alias another address.
All 32768 words must be reachable through the exported boundary: either both
full-address ports, or complementary constant-bit slices (e.g. even/odd words).
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

# AMD UG573: Address Bus (RAMB36E2 TDP table), Block RAM Address Mapping,
# Content Initialization INIT_xx/INITP_xx. Width includes the separate parity bus.
# https://docs.amd.com/r/en-US/ug573-ultrascale-memory-resources/Address-Bus-ADDRARDADDR-and-ADDRBWRADDR
# https://docs.amd.com/r/en-US/ug573-ultrascale-memory-resources/Block-RAM-Address-Mapping
PACKING = {1: (0, 1, 0), 9: (3, 8, 1), 36: (5, 32, 4)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def integer(value):
    value = str(value)
    m = re.fullmatch(r"(?:\d+)'([hHbBdD])([0-9a-fA-F]+)", value)
    if m:
        return int(m[2], {'h': 16, 'b': 2, 'd': 10}[m[1].lower()])
    return int(value, 0) if value.startswith('0x') else int(value)


class Model:
    def __init__(self, document):
        self.ports = document['ports']
        self.constants = {k: int(v) for k, v in document['constants'].items()}
        self.cells = {c['name']: c for c in document['cells']}
        require(len(self.cells) == len(document['cells']), 'duplicate primitive name')
        require(all(v in (0, 1) for v in self.constants.values()), 'invalid net constant')
        self.drivers = {}
        self.rams = {}
        for c in self.cells.values():
            ref = c['ref']
            require(not c.get('inverted_pins', []), 'inverted primitive control requires review: ' + c['name'])
            for p, net in c['pins'].items():
                if net is None:
                    # Only explicitly disconnected outputs are accepted. They
                    # do not get a driver or a fabricated zero-valued net.
                    require(p in c['outputs'], 'disconnected primitive input: ' + c['name'] + '/' + p)
                    continue
                require(isinstance(net, str) and net, 'invalid primitive net: ' + c['name'] + '/' + p)
                if p in c['outputs']:
                    require(net not in self.drivers, 'multiple primitive drivers: ' + net)
                    self.drivers[net] = (c, p)
            if ref == 'RAMB36E2':
                prop = c['properties']
                for key in ('READ_WIDTH_A', 'READ_WIDTH_B'):
                    require(integer(prop[key]) in PACKING, 'unsupported ROM packing: ' + c['name'] + '/' + key)
                for side in 'AB':
                    require(integer(prop['WRITE_WIDTH_' + side]) == integer(prop['READ_WIDTH_' + side]),
                            'unsupported ROM write/read packing: ' + c['name'])
                    require(prop['CASCADE_ORDER_' + side] == 'NONE', 'unsupported ROM cascade: ' + c['name'])
                    for key in ('ENADDREN' + side, 'RDADDRCHANGE' + side):
                        require(str(prop[key]).upper() in ('FALSE', '0'), 'unsupported ROM address mode: ' + key)
                for key in ('DOA_REG', 'DOB_REG'):
                    require(integer(prop[key]) == 0, 'extra ROM read pipeline: ' + c['name'])
                for key in ('EN_ECC_READ', 'EN_ECC_WRITE', 'EN_ECC_PIPE'):
                    require(str(prop.get(key, '')).upper() in ('FALSE', '0'), 'ECC mode not proven disabled')
                def contents(prefix, count):
                    blocks = [integer(prop[f'{prefix}_{i:02X}']) for i in range(count)]
                    require(all(0 <= b < (1 << 256) for b in blocks), 'invalid ROM INIT block')
                    return sum(b << (i * 256) for i, b in enumerate(blocks))
                data = contents('INIT', 128)
                parity = contents('INITP', 16)
                self.rams[c['name']] = (data, parity)
        require(self.rams, 'no physical ROM RAMB36E2s')
        for p in ('clka', 'clkb', 'ena', 'enb'):
            require(p in self.ports, 'missing ROM boundary ' + p)
        for port in ('a', 'b'):
            for i in range(15):
                require(f'addr{port}[{i}]' in self.ports, 'missing 15-bit address')
            for i in range(32):
                require(f'dout{port}[{i}]' in self.ports, 'missing 32-bit data')
        require(all(isinstance(n, str) and n for n in self.ports.values()),
                'missing/disconnected ROM boundary net')

    def reachable(self, address, port):
        # Synthesis may expose A[0]=0 / B[0]=1 with shared upper address nets.
        # Do not override these physical constants to manufacture full ports.
        # Repeated address nets impose equality too; coverage below must still
        # account for every word through at least one real port.
        bindings = dict(self.constants)
        for p, value in [('ena', 1), ('enb', 1)] + [
                (f'addr{port}[{i}]', (address >> i) & 1) for i in range(15)]:
            n = self.ports[p]
            if n in bindings and bindings[n] != value:
                return False
            bindings[n] = value
        return True

    def read(self, address, port):
        # Opposite-port addresses are deliberately left unbound. Any dependency
        # on them fails even when both ports happen to return identical zeros.
        inputs = {}

        def bind(n, value):
            require(isinstance(n, str) and n, 'missing/disconnected ROM boundary net')
            require(n not in self.constants or self.constants[n] == value,
                    'constant contradicts ROM boundary input')
            require(n not in inputs or inputs[n] == value, 'aliased address/control boundary')
            inputs[n] = value

        for p in ('ena', 'enb'):
            bind(self.ports[p], 1)
        for i in range(15):
            bind(self.ports[f'addr{port}[{i}]'], (address >> i) & 1)
        cache, visiting = {}, set()

        def const(v):
            require(isinstance(v, int) and v in (0, 1), 'data-dependent ROM address/control')
            return v

        def pin(c, p, epoch):
            require(p in c['pins'], 'missing primitive pin ' + c['name'] + '/' + p)
            require(c['pins'][p] is not None, 'disconnected primitive pin ' + c['name'] + '/' + p)
            return net(c['pins'][p], epoch)

        def ram(c, p, epoch):
            require(epoch == 1, 'ROM feeds pre-edge logic/extra read pipeline')
            m = re.fullmatch(r'(DOUT[AB]DOUT|DOUTP[AB]DOUTP)\[(\d+)\]', p)
            require(m is not None, 'unsupported BRAM output: ' + p)
            side = 'A' if m[1] in ('DOUTADOUT', 'DOUTPADOUTP') else 'B'
            expected = 'a' if side == 'A' else 'b'
            shift, data_width, parity_width = PACKING[integer(c['properties']['READ_WIDTH_' + side])]
            is_parity = m[1].startswith('DOUTP')
            bit = int(m[2])
            require(bit < (parity_width if is_parity else data_width), 'invalid BRAM output bit for width')
            row_key = ('RAM_ROW', c['name'], side)
            if row_key not in cache:
                clock = 'CLKARDCLK' if side == 'A' else 'CLKBWRCLK'
                require(c['pins'][clock] == self.ports['clk' + expected], 'ROM clock mapping differs')
                for name, count in (('WEA', 4), ('WEBWE', 8)):
                    for we_bit in range(count):
                        require(const(pin(c, f'{name}[{we_bit}]', 0)) == 0, 'ROM write enable is not disabled')
                for name in ('RSTRAMARSTRAM', 'RSTRAMB', 'RSTREGARSTREG', 'RSTREGB', 'SLEEP'):
                    require(const(pin(c, name, 0)) == 0, 'ROM reset/sleep not inactive')
                en = 'ENARDEN' if side == 'A' else 'ENBWREN'
                require(const(pin(c, en, 0)) == 1, 'selected ROM bank not enabled')
                addrpin = 'ADDRARDADDR' if side == 'A' else 'ADDRBWRADDR'
                raw = sum(const(pin(c, f'{addrpin}[{i}]', 0)) << i for i in range(15))
                # Low bits are unused by this aspect ratio. Require real,
                # evaluable pins above, but do not mistake tied-high unused
                # bits for address bits. UG573 TDP table: x9 uses [14:3].
                row = raw >> shift
                cache[row_key] = row
            row = cache[row_key]
            # Canonical physical identity, independent of port aspect ratio:
            # one 32-data/4-parity-bit row. INITP is NOT interleaved into INIT.
            offset = row * (parity_width if is_parity else data_width) + bit
            return (c['name'], offset // (4 if is_parity else 32),
                    offset % (4 if is_parity else 32) + (32 if is_parity else 0))

        def net(n, epoch):
            require(isinstance(n, str) and n, 'missing/disconnected ROM boundary net')
            key = (n, epoch)
            if key in cache:
                return cache[key]
            if n in inputs:
                return inputs[n]
            if n in self.constants:
                return self.constants[n]
            require(key not in visiting, 'combinational/unsupported sequential loop: ' + n)
            require(n in self.drivers, 'unbound input or opposite-port address dependency: ' + n)
            visiting.add(key)
            c, output = self.drivers[n]
            ref, props = c['ref'], c['properties']
            if ref in ('GND', 'VCC'):
                value = int(ref == 'VCC')
            elif ref == 'RAMB36E2':
                value = ram(c, output, epoch)
            elif re.fullmatch(r'LUT[1-6]', ref):
                count = int(ref[-1]); init = integer(props['INIT'])
                args = []
                for i in range(count):
                    try:
                        args.append(pin(c, f'I{i}', epoch))
                    except ValueError as error:
                        # An unselected mux arm may have disabled RAM or an
                        # unrelated port. Carry poison until LUT reduction.
                        args.append(('UNPROVEN', str(error)))
                symbols = list(dict.fromkeys(v for v in args if not isinstance(v, int)))
                # Reduce LUT truth table with known address/control constants.
                # An output must remain a constant or exactly one RAM symbol.
                table = []
                for vector in range(1 << len(symbols)):
                    assignment = {s: (vector >> i) & 1 for i, s in enumerate(symbols)}
                    index = sum((v if isinstance(v, int) else assignment[v]) << i for i, v in enumerate(args))
                    table.append((init >> index) & 1)
                if len(set(table)) == 1:
                    value = table[0]
                else:
                    matches = [s for i, s in enumerate(symbols) if table == [(v >> i) & 1 for v in range(len(table))]]
                    require(len(matches) == 1, 'ROM output is modified/mixed data, not direct physical mapping')
                    value = matches[0]
            elif ref in ('MUXF7', 'MUXF8', 'MUXF9'):
                value = pin(c, 'I1' if const(pin(c, 'S', epoch)) else 'I0', epoch)
            elif ref in ('BUF',):
                value = pin(c, 'I', epoch)
            elif ref in ('FDRE', 'FDSE', 'FDCE', 'FDPE'):
                require(epoch == 1, 'more than one FF stage or previous-state dependency')
                control = {'FDRE': 'R', 'FDSE': 'S', 'FDCE': 'CLR', 'FDPE': 'PRE'}[ref]
                require(const(pin(c, control, 0)) == 0 and const(pin(c, 'CE', 0)) == 1,
                        'ROM selector reset/enable requires unknown prior state')
                require(c['pins']['C'] == self.ports['clk' + port], 'selector clock mismatch')
                value = pin(c, 'D', 0)
                require(isinstance(value, int), 'registered data adds a second ROM latency')
            else:
                raise ValueError('unsupported mapped ROM primitive: ' + ref + ' ' + c['name'])
            visiting.remove(key); cache[key] = value
            return value

        result = [net(self.ports[f'dout{port}[{i}]'], 1) for i in range(32)]
        require(all(isinstance(s, tuple) and len(s) == 3 and s[0] in self.rams for s in result), 'constant/nonphysical ROM output bit')
        return result

    def value(self, source):
        name, row, bit = source
        data, parity = self.rams[name]
        return ((data >> (row * 32 + bit)) if bit < 32 else (parity >> (row * 4 + bit - 32))) & 1


def audit(document, golden):
    require(len(golden) == 131072, 'ROM golden must be exactly 131072 bytes')
    model = Model(document)
    seen = set(); port_words = dict(a=0, b=0)
    for address in range(32768):
        mappings = []
        for port in ('a', 'b'):
            if model.reachable(address, port):
                mappings.append(model.read(address, port)); port_words[port] += 1
        require(mappings, f'ROM boundary has no accessible port at word {address}')
        a = mappings[0]
        require(all(a == b for b in mappings[1:]),
                f'port A/B physical address/data mapping differs at word {address}')
        require(len(set(a)) == 32 and not seen.intersection(a), f'physical bit alias at word {address}')
        seen.update(a)
        actual = sum(model.value(s) << i for i, s in enumerate(a))
        expected = int.from_bytes(golden[address*4:address*4+4], 'little')
        require(actual == expected, f'ROM INIT mismatch word={address} expected={expected:08x} actual={actual:08x}')
    return dict(status='PASS', bytes=131072, words=32768, physical_bits=len(seen),
                ram_primitives=len(model.rams), ports=['a', 'b'], port_words=port_words,
                rom_sha256=hashlib.sha256(golden).hexdigest())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--netlist', type=Path, required=True)
    p.add_argument('--rom', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    try:
        result = audit(json.loads(a.netlist.read_text()), a.rom.read_bytes())
    except (ValueError, KeyError, TypeError, OSError) as e:
        a.output.write_text(json.dumps(dict(status='BLOCKED', reason=str(e)), indent=2)+'\n')
        raise SystemExit('COMMON_ROM_BLOCKED: ' + str(e))
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print('COMMON_ROM_CONTENT_MAPPING_PASS')


if __name__ == '__main__':
    main()
