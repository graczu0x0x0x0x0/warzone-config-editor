"""PyInstaller entry point (PyInstaller needs a script file, not ``python -m wzce``)."""

import sys

from wzce.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
