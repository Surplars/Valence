"""Offline pinned ROM asset/image check. Never opens Vivado or executes Tcl."""
import argparse
import hashlib
import json
from pathlib import Path
import re

SOURCE = '50cb0c5d4b17318904d6cf818ad23829821d5d93'
WRAPPER = '2ff5598b214b31506231b6de198d49c843a6d897abf77ab8a9d7a65270ca3028'
IP = 'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/'
SELECTED = {
    'schema': 'repair-diagnostic-current-355-rom-v1',
    'raw_binary_bytes': 67280, 'padded_bytes': 131072,
    'raw_binary_sha256': 'ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79',
    'coe_sha256': 'ca0c9a52825208dc93d16e38a6f43a83e3c997b3e425d7cabe8828da23b0b61b',
    'padded_binary_sha256': '0d03f41230ed458e133d9503acba36edb34689f5aaa6cafd41ea2f81ec5879fd',
    'dcp_sha256': '6f86eef783b3cb795fd4c2c2d99870e0215f4d8d523f883f2e95fbfc624cc0bc',
    'mif_sha256': 'e60ed763c09520a9c041d87d834368b4a4928fe4ce7bd57fa60434048640508b',
    'veo_sha256': '6ba6eaf309ad20d8ee0a9839361e38766868c92dad4d942ff71f5c4b32144fe9',
    'firmware_tree': '9c3617721204969d349baa2042a6b628fa2edfc5',
    'vivado': '2025.1 build6140274', 'part': 'xczu15eg-ffvb1156-2-i', 'port_count': 8,
}
FILES = {'firmware/bootrom.bin': 'raw_binary_sha256', 'firmware/bootrom.coe': 'coe_sha256',
         IP+'blk_mem_gen_0.dcp': 'dcp_sha256', IP+'blk_mem_gen_0.mif': 'mif_sha256',
         IP+'blk_mem_gen_0.veo': 'veo_sha256'}
DCP = SELECTED['dcp_sha256']

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def image_check(raw, mif, coe, even=None, odd=None):
    require(0 < len(raw) <= 131072, 'Raw ROM size outside 1..131072')
    padded = raw + bytes(131072-len(raw))
    words = mif.split()
    require(len(words) == 32768 and all(re.fullmatch('[01]{32}', x) for x in words), 'Unsupported MIF word inventory')
    require(b''.join(int(x,2).to_bytes(4,'little') for x in words) == padded, 'MIF differs from raw plus zero padding')
    match = re.fullmatch(r'\s*memory_initialization_radix\s*=\s*16\s*;\s*memory_initialization_vector\s*=\s*([0-9a-fA-F,\s]+);\s*', coe)
    require(match is not None, 'Unsupported COE format')
    tokens = [x.strip() for x in match[1].split(',')]
    require(len(tokens) == 32768 and all(re.fullmatch('[0-9a-fA-F]{1,8}', x) for x in tokens), 'Wrong COE word inventory')
    values = [int(x,16) for x in tokens]
    require(b''.join(x.to_bytes(4,'little') for x in values) == padded, 'COE image differs')
    require((even is None) == (odd is None), 'Both optional banks are required together')
    for index, text in enumerate([] if even is None else [even, odd]):
        tokens = text.split()
        require(len(tokens) == 16384 and all(re.fullmatch('[0-9a-fA-F]{1,8}', x) for x in tokens), 'Wrong bank word inventory')
        require([int(x,16) for x in tokens] == values[index::2], 'Even/odd bank image differs')
    return dict(raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                padded_bytes=131072, padded_sha256=hashlib.sha256(padded).hexdigest(),
                logical_words=32768, word_bytes=4, word_endianness='little',
                padding='zero bytes after raw length to 131072',
                bank_order='A even word addresses; B odd word addresses',
                mif_coe_equal=True, optional_even_odd_checked=even is not None)

def verify(package, inputs):
    manifest = package/'local-rom-required.json'
    selected = json.loads(manifest.read_text())
    for key, value in SELECTED.items():
        require(selected.get(key) == value, 'Explicit selected ROM contract mismatch: '+key)
    require(selected.get('firmware_tree_equal_between') == ['3554932ea0b1136ba9b41257385df0c1e8c5ff5c', SOURCE], 'Firmware provenance mismatch')
    wrapper = package/'rtl/InstructionRom.sv'
    require(sha(wrapper) == WRAPPER, 'Frozen CPU InstructionRom.sv changed')
    text = wrapper.read_text()
    instance = re.findall(r'blk_mem_gen_0\s+memory\s*\((.*?)\);', text, re.S)
    require(len(instance) == 1, 'Expected unique actual ROM instance')
    for pin in ['clka', 'clkb']:
        require(re.findall(r'\.'+pin+r'\s*\(\s*([^)]*?)\s*\)', instance[0]) == ['clock'], 'Wrapper clocks are not both original clock')
    verified = {}
    for relative, key in FILES.items():
        path = inputs/relative
        require(path.is_file(), 'Missing local ROM asset: '+str(path))
        require(sha(path) == selected[key], 'Local ROM asset hash mismatch: '+relative)
        verified[relative] = dict(sha256=selected[key], bytes=path.stat().st_size)
    veo = (inputs/(IP+'blk_mem_gen_0.veo')).read_text()
    ports = re.findall(r'\.(\w+)\s*\(', veo)
    require(sorted(ports) == sorted(['clka','ena','addra','douta','clkb','enb','addrb','doutb']), 'VEO interface changed')
    image = image_check((inputs/'firmware/bootrom.bin').read_bytes(),
        (inputs/(IP+'blk_mem_gen_0.mif')).read_text(),
        (inputs/'firmware/bootrom.coe').read_text())
    require(image['raw_bytes'] == selected['raw_binary_bytes'], 'Selected raw ROM length changed')
    require(image['padded_sha256'] == selected['padded_binary_sha256'], 'Selected padded ROM image changed')
    contract = dict(schema='rom-leaf-clock-r3', source_commit=SOURCE, wrapper_sha256=WRAPPER,
        vendor_dcp_sha256=DCP, expected_leaf_clocks=64, expected_bram_clocks=58, expected_selector_clocks=6,
        local_asset_status='PASS_HASHED_ROM_ASSETS_AND_IMAGE')
    return dict(status='PASS_OFFLINE_ASSETS_ACTUAL_LEAF_PROOF_STILL_REQUIRED', contract=contract,
        image=image, files=verified, selected_manifest_sha256=sha(manifest),
        verifier_sha256=sha(__file__), gate_sha256=sha(Path(__file__).with_name('r3_rom_graph_leaf_r3.tcl')),
        sealed_r1_gate_sha256=sha(package/'rom-audit/r3_rom_graph_leaf_r1.tcl'),
        remaining='Fresh post-synthesis and post-place actual leaf connectivity/polarity audit plus all-word INIT graph reconstruction; this receipt alone does not authorize placement or prove clock timing.')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package-root', type=Path, required=True)
    ap.add_argument('--local-input-root', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    a=ap.parse_args()
    result=verify(a.package_root.resolve(), a.local_input_root.resolve())
    a.output_dir.mkdir(parents=True, exist_ok=False)
    (a.output_dir/'local-rom-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    values=' '.join(f'{k} {{{v}}}' for k,v in result['contract'].items())
    (a.output_dir/'local-rom-contract.tcl').write_text('# Generated only after pinned offline asset/image checks.\nrom_leaf_r3::configure [dict create '+values+']\n')
    print(json.dumps(result,sort_keys=True))

if __name__ == '__main__':
    main()
