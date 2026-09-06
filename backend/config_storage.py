"""Keep server configuration independent of the installed Cue PWA."""

import os
import tempfile
from pathlib import Path


def config_path(home: Path) -> Path:
    destination = home / ".config" / "subtitle-maker" / "config.json"
    legacy = home / "Library" / "Application Support" / "Cue" / "config.json"
    if destination.exists() or not legacy.is_file():
        return destination

    # Copy, never move: uninstalling the old app must not remove the new config.
    # Publish only a complete copy, without replacing another process's config.
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(legacy.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink()
    return destination
