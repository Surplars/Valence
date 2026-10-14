#!/usr/bin/env python3
"""Source-only RV64 image and frozen B1 integration scenarios; never runs a DUT."""
import argparse
import hashlib
import json
from pathlib import Path

BASE = 0x80200000
CTRL = 0x80600000
DATA = 0x80400000
ALT = 0x80500000
ROOT_A = 0x80300000
ROOT_B = 0x80308000
MASK = (1 << 64) - 1
PHASES = (0, 1, 2, 3)
BOUNDS = {'cycles_per_reset': 30000, 'process_timeout_seconds': 120}


def signed(value, width):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def i_type(op, f3, rd, rs1, imm):
    assert -2048 <= imm < 2048
    return ((imm & 4095) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def r_type(f7, f3, rd, rs1, rs2):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | 0x33


class Image:
    def __init__(self):
        self.words, self.labels, self.fixups = [], {}, []
    @property
    def pc(self):
        return BASE + 4 * len(self.words)
    def label(self, name):
        assert name not in self.labels
        self.labels[name] = self.pc
    def emit(self, word):
        assert 0 <= word < (1 << 32)
        self.words.append(word)
    def addi(self, rd, rs, imm): self.emit(i_type(0x13, 0, rd, rs, imm))
    def ld(self, rd, rs, imm=0): self.emit(i_type(3, 3, rd, rs, imm))
    def sd(self, rs2, rs1, imm=0):
        assert -2048 <= imm < 2048
        imm &= 4095
        self.emit(((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (3 << 12) | ((imm & 31) << 7) | 0x23)
    def add(self, rd, a, b): self.emit(r_type(0, 0, rd, a, b))
    def mul(self, rd, a, b): self.emit(r_type(1, 0, rd, a, b))
    def divu(self, rd, a, b): self.emit(r_type(1, 5, rd, a, b))
    def csrw(self, csr, rs): self.emit((csr << 20) | (rs << 15) | (1 << 12) | 0x73)
    def csrr(self, rd, csr): self.emit((csr << 20) | (2 << 12) | (rd << 7) | 0x73)
    def li(self, rd, value):
        value = signed(value, 64)
        if -2048 <= value < 2048:
            self.addi(rd, 0, value)
        else:
            low = signed(value, 12)
            self.li(rd, (value - low) >> 12)
            self.emit(i_type(0x13, 1, rd, rd, 12))
            if low: self.addi(rd, rd, low)
    def la(self, rd, label):
        self.fixups.append(('la', len(self.words), rd, label)); self.emit(0); self.emit(0)
    def jump(self, label):
        self.fixups.append(('jal', len(self.words), 0, label)); self.emit(0)
    def branch(self, f3, a, b, label):
        self.fixups.append(('branch', len(self.words), (f3, a, b), label)); self.emit(0)
    def nop(self): self.addi(0, 0, 0)
    def sfence(self): self.emit(0x12000073)
    def fence(self): self.emit(0x0330000f)
    def fence_i(self): self.emit(0x0000100f)
    def mret(self): self.emit(0x30200073)
    def finalize(self):
        for kind, index, register, label in self.fixups:
            delta = self.labels[label] - (BASE + index * 4)
            if kind == 'la':
                hi = (delta + 0x800) >> 12; lo = delta - (hi << 12)
                self.words[index] = ((hi & 0xfffff) << 12) | (register << 7) | 0x17
                self.words[index + 1] = i_type(0x13, 0, register, register, lo)
            elif kind == 'jal':
                assert delta % 2 == 0 and -(1 << 20) <= delta < (1 << 20)
                u = delta & ((1 << 21) - 1)
                self.words[index] = (((u >> 20) & 1) << 31) | (((u >> 1) & 1023) << 21) | (((u >> 11) & 1) << 20) | (((u >> 12) & 255) << 12) | 0x6f
            else:
                assert delta % 2 == 0 and -4096 <= delta < 4096
                f3, a, b = register; u = delta & 8191
                self.words[index] = (((u >> 12) & 1) << 31) | (((u >> 5) & 63) << 25) | (b << 20) | (a << 15) | (f3 << 12) | (((u >> 1) & 15) << 8) | (((u >> 11) & 1) << 7) | 0x63
        return b''.join(word.to_bytes(4, 'little') for word in self.words)


def cold_loads(a):
    for rd, offset in zip((2, 3, 4, 5), (0, 64, 128, 192)):
        a.ld(rd, 8, offset)


def pair(a, prefix, offset=256, kind='left'):
    a.label(prefix + '_dummy'); a.addi(9, 7, 17)
    # Deliberately different from a move alias. P0 belongs in the second ranked
    # issue slot when dummy/P0 become eligible together; reachability is measured.
    a.label(prefix + '_p0'); a.addi(10, 8, offset)
    a.label(prefix + '_c1')
    if kind == 'right': a.add(11, 7, 10)
    elif kind == 'both': a.add(11, 10, 10)
    else: a.addi(11, 10, 8)


def descendants(a, prefix):
    a.label(prefix + '_load'); a.ld(12, 11)
    a.label(prefix + '_mul'); a.mul(13, 11, 7)
    a.label(prefix + '_store'); a.sd(13, 11, 8)


def make_image():
    a = Image(); a.label('_start'); a.li(20, CTRL)
    a.la(6, 'trap'); a.csrw(0x305, 6)
    # pmpaddr0/1 and cfg are seeded per scenario, always via real head CSRs.
    for offset, csr in ((72, 0x3b0), (80, 0x3b1), (88, 0x3a0), (24, 0x180)):
        a.ld(6, 20, offset); a.csrw(csr, 6)
    a.sfence(); a.ld(8, 20, 32); a.li(7, 8)
    a.ld(6, 20, 0); a.csrw(0x341, 6)
    a.ld(6, 20, 16); a.csrw(0x300, 6); a.mret()
    families = ('D1', 'D2', 'D3head', 'D3behind', 'D4', 'D5load', 'D5store', 'D6div', 'D6mul', 'D6csr')
    for family in families:
        for phase in PHASES:
            prefix = f'{family}_p{phase}'; a.label(prefix)
            for _ in range(phase): a.nop()
            if family == 'D1':
                cold_loads(a); pair(a, prefix); descendants(a, prefix)
                # Mixed load/ALU and old-value refill candidates use distinct PCs.
                a.label(prefix + '_mixed_load'); a.ld(16, 8, 512)
                a.addi(17, 8, 520); a.label(prefix + '_mixed'); a.add(18, 16, 17)
                a.label(prefix + '_old'); a.addi(17, 8, 528)
                a.label(prefix + '_consume'); a.addi(19, 17, 8)
                a.label(prefix + '_replace'); a.addi(17, 8, 536)
            elif family == 'D2':
                a.li(6, MASK); a.label(prefix + '_div'); a.divu(14, 6, 7)
                a.label(prefix + '_branch'); a.branch(1, 14, 0, prefix + '_target')
                cold_loads(a); pair(a, prefix); descendants(a, prefix)
                a.label(prefix + '_sentinel'); a.sd(13, 20, 0x100)
                a.label(prefix + '_target')
                a.divu(14, 6, 7)
                for n in range(96): a.addi(1 + n % 19, 0, n + 1)
            elif family.startswith('D3'):
                if family == 'D3behind': a.li(6, MASK); a.divu(14, 6, 7)
                a.addi(15, 8, 2040); a.addi(15, 15, 2040); a.addi(15, 15, 16)
                a.label(prefix + '_fault'); a.ld(16, 15)
                a.label(prefix + '_resume')  # handler skips exactly the faulting 32-bit load
                cold_loads(a); pair(a, prefix); descendants(a, prefix)
                a.label(prefix + '_sentinel'); a.sd(13, 20, 0x100)
            elif family == 'D4' or family.startswith('D5'):
                cold_loads(a)
                a.addi(15, 8, 2040); a.addi(15, 15, 2040)
                a.label(prefix + '_dummy'); a.addi(9, 7, 17)
                a.label(prefix + '_p0'); a.addi(10, 15, 16)
                a.label(prefix + '_c1'); a.addi(11, 10, 8)
                a.label(prefix + '_fault')
                if family == 'D5store': a.sd(7, 11)
                else: a.ld(12, 11)
                a.jump('unexpected_no_fault')
                a.label(prefix + '_resume')
                a.label(prefix + '_retry')
                if family == 'D5store': a.sd(7, 11)
                else: a.ld(12, 11)
            else:
                a.li(6, MASK)
                a.label(prefix + '_competitor')
                if family == 'D6div': a.divu(14, 6, 7)
                elif family == 'D6mul': a.mul(14, 6, 7)
                else: a.csrr(14, 0x140)  # sscratch: legal S-mode head CSR
                pair(a, prefix); descendants(a, prefix)
            a.jump('finish')
    a.label('D6serial')
    a.ld(6, 20, 64); a.csrw(0x180, 6); a.sfence()
    a.ld(6, 20, 96); a.csrw(0x3a0, 6); a.fence_i()
    a.la(6, 'finish'); a.csrw(0x341, 6); a.li(6, 1 << 11); a.csrw(0x300, 6); a.mret()
    a.label('finish'); a.li(6, 0x600d); a.sd(6, 20, 0x118); a.fence_i(); a.fence()
    a.label('done'); a.nop(); a.label('terminal_ecall'); a.emit(0x00000073); a.jump('done')
    a.label('unexpected_no_fault'); a.li(6, 0xbad); a.sd(6, 20, 0x118); a.jump('done')
    a.label('trap')
    # Reserved x25..x31 are handler scratch; all scenario source registers survive.
    a.csrr(25, 0x342); a.csrr(26, 0x341); a.csrr(27, 0x343)
    a.sd(25, 20, 0x120); a.sd(26, 20, 0x128); a.sd(27, 20, 0x130)
    a.ld(28, 20, 0x138); a.addi(28, 28, 1); a.sd(28, 20, 0x138)
    a.li(29, 1); a.branch(1, 28, 29, 'trap_stop')
    a.ld(29, 20, 40); a.branch(1, 25, 29, 'trap_stop')
    a.ld(29, 20, 48); a.branch(1, 26, 29, 'trap_stop')
    a.ld(29, 20, 104); a.branch(1, 27, 29, 'trap_stop')
    a.ld(29, 20, 64); a.csrw(0x180, 29); a.sfence()
    a.ld(29, 20, 96); a.csrw(0x3a0, 29)
    a.ld(29, 20, 56); a.csrw(0x341, 29); a.mret()
    a.label('trap_stop'); a.jump('trap_stop')
    data = a.finalize()
    assert len(data) < 32768
    return a, data


def page_tables(root, denied=False, remap=False):
    memory = {}
    branch = lambda pa: ((pa >> 12) << 10) | 1
    leaf = lambda pa: ((pa >> 12) << 10) | 0xcf  # V R W X A D, S-only
    l1_identity, l1_data, l0_data = root + 4096, root + 8192, root + 12288
    # Every page-table byte is predeclared zero; writes below only install PTEs.
    for page in (root, l1_identity, l1_data, l0_data):
        for offset in range(0, 4096, 8): memory[page + offset] = 0
    memory[root + 16] = branch(l1_identity)
    memory[l1_identity + 8] = leaf(BASE)  # 2 MiB identity code
    memory[l1_identity + 24] = leaf(CTRL) # 2 MiB identity control
    memory[root + 8] = branch(l1_data); memory[l1_data] = branch(l0_data)
    memory[l0_data] = leaf(DATA)
    if not denied: memory[l0_data + 8] = leaf((ALT if remap else DATA) + 4096)
    return memory


def service(family, phase):
    # Parameters depend ONLY on scenario inputs, accepted address/beat and time.
    return {'law': 'retained_DdrModel_plus_predeclared_directed_read_rules_v1',
            'read_credits': 8, 'base_read_latency': 32, 'beat_gap': 1,
            'ar_block_mod7': 2, 'aw_block_mod11': 3, 'w_block_mod5': 1,
            'b_after_wlast': 32, 'r_selection': 'newest eligible; hold full beat until fire',
            'phase_extra_read_delay': phase,
            'delayed_line': DATA + 256 if family == 'D2' else None,
            'delayed_line_min_latency': 240 if family == 'D2' else None,
            'error_line': DATA + 4096 if family.startswith('D3') else None,
            'error_occurrence': 0 if family.startswith('D3') else None,
            'error_beat': 'last' if family.startswith('D3') else None,
            'error_resp': 2 if family.startswith('D3') else None,
            'mutate_dut': False, 'adaptive_alignment': False}


def read_rule(law, *, accepted_cycle, physical_address, line_occurrence, beat, count):
    line = physical_address & ~63
    latency = law['base_read_latency'] + law['phase_extra_read_delay']
    if line == law['delayed_line']:
        latency = max(latency, law['delayed_line_min_latency'])
    error = line == law['error_line'] and line_occurrence == law['error_occurrence'] and beat + 1 == count
    return {'first_due': accepted_cycle + latency, 'response': law['error_resp'] if error else 0}


def scenarios(image):
    result = []
    families = ('D1', 'D2', 'D3head', 'D3behind', 'D4', 'D5load', 'D5store', 'D6div', 'D6mul', 'D6csr')
    for family in families:
        modes = ('sv39',) if family == 'D4' else ('bare',) if family.startswith('D5') else ('bare', 'sv39')
        for mode in modes:
            for phase in PHASES:
                name = f'{family}-{mode}-p{phase}'; prefix = f'{family}_p{phase}'
                virtual = mode == 'sv39'; address = 0x40000000 if virtual else DATA
                satp = (8 << 60) | (ROOT_A >> 12) if virtual else 0
                next_satp = ((8 << 60) | (ROOT_B >> 12)) if family == 'D4' else satp
                pmp = family.startswith('D5')
                fault = family.startswith('D3') or family == 'D4' or pmp
                cause = 13 if family == 'D4' else 7 if family == 'D5store' else 5 if fault else 0
                tval = address + (4096 if family.startswith('D3') else 4104) if fault else 0
                controls = {0:image.labels[prefix], 8:phase, 16:1 << 11, 24:satp, 32:address,
                            40:cause, 48:image.labels.get(prefix + '_fault', 0),
                            56:image.labels.get(prefix + '_resume', 0), 64:next_satp,
                            72:((DATA + 4096) >> 2) | 511 if pmp else MASK,
                            80:MASK, 88:0x1f18 if pmp else 0x1f, 96:0x1f1f if pmp else 0x1f, 104:tval}
                memory = {CTRL + n:0 for n in range(0, 512, 8)}
                memory.update({CTRL + off:val for off,val in controls.items()})
                memory.update({DATA+n:0x10203040+n//8 for n in range(0, 8192, 8)})
                memory.update({ALT+n:0x50607080+n//8 for n in range(4096, 8192, 8)})
                if virtual:
                    memory.update(page_tables(ROOT_A, denied=family == 'D4'))
                    memory.update(page_tables(ROOT_B, remap=True))
                result.append({'name':name, 'family':family, 'mode':mode, 'phase':phase,
                    'status':'NOT_RUN', 'bounds':BOUNDS, 'entry':image.labels[prefix],
                    'image':'guest.bin', 'reset_before':True, 'service':service(family, phase),
                    'initial_memory':{f'{k:#x}':v for k,v in sorted(memory.items())},
                    'fault':{'pc':controls[48], 'cause':cause, 'tval':tval, 'resume':controls[56]} if fault else None,
                    'expected_terminal':{'pc':image.labels['done'], 'signature_address':CTRL+0x118,
                                         'signature':0x600d, 'fault_count_before_terminal_ecall':int(fault),
                                         'sentinel_address':CTRL+0x100, 'sentinel':((address+264)*8)&MASK if family.startswith('D3') else 0},
                    'roles':{key[len(prefix)+1:]:value for key,value in image.labels.items() if key.startswith(prefix+'_')}})
    serial = dict(result[0]); serial.update(name='D6serial-bare', family='D6serial', mode='bare', phase=0, entry=image.labels['D6serial'], roles={})
    serial['initial_memory'] = dict(result[0]['initial_memory'])
    serial['initial_memory'][f'{CTRL:#x}'] = image.labels['D6serial']
    serial['initial_memory'][f'{CTRL+16:#x}'] = 3 << 11
    serial['initial_memory'][f'{CTRL+64:#x}'] = (8 << 60) | (ROOT_B >> 12)
    serial['initial_memory'][f'{CTRL+96:#x}'] = 0x1f1f
    serial['initial_memory'].update({f'{k:#x}':v for k,v in page_tables(ROOT_B, remap=True).items()})
    serial['service'] = service('D6serial', 0)
    result.append(serial)
    return result


def write(out):
    image, data = make_image(); cases = scenarios(image)
    out.mkdir(parents=True, exist_ok=True)
    (out/'guest.bin').write_bytes(data)
    (out/'symbols.json').write_text(json.dumps(image.labels, indent=2, sort_keys=True)+'\n')
    # Deduplicate memory seeds; all control words remain explicit per reset.
    (out/'seeds').mkdir(exist_ok=True)
    for case in cases:
        memory=case.pop('initial_memory')
        case['control_qwords']={k:v for k,v in memory.items() if CTRL<=int(k,16)<CTRL+512}
        seed={k:v for k,v in memory.items() if not CTRL<=int(k,16)<CTRL+512}
        seed_text=json.dumps(seed,sort_keys=True,indent=2)+'\n'
        name=hashlib.sha256(seed_text.encode()).hexdigest()+'.json'
        (out/'seeds'/name).write_text(seed_text)
        case['seed_file']='seeds/'+name
    (out/'scenarios.json').write_text(json.dumps(cases, indent=2, sort_keys=True)+'\n')
    labels_by_pc={}
    for name,pc in image.labels.items(): labels_by_pc.setdefault(pc,[]).append(name)
    listing='pc\tword\tlabels\n'+''.join(f'{BASE+4*i:016x}\t{word:08x}\t{",".join(labels_by_pc.get(BASE+4*i,[]))}\n' for i,word in enumerate(image.words))
    (out/'guest.words.tsv').write_text(listing)
    summary = {'status':'PREPARED_NOT_RUN', 'image_sha256':hashlib.sha256(data).hexdigest(),
               'image_bytes':len(data), 'scenario_count':len(cases), 'bounds':BOUNDS,
               'source_encoder':'independent immediate/field encoding; no DUT decode tables',
               'limitations':['Alignment and mandatory overlap NOT_REACHED until executed.',
                              'D1 right/both held-source subcases are not encoded in this first image; required old fixture source controls remain separate.',
                              'Complete integrated observer/host binding remains blocked; image is not qualified.',
                              'No compiled guest ELF, model, native/C++ build, or simulation was performed.']}
    (out/'inputs.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--out', type=Path, required=True)
    print(json.dumps(write(p.parse_args().out), indent=2))
