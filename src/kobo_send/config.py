"""Settings from ~/.config/kobo-send/config.toml. The file and every key in it are optional."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


PDF_MODES = ("fit", "reflow")


@dataclass(frozen=True)
class Config:
    inbox: str = "gdrive:Books"  # rclone remote folder to send from
    sent: str = "Sent"  # subfolder of the inbox that receives sent files
    subdir: str = "Technical"  # folder under Books/ on the Kobo
    label: str = "KOBOeReader"  # filesystem label of the Kobo
    k2pdfopt_device: str = "koc"  # Kobo Clara HD profile: same 1072 px, 300 dpi panel as the Clara BW
    pdf_mode: str = "fit"  # "fit": k2pdfopt fits each page to the screen. "reflow": marker, see the README
    marker_python: str = "~/.local/share/kobo-send/marker/bin/python"  # Python of the marker environment


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "kobo-send" / "config.toml"


def load(path: Path | None = None) -> Config:
    path = path or default_path()
    if not path.is_file():
        return Config()
    data = tomllib.loads(path.read_text())
    unknown = sorted(set(data) - {f.name for f in fields(Config)})
    if unknown:
        raise ValueError(f"{path}: unknown keys: {', '.join(unknown)}")
    bad = sorted(k for k, v in data.items() if not isinstance(v, str))
    if bad:
        raise ValueError(f"{path}: these keys must be strings: {', '.join(bad)}")
    cfg = Config(**data)
    if cfg.pdf_mode not in PDF_MODES:
        raise ValueError(f"{path}: pdf_mode must be one of: {', '.join(PDF_MODES)}")
    return cfg
