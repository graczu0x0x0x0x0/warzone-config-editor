"""Entry point: ``python -m wzce`` / ``wzce``.

Until the GUI exists (stage 3) this prints a read-only report of the settings
files found on this machine - handy to check discovery and parsing on real data.
"""

from __future__ import annotations

import sys

from .core import WzceError, discover, is_game_running


def main() -> int:
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


if __name__ == "__main__":
    sys.exit(main())
