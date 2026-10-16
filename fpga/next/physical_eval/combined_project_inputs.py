"""Verify Vivado's discovered file closure before the actual synth command."""
import argparse
from pathlib import Path
from combined_contract import checked_files, read, require, write


def verify(root, listing, tool_root):
    root, tool_root = Path(root).resolve(), Path(tool_root).resolve()
    seal = read(root/'package-seal.json')
    checked_files(root, seal['files'])
    inputs = []
    for line in Path(listing).read_text().splitlines():
        path = Path(line).resolve(strict=True)
        if path.is_relative_to(root):
            name = path.relative_to(root).as_posix()
            require(name in seal['files'], 'Unsealed project input: '+name)
            inputs.append(dict(path=name, origin='sealed-package'))
        else:
            require(path.is_relative_to(tool_root), 'Project source escapes package/tool installation: '+str(path))
            inputs.append(dict(path=str(path), origin='version-checked-vivado-installation-bytes-not-pinned'))
    require(bool(inputs), 'Vivado discovered no project inputs')
    write(Path(listing).with_suffix('.verified.json'), dict(status='PASS_DISCOVERED_PROJECT_INPUT_PATHS_ONLY', inputs=inputs))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('listing', type=Path)
    parser.add_argument('tool_root', type=Path)
    args = parser.parse_args()
    verify(args.root, args.listing, args.tool_root)
