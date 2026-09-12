import os
from pathlib import Path, PureWindowsPath


def extended_windows_path(value: str) -> str:
    """Extended Win32 syntax for absolute file arguments, never options."""
    path = PureWindowsPath(value)
    if not path.is_absolute() or value.startswith("\\\\?\\") or len(value) < 240:
        return value
    normalized = str(path)
    if value.endswith(("\\", "/")) and not normalized.endswith("\\"):
        normalized += "\\"
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized[2:]
    return "\\\\?\\" + normalized


def media_path(path: Path) -> str:
    value = str(path.resolve())
    return extended_windows_path(value) if os.name == "nt" else value
