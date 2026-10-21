"""Explicit installed-XSIM invocation, including Windows cmd/batch boundaries."""
import os
from pathlib import Path
import shutil


def resolve_tool(name, tool_dir=None, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    # Vivado/bin can contain both a Unix launcher and Windows .bat. Never select
    # the extensionless shell script on Windows (CreateProcess error 193).
    suffixes = ('.bat', '.cmd', '.exe') if windows else ('',)
    if tool_dir:
        for suffix in suffixes:
            candidate = Path(tool_dir) / (name + suffix)
            if candidate.is_file():
                return str(candidate.resolve())
        raise RuntimeError('installed XSIM tool not found in selected directory: ' + name)
    for suffix in suffixes:
        candidate = shutil.which(name + suffix)
        if candidate:
            return candidate
    raise RuntimeError('installed XSIM tool not found: ' + name)


def invocation(arguments, windows=None, comspec=None):
    windows = os.name == 'nt' if windows is None else windows
    arguments = [str(a) for a in arguments]
    if not windows or Path(arguments[0]).suffix.lower() not in ('.bat', '.cmd'):
        return arguments
    # cmd/batch splits an unquoted NAME=VALUE into separate arguments. Python's
    # list2cmdline does not quote '=' alone; explicitly quote EVERY batch token.
    # Pass a raw command string to CreateProcess, not a list that gets re-escaped.
    if any('"' in a or '\n' in a or '\r' in a for a in arguments):
        raise ValueError('unsupported quote/newline in Windows XSIM argument')
    command = ' '.join('"' + a + '"' for a in arguments)
    interpreter = comspec or os.environ.get('COMSPEC', 'cmd.exe')
    return '"' + interpreter + '" /d /s /c "' + command + '"'
