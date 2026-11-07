"""Console entry point; optional capture imports remain lazy."""
import argparse
import asyncio
import json
import socket
from pathlib import Path
from urllib.error import URLError

from .config import config_path, load_config, pair

UVX_PREFIX = "uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper"
CHECKOUT_PREFIX = "uv run --extra helper partyline-helper"


def run_hint():
    # How this helper was launched (uvx or a checkout) cannot be detected reliably, so show both.
    return (f"Paired. Now start the helper on this computer and keep that terminal open:\n"
            f"  {UVX_PREFIX} run          (if you used uvx)\n"
            f"  {CHECKOUT_PREFIX} run     (from a partyline checkout)\n"
            "Answer y to each share prompt.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="partyline-helper")
    commands = parser.add_subparsers(dest="command", required=True)
    pairing = commands.add_parser("pair")
    pairing.add_argument("server")
    pairing.add_argument("code")
    pairing.add_argument("--name", default=socket.gethostname())
    run = commands.add_parser("run")
    run.add_argument("--yes", action="store_true",
                     help="Auto-accept every share request (never grants agent control)")
    run.add_argument("--log", type=Path, help="Append output to this file (used at login)")
    run.add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--no-border", action="store_true",
                     help="Do not draw the capture-zone border while sharing")
    run.add_argument("--allow-control-without-prompt", action="store_true",
                     help="DANGEROUS: grant every agent control request without asking")
    commands.add_parser("unpair")
    commands.add_parser("install", help="Register partyline:// links and start at login (once)")
    commands.add_parser("uninstall", help="Remove what install registered (keeps pairing)")
    opener = commands.add_parser("open", help="Handle a partyline:// link (run by the OS)")
    opener.add_argument("url")
    commands.add_parser("monitors")
    args = parser.parse_args(argv)
    desktop = border = None
    try:
        if args.command == "pair":
            pair(args.server, args.code, args.name)
            print(run_hint())
        elif args.command == "unpair":
            config_path().unlink(missing_ok=True)
            print("Local credential removed. Revoke the device in Partyline to invalidate its token.")
        elif args.command in ("install", "uninstall", "open"):
            from .links import dispatch
            print(dispatch(args))
        else:
            if args.command == "run":
                from .links import claim_run
                if not claim_run(args.log, args.wait):
                    return print("The helper is already running.")
            from .desktop import Desktop
            desktop = Desktop()
            if args.command == "monitors":
                print(json.dumps(desktop.monitors(), indent=2))
            else:
                from .client import serve
                from .consent_dialog import auto_dialog
                from .terminal import Terminal
                if args.yes:
                    print("WARNING: --yes auto-accepts ALL screen share requests without asking locally.")
                if not args.no_border:
                    from .border import CaptureBorder
                    border = CaptureBorder(scale=desktop.scale)
                if args.allow_control_without_prompt:
                    print("WARNING: --allow-control-without-prompt LETS AGENTS DRIVE THIS MOUSE AND "
                          "KEYBOARD WITHOUT ASKING. Move the mouse or press a key to take control back.")
                asyncio.run(serve(load_config(), desktop, Terminal(dialog=auto_dialog()), args.yes,
                                  border=border, allow_control=args.allow_control_without_prompt))
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
        if border:
            border.close()
        if desktop:
            desktop.close()
