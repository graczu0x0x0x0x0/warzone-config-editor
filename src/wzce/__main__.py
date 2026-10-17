"""Entry point: ``python -m wzce`` / ``wzce``.

* no arguments  -> start the GUI
* ``--report``  -> print a read-only report of the settings files found on this
                   machine (handy to check discovery and parsing on real data)
* ``--smoke-test`` -> build the whole UI headless and exit (used to verify the
                   frozen .exe: bundled data, Qt plugins, imports). Exit code 0 = OK.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import WzceError, discover, is_game_running


def report() -> int:
    locations = discover()
    if not locations:
        print("No Call of Duty settings files found.")
        return 1

    print(f"Game running: {'yes' if is_game_running() else 'no'}")
    for loc in locations:
        fs = loc.fileset
        where = f"account {loc.account_id}" if loc.account_id else "machine"
        print(f"\n[{loc.title_name}] {loc.kind.value} ({where})  {fs.directory / fs.stem}")
        try:
            loaded = fs.load()
        except WzceError as exc:
            print(f"  ERROR: {exc}")
            continue
        doc = loaded.document
        layout = "A/B pair" if fs.is_ab else "single file"
        print(f"  {layout}, read from {loaded.source.name}, {len(doc)} settings")
        print(f"  sections: {', '.join(s or '(none)' for s in doc.sections)}")
        if fs.is_ab:
            if loaded.slots_in_sync:
                print("  slots in sync")
            else:
                diffs = ", ".join(c.setting_id for c in loaded.slot_differences)
                print(f"  slots differ: {diffs}")
        for warning in doc.warnings:
            print(f"  warning: {warning}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="wzce", description="Warzone Config Editor")
    parser.add_argument("--report", action="store_true", help="print a read-only file report")
    parser.add_argument("--smoke-test", action="store_true", help="build the UI headless and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()
    if args.report:
        return report()
    if args.smoke_test:
        from .ui.app import smoke_test

        return smoke_test()
    from .ui.app import run  # imported lazily so --report works without Qt

    return run()


if __name__ == "__main__":
    sys.exit(main())
