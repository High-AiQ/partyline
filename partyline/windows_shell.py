"""Encode Python hook scripts for native Windows shells without interpolation."""

import base64
import sys


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def python_command(script):
    expression = "exec(bytes.fromhex('" + script.encode().hex() + "'))"
    command = f'& {quote(sys.executable)} -c "{expression}"; exit $LASTEXITCODE'
    encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
    return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded
