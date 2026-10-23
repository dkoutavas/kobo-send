"""Book naming, conversion and file checks. Nothing here touches the Kobo or the inbox."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

PDF_MODES = ("fit", "reflow")
K2PDFOPT_DEVICE = "koc"  # Kobo Clara HD profile: same 1072 px, 300 dpi panel as the Clara BW
MARKER_PYTHON = Path.home() / ".local/share/kobo-send/marker/bin/python"  # Python of the marker environment

# The directory that holds the kobo_send package. The reflow subprocess imports it from here.
SRC_DIR = Path(__file__).resolve().parent.parent

# Longest suffix first, so "x.kepub.epub" does not match as ".epub".
SUFFIXES = (".kepub.epub", ".epub", ".pdf")

# Download sites put their name in front and every ISBN of the book at the end.
_SITE_PREFIX = re.compile(r"^example\.pub_")
_ISBN_TAIL = re.compile(r"(-\d{13}|-\d{9}[\dX])+$")

K2PDFOPT_ARGS = (
    "-ui-", "-a-", "-x", "-y",  # no menu, no colour, exit when done, overwrite
    "-ocr-",                    # the source already has a text layer
    "-wrap-", "-col", "1",      # fit the width without reflow, so code listings keep their layout
    "-n",                       # keep the vector text: sharper, smaller and searchable
)


class ConversionError(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    """What one source file becomes on the Kobo."""

    source_name: str
    name: str  # cleaned file name without the extension
    ext: str  # "kepub.epub" or "pdf"

    @property
    def target(self) -> str:
        return f"{self.name}.{self.ext}"

    @property
    def other(self) -> str:
        """The same book in the other format. Sending this book replaces it."""
        return f"{self.name}.{'kepub.epub' if self.ext == 'pdf' else 'pdf'}"


def plan(source_name: str, pdf_mode: str = "fit") -> Plan | None:
    """Return the plan for a file name, or None if the file is not an EPUB or a PDF."""
    lower = source_name.lower()
    for suffix in SUFFIXES:
        if lower.endswith(suffix):
            ext = "pdf" if suffix == ".pdf" and pdf_mode == "fit" else "kepub.epub"
            return Plan(source_name, clean_name(source_name[: -len(suffix)]), ext)
    return None


def clean_name(stem: str) -> str:
    return _ISBN_TAIL.sub("", _SITE_PREFIX.sub("", stem))


def convert(src: Path, out: Path, pdf_mode: str) -> None:
    """Write src to out in the format the Kobo gets. Raise ConversionError on failure."""
    lower = src.name.lower()
    if lower.endswith(".kepub.epub"):
        shutil.copyfile(src, out)
        return
    if lower.endswith(".pdf") and pdf_mode == "reflow":
        _reflow(src, out)
        return
    if lower.endswith(".pdf"):
        _run(["k2pdfopt", *K2PDFOPT_ARGS, "-dev", K2PDFOPT_DEVICE, "-o", str(out), str(src)], out)
    else:
        _run(_kepubify(src, out), out)


def _reflow(src: Path, out: Path) -> None:
    """PDF to EPUB with marker in its own environment, then EPUB to KEPUB with kepubify."""
    if not MARKER_PYTHON.is_file():
        raise ConversionError(f"marker environment not found: {MARKER_PYTHON}. See the README, section Reflow mode.")
    epub = out.with_name(out.name.removesuffix(".kepub.epub") + ".epub")
    try:
        cmd = [str(MARKER_PYTHON), "-m", "kobo_send.reflow", str(src), str(epub)]
        _run(cmd, epub, label="reflow", env={"PYTHONPATH": str(SRC_DIR)})
        _run(_kepubify(epub, out), out)
    finally:
        epub.unlink(missing_ok=True)


def _kepubify(src: Path, out: Path) -> list[str]:
    # kepubify treats -o as a file path only for one input and an -o path that does not exist.
    return ["kepubify", "-o", str(out), str(src)]


def _run(cmd: list[str], out: Path, label: str | None = None, env: dict[str, str] | None = None) -> None:
    label = label or cmd[0]
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            env={**os.environ, **env} if env else None,
        )
    except FileNotFoundError:
        raise ConversionError(f"{label} is not installed") from None
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
        raise ConversionError(f"{label} failed (exit {result.returncode})\n{tail}")


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def opens(path: Path) -> bool:
    """True if the file opens as its format: a sound zip for KEPUB, a PDF header for PDF."""
    if path.name.lower().endswith(".pdf"):
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None
    except zipfile.BadZipFile:
        return False
