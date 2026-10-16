# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``python -m sankey_studio`` runs the same entry point as the ``sankey-studio`` script."""

from sankey_studio.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
