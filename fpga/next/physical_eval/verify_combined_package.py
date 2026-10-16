"""Read-only exact-byte gate before candidate synth/place. Does not invoke tools."""
import argparse
from pathlib import Path
from combined_contract import (SCHEMA, checked_files, read, require, validate_ip,
                               validate_native, validate_rom)


def verify(root, vivado_version):
    root = Path(root).resolve()
    seal = read(root/'package-seal.json')
    require(seal['schema'] == 'combined-bandwidth-package-seal-v1', 'Wrong package seal')
    checked_files(root, seal['files'])
    # Outputs may be created later, but input directories may never gain unsealed files.
    for directory in ('native', 'export', 'firmware', 'ip-build', 'mig', 'board', 'scripts', 'evidence'):
        present = {p.relative_to(root).as_posix() for p in (root/directory).rglob('*') if p.is_file()}
        expected = {name for name in seal['files'] if name.startswith(directory+'/')}
        require(present == expected, 'Missing/extra package files: '+directory)
    contract = read(root/'evidence/combined-inputs.json')
    require(contract['schema'] == SCHEMA and contract['physicalQualification'] is False, 'Wrong candidate contract')
    require(contract['vivadoVersion'] == vivado_version, 'Unexpected actual Vivado version')
    validate_native(root/'native', contract['sourceClosure'], contract['emissionToolchain'])
    padded = validate_rom(root/'firmware', contract['romManifest'], contract['romSha256'], contract['paddedSha256'])
    validate_ip(root, contract['ipManifest'], padded, root, contract['ipOwnership'])
    return 'PASS_COMBINED_EXACT_INPUT_BYTES_ONLY_NO_PHYSICAL_QUALIFICATION'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--vivado-version', required=True)
    args = parser.parse_args()
    print(verify(args.root, args.vivado_version))
