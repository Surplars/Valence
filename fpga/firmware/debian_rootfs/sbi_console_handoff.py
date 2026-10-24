"""Pinned OpenSBI late-DT UART ownership fixup; never disable initial console DT."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REVISION = 'cbf9f6734dd85a982c63e3cb5db7ffe09da839ca'
HEADER = HERE / 'valence_sbi_console_handoff.h'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise RuntimeError('OpenSBI source revision mismatch')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Pinned OpenSBI source must be clean')
    original = (source/'platform/generic/platform.c').read_text()
    include = '#include <libfdt.h>\n'
    anchor = """	fdt_pack(fdt);
	fdt_open_into(fdt, fdt, fdt_totalsize(fdt) +
		      CONFIG_PLATFORM_GENERIC_FDT_EMPTY_SPACE * 1024);

	return 0;
"""
    if original.count(include) != 1 or original.count(anchor) != 1:
        raise RuntimeError('Pinned OpenSBI handoff hook drift')
    patched = original.replace(include, include + '#include "valence_sbi_console_handoff.h"\n')
    patched = patched.replace(anchor, """	/* Preserve the generic reserved DT capacity before growing status. */
	{
		int rc = fdt_pack(fdt);
		if (rc)
			return rc;
		rc = fdt_open_into(fdt, fdt, fdt_totalsize(fdt) +
			CONFIG_PLATFORM_GENERIC_FDT_EMPTY_SPACE * 1024);
		if (rc)
			return rc;
		/* SBI console callbacks are already live; Linux alone loses UART. */
		return valence_sbi_console_handoff(fdt);
	}
""")
    if not output.exists():
        shutil.copytree(source, output, ignore=shutil.ignore_patterns('.git', 'build'))
        (output/'platform/generic/platform.c').write_text(patched)
        shutil.copy2(HEADER, output/'platform/generic'/HEADER.name)
    if (output/'platform/generic/platform.c').read_text() != patched or digest(output/'platform/generic'/HEADER.name) != digest(HEADER):
        raise RuntimeError('Previously patched OpenSBI source changed')
    tracked = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode().split('\0')
    expected = {name: digest(source/name) for name in tracked if name}
    expected['platform/generic/platform.c'] = hashlib.sha256(patched.encode()).hexdigest()
    expected['platform/generic/' + HEADER.name] = digest(HEADER)
    actual = {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file()}
    if actual != expected:
        raise RuntimeError('Patched OpenSBI source inventory drift, use a fresh output')
    return dict(original_revision=REVISION, source_file_count=len(expected),
                source_inventory_sha256=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest(),
                original_platform_sha256=digest(source/'platform/generic/platform.c'),
                patched_platform_sha256=digest(output/'platform/generic/platform.c'),
                handoff_header_sha256=digest(HEADER), initial_uart_enabled=True,
                handoff_uart_disabled=True, no_uart_mmio_writes_in_fixup=True)
