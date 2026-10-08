#!/usr/bin/env python3
"""Bounded home tag storage proof and exact baseline/candidate cycle replay.

No CPU, board, FPGA mapping or timing claim. Run --host-only without a toolchain.
Use --layout registers for the unmodified home baseline and --layout banked for
its candidate; --reference requires identical public-protocol transcript logs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import run as common
from data_cache_geometry import module


CASES = [(f'{kind}-l{lines}-c{compact}-m{entries}', mixed, lines, compact, entries)
         for kind, mixed in [('nonblocking', 0), ('mixed', 1)]
         for lines, compact, entries in [(16, 0, 2), (16, 1, 4), (512, 1, 2)]]
PROOF_FILES = ['simulator/gsim/home_tag_ram.py', 'simulator/gsim/harness/home_tag_ram.cpp',
               'simulator/gsim/harness/home_mshr.cpp', 'src/test/scala/ooo/HomeTagRamGsim.scala']


def host_equivalence():
    """Independent integer proof of indexed-tag equivalence, not an RTL oracle."""
    rng = random.Random(0x715a9)
    comparisons = omitted_qualifier_rejected = dropped_tag_bit_rejected = 0
    geometries = []
    for base, size in [(0, 0x20000), (0x80010000, 0x20000), (0xffff0000, 0x20000),
                       ((1 << 63) + 0xff0000, 0x20000), ((1 << 64) - 0x20000, 0x20000)]:
        for lines in (16, 512):
            sets = lines // 2
            set_bits = sets.bit_length() - 1
            for compact in (0, 1):
                high = max(7, (base + size - 1).bit_length()) if compact else 64
                new_high = max(7 + set_bits, (base + size - 1).bit_length()) if compact else 64
                # This is the complete indexed lookup relation: an installed
                # owner's set must equal the selected query set before tags compare.
                def hit(owner, query, trimmed, qualifier=True, drop_bit=False):
                    low, retained = (6 + set_bits, new_high) if trimmed else (6, high)
                    mask = (1 << (retained - low - int(drop_bit))) - 1
                    return (not compact or not qualifier or base <= query < base + size) and \
                        ((owner >> 6) & (sets - 1)) == ((query >> 6) & (sets - 1)) and \
                        ((owner >> low) & mask) == ((query >> low) & mask)
                edges = [0, 63, base, base + 64, base + size - 64, base + size - 1,
                         (base - 64) & ((1 << 64) - 1), (base + size) & ((1 << 64) - 1),
                         (1 << 32), (1 << 40), (1 << 63), (1 << 64) - 1]
                for index in range(1024):
                    owner = base + 64 * rng.randrange(size // 64)
                    query = rng.randrange(1 << 64) if index & 1 else base + rng.randrange(size)
                    candidates = edges + [query, owner, owner ^ (1 << (6 + set_bits)),
                        owner ^ (1 << min(new_high, 63)), owner ^ (1 << (new_high - 1))]
                    for address in candidates:
                        old = hit(owner, address, False)
                        new = hit(owner, address, True)
                        assert old == new, (base, size, lines, compact, owner, address)
                        comparisons += 1
                        omitted_qualifier_rejected += new != hit(owner, address, True, qualifier=False)
                        dropped_tag_bit_rejected += new != hit(owner, address, True, drop_bit=True)
                geometries.append({'base': hex(base), 'bytes': size, 'lines': lines, 'compact': compact,
                    'old_tag_bits': high - 6, 'new_tag_bits': new_high - 6 - set_bits})
    assert omitted_qualifier_rejected and dropped_tag_bit_rejected, 'host mutation witnesses absent'
    return {'status': 'PASS', 'comparisons': comparisons, 'geometries': geometries,
        'negative_omitted_qualifier_witnesses': omitted_qualifier_rejected,
        'negative_dropped_tag_bit_witnesses': dropped_tag_bit_rejected,
        'scope': 'integer indexed-tag identity and qualifier counterexamples; not hardware behavior'}


def source_audit(layout):
    facts = {}
    for name in ('NonBlockingCoherentLineHome', 'MixedCoherentLineHome'):
        text = (common.ROOT / f'src/main/scala/core/ooo/{name}.scala').read_text()
        if layout == 'banked':
            anchors = ['tagConfig.geometry(base, bytes, 6 + setBits)',
                'Seq.fill(trackedWays)(Mem(trackedLines / trackedWays, UInt(tagGeometry.tagBits.W)))',
                'tagBanks.map(_.read(setOf(tagLookupAddress)))',
                'tagBanks.map(_.read(setOf(port.c.bits.address)))',
                'tagBanks.map(_.read(setOf(port.a.bits.address)))',
                'tagLookupAddress := Mux(maintenance === mProbeSend, access.address, io.upstream.request.bits.address)',
                'directory(eEntry)(setBits - 1, 0) === setOf(addresses(eEntry))']
            assert all(a in text for a in anchors), name + ' source geometry/read client audit'
            assert text.count('tagBanks.map(_.read(') == 3
            assert text.count('tagBanks(way).write(') == 1
            assert text.count('acquireTags') == 2
            assert re.search(r'when\(port.a.fire\) \{\s*assert\([^;]+?lineOwned\(port.a.bits.address, acquireTags\)', text)
            facts[name] = {'functional_read_clients_per_way': 2, 'assert_only_read_clients_per_way': 1,
                'write_clients_per_way': 1, 'ownership_resettable_flops': True,
                'r0_select': 'registered maintenance == mProbeSend', 'physical_mapping': 'UNVERIFIED'}
        else:
            assert 'tagConfig.geometry(base, bytes, 6)' in text
            assert 'Reg(Vec(trackedLines, UInt(tagGeometry.tagBits.W)))' in text
            facts[name] = {'layout': 'flat full-line tag register vector'}
    return facts


def fir_audit(fir, mixed, lines, compact, layout):
    home = module(fir, 'MixedCoherentLineHome' if mixed else 'NonBlockingCoherentLineHome')
    assert f'regreset owned : UInt<1>[{lines}]' in home
    if layout == 'registers':
        bits = 27 if compact else 58
        assert f'reg tags : UInt<{bits}>[{lines}]' in home
        return {'tag_bits': bits, 'entries': lines, 'layout': 'registers'}
    sets = lines // 2
    bits = (33 if compact else 64) - 6 - (sets.bit_length() - 1)
    memories = re.findall(r'cmem (tagBanks_\d+) : UInt<(\d+)>\[(\d+)\]', home)
    assert len(memories) == 2 and all(int(width) == bits and int(depth) == sets
                                   for _, width, depth in memories), memories
    ports = {}
    for name, _, _ in memories:
        reads = re.findall(r'read mport (\w+) = ' + name + r'\[', home)
        writes = re.findall(r'write mport (\w+) = ' + name + r'\[', home)
        assert len(reads) == 3 and len(writes) == 1, (name, reads, writes)
        assert any('lookupTags' in value for value in reads)
        assert any('releaseTags' in value for value in reads)
        assert any('acquireTags' in value for value in reads)
        ports[name] = {'reads': reads, 'writes': writes, 'functional_reads': 2, 'assert_only_reads': 1}
    assert 'reg tags :' not in home
    return {'tag_bits': bits, 'banks': 2, 'sets': sets, 'ports': ports,
            'logical_tag_bits': bits * lines, 'physical_mapping': 'UNVERIFIED'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag')
    ap.add_argument('--layout', choices=['registers', 'banked'], default='banked')
    ap.add_argument('--reference', type=Path)
    ap.add_argument('--host-only', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if args.dry_run:
        print(json.dumps({'cases': CASES, 'base': '0xffff0000', 'bytes': 0x20000,
            'scope': 'home-only functional and structural checks; no CPU/FPGA'}, indent=2)); return
    if args.host_only:
        print(json.dumps(host_equivalence(), indent=2)); return
    if not args.tag or not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): ap.error('--tag requires a safe identifier')
    out = common.BUILD / ('home-tag-ram-' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [common.ROOT / x for x in PROOF_FILES if not x.endswith('.scala')]
    hashes = lambda: {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'status': 'RUNNING', 'layout': args.layout, 'source_sha256': hashes(), 'cases': {},
        'scope': 'independent home protocol/data oracle, deterministic cycle replay, logical FIR ports; no physical mapping/timing'}
    try:
        report['host_equivalence'] = host_equivalence()
        report['source_audit'] = source_audit(args.layout)
        reference = json.loads(args.reference.read_text()) if args.reference else None
        if reference:
            assert reference['status'] == 'PASS' and reference['layout'] == 'registers'
            assert all(reference['source_sha256'][p] == report['source_sha256'][p] for p in PROOF_FILES), 'proof source drift'
        gsim, cxx = common.setup(False)
        for name, mixed, lines, compact, entries in CASES:
            target = common.test(gsim, cxx, str(out.relative_to(common.BUILD) / name),
                'ooo.hometagram.HomeTagRamGsimMain', 'HomeMshrGsim', 'home_tag_ram.cpp',
                parameters=(entries, compact, lines, mixed),
                defines={'HOME_ENTRIES': entries, 'HOME_LINES': lines, 'HOME_MIXED': mixed,
                         'HOME_BASE': '0xffff0000ULL'}, timeout=120)
            log = (target / 'test.log').read_text()
            assert 'HOME_TAG_RAM_PASS' in log
            entry = {'status': 'PASS', 'log': log, 'geometry': fir_audit((target / 'HomeMshrGsim.fir').read_text(),
                     mixed, lines, compact, args.layout), 'negative': {}}
            for flag, anchor in [('--inject-data', 'independent Grant data mismatch'),
                ('--bad-owned-acquire', 'home accepts only an aligned unowned nToT AcquireBlock'),
                ('--bad-aperture', 'home accepts only an aligned unowned nToT AcquireBlock'),
                ('--bad-release-aperture', 'release has no committed directory owner')]:
                run = subprocess.run([target / 'run', flag], capture_output=True, text=True,
                    timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                failed = run.stdout + run.stderr
                (target / (flag[2:] + '.log')).write_text(failed)
                assert run.returncode != 0 and anchor in failed, (name, flag, failed[-2000:])
                entry['negative'][flag] = 'PASS'
            if reference:
                assert log == reference['cases'][name]['log'], name + ' public-protocol/cycle trace changed'
                entry['exact_baseline_replay'] = 'PASS'
            report['cases'][name] = entry
            (out / 'progress.json').write_text(json.dumps(report, indent=2) + '\n')
        assert hashes() == report['source_sha256'], 'source drift'
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': main()
