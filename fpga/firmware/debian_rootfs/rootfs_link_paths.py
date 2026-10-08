"""Normalize only explicitly identified build-root prefixes before archiving."""
import os
from pathlib import Path, PurePosixPath


def guest_target(value, origins):
    if not value.startswith('/'):
        return value
    for origin in origins:
        if value == origin or value.startswith(origin + '/'):
            value = '/' + value[len(origin):].lstrip('/')
            break
    parts = []
    for part in PurePosixPath(value).parts:
        if part in ('/', '.', ''):
            continue
        if part == '..':
            if not parts:
                raise RuntimeError('Rootfs link escapes the guest root')
            parts.pop()
        else:
            parts.append(part)
    return value


def normalize_build_links(root, origins):
    root = Path(root)
    prefixes = tuple(str(Path(p).absolute()).rstrip('/') for p in origins)
    if not prefixes or any(p in ('', '/') for p in prefixes):
        raise RuntimeError('Explicit non-root build origin prefixes are required')
    changed = []
    for path in sorted(root.rglob('*')):
        if not path.is_symlink():
            continue
        original = os.readlink(path)
        replacement = guest_target(original, prefixes)
        if not replacement.startswith('/'):
            position = list(path.parent.relative_to(root).parts)
            for part in PurePosixPath(replacement).parts:
                if part == '..':
                    if not position:
                        raise RuntimeError('Relative rootfs link escapes the guest root')
                    position.pop()
                elif part != '.':
                    position.append(part)
        # Do not reinterpret arbitrary absolute paths as a build-root path.
        if replacement.startswith('/workspace/'):
            raise RuntimeError('Unknown build-host symlink target: ' + str(path))
        if replacement == original:
            continue
        metadata = path.lstat()
        path.unlink()
        path.symlink_to(replacement)
        os.chown(path, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
        changed.append({'path':path.relative_to(root).as_posix(),
                        'before':original, 'after':replacement})
    # update-alternatives state is guest-path data, never a shell command.
    states = []
    for path in sorted((root / 'var/lib/dpkg/alternatives').glob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        original = path.read_text()
        lines = original.splitlines(keepends=True)
        result = []
        for line in lines:
            raw = line.removesuffix('\n')
            fixed = guest_target(raw, prefixes) if raw.startswith('/') else raw
            if fixed.startswith('/workspace/'):
                raise RuntimeError('Unknown build-host alternatives path')
            result.append(fixed + ('\n' if line.endswith('\n') else ''))
        replacement = ''.join(result)
        if replacement != original:
            path.write_text(replacement)
            states.append(path.relative_to(root).as_posix())
    return {'links':changed, 'alternatives_state_files':states}
