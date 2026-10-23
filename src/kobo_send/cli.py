"""kobo-send: send EPUB and PDF books to a Kobo over USB."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import books, device, inbox

INBOX = "gdrive:Books"  # rclone remote folder to send from
SENT = "Sent"  # subfolder of the inbox that receives sent files
SUBDIR = "Technical"  # default folder under Books/ on the Kobo
LABEL = "KOBOeReader"  # filesystem label of the Kobo
PDF_MODE = "fit"  # default PDF mode: "fit" (k2pdfopt) or "reflow" (marker, see the README)


class Fatal(Exception):
    pass


class Failed(Exception):
    pass


@dataclass(frozen=True)
class Job:
    plan: books.Plan
    local: Path | None  # a file from the command line; None means plan.source_name in the inbox


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.pdf not in books.PDF_MODES:  # argparse does not check a default against choices
        parser.error(f"PDF_MODE in cli.py must be one of: {', '.join(books.PDF_MODES)}")
    try:
        return _run(args)
    except (Fatal, device.DeviceError, inbox.InboxError) as e:
        print(f"kobo-send: {e}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kobo-send",
        description="Convert EPUB to KEPUB (kepubify) and PDF to a screen-fitted PDF (k2pdfopt) "
        "or a reflowable KEPUB (marker), then copy the books to the Kobo, check them and unmount it.",
    )
    p.add_argument(
        "files",
        nargs="*",
        type=Path,
        help=f"books to send. With none, send every EPUB and PDF in {INBOX} and move each sent file to {SENT}/",
    )
    p.add_argument(
        "-d", "--subdir", default=SUBDIR,
        help="folder under Books/ on the Kobo (default: %(default)s)",
    )
    p.add_argument(
        "-k", "--keep", action="store_true",
        help="keep the Kobo mounted afterwards (default: unmount it)",
    )
    p.add_argument(
        "--pdf", choices=books.PDF_MODES, default=PDF_MODE,
        help="fit: k2pdfopt fits each page to the screen and keeps the layout. "
        "reflow: marker makes reflowable text and rebuilds code listings (default: %(default)s)",
    )
    return p


def _run(args: argparse.Namespace) -> int:
    jobs, ok = _gather(args.files, args.pdf)
    if not jobs:
        print("nothing to send" if args.files else f"inbox empty: {INBOX}")
        return 0 if ok else 1

    block = device.find(LABEL)
    if block is None:
        raise Fatal(f"no filesystem labelled {LABEL}. Plug in the Kobo and tap Connect on it.")
    mnt = device.mount(block)
    if not (mnt / ".kobo").is_dir():
        raise Fatal(f"{mnt} has no .kobo directory, so it is not a Kobo")
    dest = mnt / "Books" / args.subdir
    dest.mkdir(parents=True, exist_ok=True)
    print(f"sending to {dest}")

    with tempfile.TemporaryDirectory(prefix="kobo-send-") as tmp:
        work = Path(tmp)
        (work / "in").mkdir()
        (work / "out").mkdir()
        for job in jobs:
            ok &= _send(job, dest, work, args.pdf)

    if not ok:
        print(f"kobo-send: errors above, leaving {mnt} mounted", file=sys.stderr)
        return 1
    if not args.keep:
        device.unmount(block)
        print("unmounted. Unplug the Kobo now. It imports the new books after you unplug it.")
    return 0


def _gather(files: list[Path], pdf_mode: str) -> tuple[list[Job], bool]:
    """Return the jobs to run, and False if a command-line file had to be skipped."""
    if not files:
        plans = (books.plan(name, pdf_mode) for name in inbox.list_files(INBOX))
        return [Job(p, None) for p in plans if p], True
    jobs, ok = [], True
    for f in files:
        p = books.plan(f.name, pdf_mode)
        if p is None or not f.is_file():
            print(f"SKIP {f}: {'not found' if p else 'not an EPUB or PDF'}", file=sys.stderr)
            ok = False
            continue
        jobs.append(Job(p, f))
    return jobs, ok


def _send(job: Job, dest: Path, work: Path, pdf_mode: str) -> bool:
    p = job.plan
    print(f"...  {p.source_name}", flush=True)
    start = time.monotonic()
    try:
        _send_one(job, dest, work, pdf_mode)
    except (Failed, books.ConversionError, inbox.InboxError, OSError) as e:
        print(f"FAIL {p.source_name}: {e}", file=sys.stderr)
        return False
    print(f"OK   {p.target} ({time.monotonic() - start:.0f}s)")
    return True


def _send_one(job: Job, dest: Path, work: Path, pdf_mode: str) -> None:
    p = job.plan
    src = work / "in" / p.source_name
    out = work / "out" / p.target
    try:
        # Convert from local disk: k2pdfopt reads a network or FUSE path several times slower.
        if job.local:
            shutil.copyfile(job.local, src)
        else:
            inbox.fetch(INBOX, p.source_name, src)
        books.convert(src, out, pdf_mode)
    finally:
        src.unlink(missing_ok=True)

    target = dest / p.target
    shutil.copyfile(out, target)
    with target.open("rb+") as f:
        os.fsync(f.fileno())
    if books.sha256(out) != books.sha256(target) or not books.opens(target):
        target.unlink()  # a bad file on the Kobo is worse than no file
        raise Failed("checksum or format check failed on the Kobo")
    out.unlink()

    old = dest / p.other
    if old.exists():
        old.unlink()
        print(f"     removed the old {p.other}")
    if job.local is None:
        inbox.archive(INBOX, p.source_name, SENT)
