"""Server-side process facts and the attachment's automatically transferred runtime."""
import json
import os
import subprocess
import sys


def listing():
    """Read state, birth time and argv in one bounded Linux/macOS/Windows listing."""
    windows = sys.platform.startswith('win')
    command = (['powershell', '-NoProfile', '-Command',
                'Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine,CreationDate '
                '| ConvertTo-Json -Compress'] if windows else
               ['ps', '-axo', 'pid=,pgid=,stat=,lstart=,args='])
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False,
                              env={**os.environ, 'LC_ALL': 'C'})
        if done.returncode:
            return {}
        if windows:
            rows = json.loads(done.stdout)
            rows = rows if isinstance(rows, list) else [rows]
            return {int(row['ProcessId']): {'state': 'running', 'started': row['CreationDate'],
                    'command': row['CommandLine'], 'pgid': None} for row in rows}
        found = {}
        for line in done.stdout.splitlines():
            fields = line.split(None, 8)
            if len(fields) == 9:
                found[int(fields[0])] = {'pgid': int(fields[1]), 'state': fields[2],
                    'started': ' '.join(fields[3:8]), 'command': fields[8]}
        return found
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {}


def actionable(fact):
    """Missing batch facts are uncertain; only positive death evidence excludes a PID."""
    state, command = fact.get('state') or '', fact.get('command') or ''
    return not (state.startswith(('Z', 'X')) or '<defunct>' in command)
