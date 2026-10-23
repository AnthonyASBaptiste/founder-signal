"""Allow `python -m founder_signal` to run the CLI."""

from .cli import main

raise SystemExit(main())
