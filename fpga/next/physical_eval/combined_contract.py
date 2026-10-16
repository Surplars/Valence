"""Version 1 combined-bandwidth input contract. No hardware/tool execution.

This contract deliberately does not call or modify the historical native gate.
Every accepted export must originate in emit_combined.py's fresh-source wrapper.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
from input_contract import relative_input

SCHEMA = 'combined-bandwidth-physical-inputs-v1'
FLAGS = dict(rankResidentPriority=True, sharedTwoWordFetchPmp=True,
             disjointEvictionStoreOverlap=True, splitCacheableBounds=False)
ROM_FILES = ('bootrom.bin', 'bootrom.coe', 'bootrom.even.hex', 'bootrom.odd.hex',
             'bootrom-contract.json', 'bootrom.map')
IP_FILES = (
    'ip-build/board_ip.srcs/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.xci',
    'ip-build/board_ip.srcs/sources_1/ip/clk_wiz_ddr/clk_wiz_ddr.xci',
    'ip-build/board_ip.srcs/sources_1/ip/axi_clock_converter_ddr/axi_clock_converter_ddr.xci',
    'mig/ZU15EG.srcs/sources_1/ip/ddr4_0/ddr4_0.xci',
    'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.mif',
    'board/board_ddr.xdc', 'board/pl_ddr4_pins.xdc')


def require(test, message):
    if not test:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def info(path):
    return dict(sha256=sha(path), bytes=Path(path).stat().st_size)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')


def checked_files(root, entries):
    require(isinstance(entries, dict) and bool(entries), 'Empty file inventory')
    for name, expected in entries.items():
        require(isinstance(name, str) and name and str(Path(name)) == name, 'Noncanonical file path')
        path = relative_input(root, name)
        require(path.is_file() and not (Path(root)/name).is_symlink(), 'Missing/symlink input: ' + name)
        require(expected == info(path), 'File bytes/hash mismatch: ' + name)


def source_closure(root):
    root = Path(root).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    require(not git('status', '--porcelain', '--untracked-files=all'),
            'Fresh export requires clean tracked and untracked source checkout')
    files, gitlinks = {}, {}
    for record in git('ls-files', '--stage', '-z').decode().split('\0'):
        if not record:
            continue
        head, name = record.split('\t', 1)
        mode, oid, stage = head.split()
        require(stage == '0', 'Unmerged source')
        if mode == '160000':
            gitlinks[name] = oid
        else:
            require(mode in ('100644', '100755'), 'Unsupported source file mode: ' + name)
            path = relative_input(root, name)
            require(path.is_file() and not (root/name).is_symlink(), 'Missing source: ' + name)
            files[name] = info(path)
    require('build.mill' in files and '.mill-version' in files, 'Missing build source closure')
    return dict(schema='combined-bandwidth-source-closure-v1',
                commit=git('rev-parse', 'HEAD').decode().strip(),
                tree=git('rev-parse', 'HEAD^{tree}').decode().strip(), files=files, gitlinks=gitlinks)


def validate_native(root, closure, toolchain):
    root = Path(root)
    entry = read(root/'native-entry.json')
    actual = read(root/'actual-combined-native.json')
    inventory = read(root/'rtl-inventory.json')
    provenance = read(root/'export-provenance.json')
    require(entry['schema'] == 'combined-bandwidth-experimental-native-entry-v1' and
            entry['identity'] == 'combined-bandwidth-native-experimental', 'Wrong candidate entry')
    require(actual['schema'] == 'combined-bandwidth-native-actual-v1', 'Wrong actual audit schema')
    require(actual['featureFlags'] == FLAGS and
            all(type(actual['featureFlags'][key]) is bool for key in FLAGS), 'Wrong actual feature flags')
    require(entry['actualAuditSha256'] == sha(root/'actual-combined-native.json'), 'Stale actual audit receipt')
    require(entry['rtlInventorySha256'] == sha(root/'rtl-inventory.json'), 'Stale RTL inventory receipt')
    require(inventory['schema'] == 'combined-bandwidth-rtl-inventory-v1', 'Wrong inventory schema')
    checked_files(root, inventory['files'])
    emitted = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.suffix in ('.sv', '.v')}
    listed = {name for name in inventory['files'] if Path(name).suffix in ('.sv', '.v')}
    require(emitted == listed and 'FpgaNextSocTop.sv' in listed, 'Missing/extra RTL inventory')
    require('filelist.f' in inventory['files'], 'Unsealed synthesis filelist')
    filelist = [x.strip() for x in (root/'filelist.f').read_text().splitlines() if x.strip() and not x.startswith('#')]
    require(len(filelist) == len(set(filelist)) and set(filelist) == listed, 'Incomplete/duplicate synthesis filelist')
    for key, value in dict(coreFields=178, profileFields=95, nativeTopPorts=76,
                           physicalQualification=False, qualificationInherited=False,
                           nativeMacPhysicalGenericsApplied=False, mode='native').items():
        require(type(entry[key]) is type(value) and entry[key] == value, 'Entry boundary mismatch: ' + key)
    require(actual['counts'] == dict(residentSelectors=1, sharedPmpHelpers=2, nonBlockingCaches=1,
                                    nativeMacs=1, bscanTransports=1, standaloneTaps=0), 'Wrong actual instance counts')
    require(all(type(value) is int for value in actual['counts'].values()), 'Actual instance counts must be integers')
    for key, count in (('core', 178), ('profile', 95)):
        require(len(actual[key]) == count and actual[key+'Fields'] == count, 'Incomplete actual ' + key)
        order = actual['fieldOrder'][key]
        require(len(order) == len(set(order)) == count and set(order) == set(actual[key]), 'Wrong field order')
    require(actual['core']['memoryEntries'] == 4, 'Require LSU4')
    require(actual['profile']['independentDemandAdmission'] is True and
            actual['profile']['memoryScheduleOverlap'] is True, 'Missing overlap prerequisites')
    geometry = actual['geometry']
    for key, value in dict(cacheLines=512, cacheWays=2, proofRows=3, earlyLoadCredits=2, lsuOwners=4).items():
        require(geometry[key] == value, 'Wrong geometry: ' + key)
    native = actual['nativeBoundaries']
    require(native['rawHandoffPresent'] is True and native['ramLoaderPresent'] is True and
            native['bscanChain'] == 2 and native['nativeMacPhysicalGenericsApplied'] is False, 'Wrong native boundary')
    require(actual['clockHz'] == dict(cpu=100000000, aon=50000000, uart=50000000, ddrUi=250000000), 'Wrong clocks')
    ports = actual['topPorts']
    require(len(ports) == len({p['name'] for p in ports}) == 76 and
            all(type(p['width']) is int and p['width'] > 0 for p in ports), 'Incomplete actual top ports')
    require(actual['qualificationInherited'] is False and actual['physicalQualification'] is False,
            'Qualification cannot be inherited')
    require(provenance['schema'] == 'combined-bandwidth-export-provenance-v1' and
            provenance['status'] == 'PASS_FRESH_NATIVE_EXPORT_ONLY', 'Missing fresh export provenance')
    require(provenance['sourceClosure'] == closure, 'Changed source/stale export provenance')
    require(provenance['toolchain'] == toolchain, 'Different emission toolchain')
    checked_files(root, provenance['artifacts'])
    require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} ==
            set(provenance['artifacts']) | {'export-provenance.json'}, 'Missing/extra native artifacts')
    require({'native-entry.json', 'actual-combined-native.json', 'rtl-inventory.json'} <= set(provenance['artifacts']),
            'Unbound audit/entry/inventory')
    require({p['name']: (p['direction'], p['width']) for p in ports} == native_ports(root/'FpgaNextSocTop.sv'),
            'Actual top-port audit differs from emitted SV')
    return dict(entry=entry, actual=actual, inventory=inventory, provenance=provenance)


def native_ports(path):
    text = Path(path).read_text()
    match = re.search(r'\bmodule\s+FpgaNextSocTop\s*\((.*?)\);', text, re.S)
    require(match is not None, 'Missing native top module')
    result, direction, width = {}, None, None
    for part in match[1].split(','):
        part = re.sub(r'//[^\n]*', '', part).strip()
        declaration = re.match(r'(input|output|inout)\b', part)
        if declaration:
            direction = {'input': 'Input', 'output': 'Output', 'inout': 'Bidirectional'}[declaration[1]]
            size = re.search(r'\[(\d+):(\d+)\]', part)
            width = abs(int(size[1])-int(size[2]))+1 if size else 1
        names = re.findall(r'[A-Za-z_][A-Za-z0-9_$]*', part)
        require(bool(names) and names[-1] not in result and direction is not None, 'Malformed top ports')
        result[names[-1]] = (direction, width)
    return result


def validate_rom(root, manifest, raw_hash, padded_hash):
    require(set(manifest) == set(ROM_FILES), 'Require all six explicitly hashed ROM inputs')
    checked_files(root, manifest)
    raw = (Path(root)/'bootrom.bin').read_bytes()
    require(0 < len(raw) <= 131072 and hashlib.sha256(raw).hexdigest() == raw_hash, 'ROM binary mismatch')
    padded = raw + bytes(131072-len(raw))
    require(hashlib.sha256(padded).hexdigest() == padded_hash, 'Padded ROM mismatch')
    text = (Path(root)/'bootrom.coe').read_text()
    match = re.fullmatch(r'\s*memory_initialization_radix\s*=\s*16\s*;\s*memory_initialization_vector\s*=\s*([0-9a-fA-F,\s]+);\s*', text)
    require(match is not None, 'Unsupported COE format')
    words = [int(x, 16) for x in re.split(r'[,\s]+', match[1]) if x]
    require(len(words) == 32768 and all(0 <= x < 2**32 for x in words), 'Wrong COE words')
    require(b''.join(x.to_bytes(4, 'little') for x in words) == padded, 'COE differs from selected ROM')
    for index, bank in enumerate(('even', 'odd')):
        bank_words = [int(x, 16) for x in (Path(root)/f'bootrom.{bank}.hex').read_text().split()]
        require(bank_words == words[index::2], 'Wrong ROM ' + bank + ' bank')
    contract = read(Path(root)/'bootrom-contract.json')
    require(contract['bootrom_sha256'] == raw_hash and contract['cpu_hz'] == 100000000 and
            contract['timebase_hz'] == 100000000, 'Wrong ROM hash/clock contract')
    require((Path(root)/'bootrom.map').stat().st_size > 0, 'Missing real ROM link map')
    return padded


def tcl_without_standalone_comments(text):
    """Drop only full-line comments at Tcl-proven complete-command boundaries.

    info complete parses syntax only, never evaluates the input. Quoted/braced/
    bracket bodies and backslash continuations remain byte-for-byte for scanning.
    """
    import tkinter
    interpreter = tkinter.Tcl()
    prefix, result = '', []
    continued = False
    for line in text.splitlines(keepends=True):
        standalone = not continued and bool(int(interpreter.call('info', 'complete', prefix)))
        if standalone and line.lstrip().startswith('#'):
            result.append('\n' if line.endswith('\n') else '')
        else:
            result.append(line)
        prefix += line
        body = line.rstrip('\r\n')
        continued = (len(body) - len(body.rstrip('\\'))) % 2 == 1
    return ''.join(result)


def validate_constraint_text(text, name):
    require(not re.search(r'(?m)(?:^|[;\s\[])(source|read_\w+|exec|open|load)\s',
                          tcl_without_standalone_comments(text)),
            'External-loading command in IP/XDC input requires explicit closure review: '+name)


def validate_validator_revision(source, validator):
    """Keep RTL/source identity fixed while separately binding reviewed staging code."""
    require(source['gitlinks'] == validator['gitlinks'], 'Validator checkout changed source gitlinks')
    for name in set(source['files']) | set(validator['files']):
        if not name.startswith('fpga/next/physical_eval/'):
            require(source['files'].get(name) == validator['files'].get(name),
                    'Validator revision changed non-staging source: '+name)


def validate_ip(root, inventory, padded, run, ownership=None):
    require(set(IP_FILES) <= set(inventory), 'Missing required four XCI/MIF/two XDC inputs')
    for name in inventory:
        require(name.startswith(('ip-build/', 'mig/')) or name in IP_FILES, 'Unexpected IP input: ' + name)
        if Path(name).suffix.lower() in ('.dcp', '.edf', '.edif'):
            validate_ip_asset(root, name, inventory, ownership or {})
    checked_files(root, inventory)
    for name in inventory:
        if Path(name).suffix.lower() in ('.xdc', '.tcl'):
            text = relative_input(root, name).read_text()
            validate_constraint_text(text, name)
    mif = relative_input(root, IP_FILES[4]).read_text().split()
    require(len(mif) == 32768 and all(re.fullmatch('[01]{32}', x) for x in mif), 'Unsupported MIF format')
    require(b''.join(int(x, 2).to_bytes(4, 'little') for x in mif) == padded, 'MIF differs from selected ROM')
    config = read(relative_input(root, IP_FILES[0]))['ip_inst']['parameters']['component_parameters']
    coe = config['Coe_File'][0]['value']
    require(not Path(coe).is_absolute() and '\\' not in coe and ':' not in coe, 'Nonportable ROM COE binding')
    require((Path(run)/IP_FILES[0]).parent.joinpath(coe).resolve() == Path(run).resolve()/'firmware/bootrom.coe',
            'ROM XCI must bind this staged COE')
    return inventory


def validate_ip_asset(root, name, inventory, ownership):
    """Only explicit XCI-owned OOC products; a SoC DCP is never an IP input."""
    import zipfile
    import xml.etree.ElementTree as ET
    require(name in ownership, 'Historical checkpoint/unproved IP asset ownership: '+name)
    owner = ownership[name]
    xci = owner.get('xci')
    require(xci in IP_FILES[:4], 'Unknown asset XCI owner: '+name)
    ip = Path(xci).stem
    require(ip in Path(name).parts[:-1] and Path(name).stem == ip and
            name.split('/')[0] == xci.split('/')[0], 'Wrong IP asset directory/top: '+name)
    require(owner.get('xciSha256') == inventory[xci]['sha256'], 'Stale IP asset XCI binding')
    require(owner.get('top') == ip and owner.get('part') == 'xczu15eg-ffvb1156-2-i', 'Wrong IP top/part owner')
    path = relative_input(root, name)
    if path.suffix.lower() == '.dcp':
        with zipfile.ZipFile(path) as archive:
            metadata = ET.fromstring(archive.read('dcp.xml'))
        def value(tag):
            nodes = metadata.findall(tag)
            require(len(nodes) == 1, 'Missing unambiguous DCP '+tag+' ownership proof')
            return nodes[0].get('Name')
        require(value('Top') == ip and value('Part') == owner['part'] and value('OutOfContext') == '1',
                'Disguised SoC/wrong IP DCP metadata: '+name)
    else:
        text = path.read_text()
        top = re.search(r'\(design\s+([^\s()]+)', text, re.I)
        part = re.search(r'\(property\s+PART\s+\(string\s+"([^"]+)"', text, re.I)
        require(top is not None and part is not None and top[1] == ip and part[1] == owner['part'],
                'Missing/wrong EDIF IP top/part proof: '+name)
