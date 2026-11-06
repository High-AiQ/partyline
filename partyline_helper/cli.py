"""Console entry point; optional capture imports remain lazy."""
import argparse
import asyncio
import json
import socket
from urllib.error import URLError

from .config import config_path, load_config, pair


def main(argv=None):
    parser = argparse.ArgumentParser(prog="partyline-helper")
    commands = parser.add_subparsers(dest="command", required=True)
    pairing = commands.add_parser("pair")
    pairing.add_argument("server")
    pairing.add_argument("code")
    pairing.add_argument("--name", default=socket.gethostname())
    run = commands.add_parser("run")
    run.add_argument("--yes", action="store_true",
                     help="Auto-accept every request (unsafe on shared servers)")
    commands.add_parser("unpair")
    commands.add_parser("monitors")
    args = parser.parse_args(argv)
    desktop = None
    try:
        if args.command == "pair":
            pair(args.server, args.code, args.name)
            print("Paired. Run partyline-helper run to connect.")
        elif args.command == "unpair":
            config_path().unlink(missing_ok=True)
            print("Local credential removed. Revoke the device in Partyline to invalidate its token.")
        else:
            from .desktop import Desktop
            desktop = Desktop()
            if args.command == "monitors":
                print(json.dumps(desktop.monitors(), indent=2))
            else:
                from .client import serve
                from .terminal import Terminal
                if args.yes:
                    print("WARNING: --yes auto-accepts ALL screen share requests without asking locally.")
                asyncio.run(serve(load_config(), desktop, Terminal(), args.yes))
    except KeyboardInterrupt:
        print("Helper stopped.")
    except ImportError:
        print("Install the helper extra with: uv sync --extra helper. Also check desktop/display access.")
        raise SystemExit(1) from None
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, URLError):
        # HTTP exceptions may contain credentials supplied by an untrusted endpoint.
        print("Helper could not start/pair. Check server, pairing code, config and desktop permissions.")
        raise SystemExit(1) from None
    finally:
        if desktop:
            desktop.close()
