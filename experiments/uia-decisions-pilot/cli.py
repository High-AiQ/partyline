"""Isolated entrypoint: add only this trusted source directory, never the artifact."""
import sys
from pathlib import Path


def main():
    if not sys.flags.isolated:
        raise SystemExit('Run with python -I')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run import main as evaluate
    evaluate()


if __name__ == '__main__':
    main()
