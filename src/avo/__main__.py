"""``python -m avo`` — unified engine dispatcher."""

from __future__ import annotations

import sys

from avo.engine_cli import main

raise SystemExit(main(sys.argv[1:]))
