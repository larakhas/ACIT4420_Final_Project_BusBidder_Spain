import sys

from bbspain.cli import main

if __name__ == "__main__":
    # Windows consoles often default to a legacy code page, which garbles names like "Cádiz".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
