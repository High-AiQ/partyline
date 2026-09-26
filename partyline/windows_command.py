"""Resolve native programs and npm's Node shim without interpreting shell input."""

from pathlib import Path
import re
import shutil


def resolve(argv, environment):
    if not argv or any('\0' in arg for arg in argv):
        raise ValueError('expected an executable and arguments without NUL characters')
    search = next((value for key, value in environment.items() if key.upper() == 'PATH'), '')
    executable = shutil.which(argv[0], path=search)
    if not executable:
        raise OSError(f'Windows executable was not found: {argv[0]}')
    path = Path(executable)
    if path.suffix.lower() in {'.exe', '.com'}:
        return [str(path), *argv[1:]]
    if path.suffix.lower() == '.cmd':
        # npm/cmd-shim's standard Node wrapper. Do not pass user arguments to
        # cmd.exe: %, &, quotes, and newlines must retain their literal values.
        with path.open(encoding='utf-8-sig') as source:
            content = source.read(65537)
        match = re.search(r'"%_prog%"\s+"%dp0%\\([^"\r\n%]+)" %\*\s*$', content)
        if (len(content) <= 65536 and match and 'SET "_prog=node"' in content
                and 'SET "_prog=%dp0%\\node.exe"' in content):
            script = path.parent.joinpath(*match[1].split('\\')).resolve()
            if script.is_file():
                local = path.parent / 'node.exe'
                node = str(local) if local.is_file() else shutil.which('node.exe', path=search)
                if node:
                    return [node, str(script), *argv[1:]]
    raise OSError('ConPTY requires a native executable or npm Node shim; '
                  'invoke other scripts through their interpreter')
