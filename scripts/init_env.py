"""Generate local credentials without overwriting an existing environment file.

This standalone bootstrap script uses only Python's standard library, allowing
make init to run before the project virtual environment has been installed.
It creates credentials for the local services; it does not contact a provider.
"""

import os
from pathlib import Path
import secrets


def main() -> None:
    """Expand the checked-in template into a private, untracked .env file."""
    # Resolve paths relative to this script rather than the caller's directory.
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists():
        # Service databases persist their original credentials. Replacing .env
        # on a later invocation could disconnect the runner from those services.
        print(".env already exists. Existing credentials were preserved.")
        return
    template = (root / ".env.example").read_text(encoding="utf-8")
    # Generate independent random values for separate lines. token_hex(32)
    # produces 64 hexadecimal characters, also suitable for ENCRYPTION_KEY.
    # Prefixes such as pk-lf- remain intact around the replaced marker.
    lines = [line.replace("__GENERATE__", secrets.token_hex(32)) for line in template.splitlines()]
    # O_EXCL prevents a concurrent invocation from overwriting a file created
    # after the exists() check. Mode 0600 restricts the new file to its owner,
    # subject to the filesystem's support for POSIX permission semantics.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    # fdopen wraps and closes the already-created descriptor without reopening
    # the path. The final newline keeps the file convenient for shell tooling.
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    print("Created .env. Local credentials are stored there and are ignored by Git.")


if __name__ == "__main__":
    # Printing the destination is sufficient; never print generated secrets.
    main()
