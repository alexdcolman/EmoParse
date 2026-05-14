"""Puente para soportar `python -m emoparse`. Delega al CLI."""

from emoparse.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
