"""``python -m sankey_studio`` runs the same entry point as the ``sankey-studio`` script."""

from sankey_studio.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
