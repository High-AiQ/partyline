"""Console entry point; optional capture imports remain lazy."""
import argparse
import asyncio
import json
import socket
from pathlib import Path
from urllib.error import URLError

from .config import config_path, load_config, pair
from . import consent_dialog
from .runtime import fail, guarded, tray_wanted

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
    commands = parser.add_subparsers(dest="command")  # none: same as `start`
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
    run.add_argument("--no-tray", action="store_true",
                     help="No system-tray icon (it is on by default on Windows)")
    run.add_argument("--allow-control-without-prompt", action="store_true",
                     help="DANGEROUS: grant every agent control request without asking")
    commands.add_parser("unpair")
    commands.add_parser("stop", help="Stop the running helper")
    commands.add_parser("start", help="Start the helper in the background (what the Start menu runs)")
    commands.add_parser("version", help="Print the helper version")
    commands.add_parser("selfcheck", help="Check that every module the helper needs is present")
    dialog = commands.add_parser("dialog", help=argparse.SUPPRESS)  # the frozen exe's dialog child process
    dialog.add_argument("request")
    uia = commands.add_parser("uia-snapshot", help=argparse.SUPPRESS)
    uia.add_argument("request")
    picker = commands.add_parser("uia-picker", help=argparse.SUPPRESS)
    picker.add_argument("path")
    commands.add_parser("install", help="Register partyline:// links and start at login (once)")
    commands.add_parser("uninstall", help="Remove what install registered (keeps pairing)")
    opener = commands.add_parser("open", help="Handle a partyline:// link (run by the OS)")
    opener.add_argument("url")
    commands.add_parser("monitors")
    args = parser.parse_args(argv)
    args.command = args.command or "start"
    desktop = border = tray = None
    try:
        if args.command == "pair":
            pair(args.server, args.code, args.name)
            print(run_hint())
        elif args.command == "unpair":
            config_path().unlink(missing_ok=True)
            print("Local credential removed. Revoke the device in Partyline to invalidate its token.")
        elif args.command in ("install", "uninstall", "open", "stop", "start"):
            from .links import dispatch
            print(dispatch(args))
        elif args.command == "version":
            from .version import helper_version
            print(helper_version())
        elif args.command == "selfcheck":
            from .runtime import selfcheck
            problems = selfcheck()
            print("\n".join(problems) or "OK")
            raise SystemExit(1 if problems else 0)
        elif args.command == "dialog":
            from .dialog_proc import main as dialog_main
            raise SystemExit(dialog_main([args.request]))
        elif args.command == "uia-picker":  # pragma: no cover - frozen Windows helper child
            from .uia_picker import main as picker_main
            picker_main(args.path)
        elif args.command == "uia-snapshot":  # pragma: no cover - frozen Windows helper child
            from .uia_process import main as uia_main
            uia_main(args.request)
        else:
            if args.command == "run":
                from .links import claim_run
                if not claim_run(args.log, args.wait):
                    return print("The helper is already running.")
                if args.log and not config_path().exists():
                    return print("Not paired yet; nothing to run.")  # autostart before pairing: stay quiet
            from .desktop import Desktop
            desktop = Desktop()
            if args.command == "monitors":
                print(json.dumps(desktop.monitors(), indent=2))
            else:
                from .client import serve
                from .launch import frozen
                from .status import Status
                from .terminal import Terminal
                status = Status()
                if args.yes:
                    print("WARNING: --yes auto-accepts ALL screen share requests without asking locally.")
                if not args.no_border:
                    from .border import CaptureBorder
                    border = CaptureBorder(scale=desktop.scale)
                if args.allow_control_without_prompt:
                    print("WARNING: --allow-control-without-prompt LETS AGENTS DRIVE THIS MOUSE AND "
                          "KEYBOARD WITHOUT ASKING. Move the mouse or press a key to take control back.")
                if tray_wanted(args.no_tray):
                    from .tray import start_tray
                    tray = start_tray(status)
                background = bool(args.log) or frozen()  # no one can read a prompt in a log
                terminal = Terminal(dialog=consent_dialog.auto_dialog(background), status=status)
                asyncio.run(guarded(serve(load_config(), desktop, terminal, args.yes, border=border,
                                          allow_control=args.allow_control_without_prompt, status=status),
                                    status))
    except KeyboardInterrupt:
        print("Helper stopped.")
    except ImportError:
        fail("Install the helper extra with: uv sync --extra helper. Also check desktop/display access.")
        raise SystemExit(1) from None
    except RuntimeError as exc:
        fail(str(exc))
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, URLError):
        # HTTP exceptions may contain credentials supplied by an untrusted endpoint.
        fail("Helper could not start/pair. Check server, pairing code, config and desktop permissions.")
        raise SystemExit(1) from None
    finally:
        if tray:
            tray.stop()
        if border:
            border.close()
        if desktop:
            desktop.close()
