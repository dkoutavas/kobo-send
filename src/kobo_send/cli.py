"""kobo-send: send EPUB and PDF books to a Kobo over USB."""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import books, config, device, inbox


class Fatal(Exception):
    pass


class Failed(Exception):
    pass


@dataclass(frozen=True)
class Job:
    plan: books.Plan
    local: Path | None  # a file from the command line; None means plan.source_name in the inbox


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = config.load()
    except (ValueError, OSError) as e:
        print(f"kobo-send: {e}", file=sys.stderr)
        return 1
    args = _parser(cfg).parse_args(argv)
    try:
        return _run(args, cfg)
    except (Fatal, device.DeviceError, inbox.InboxError) as e:
        print(f"kobo-send: {e}", file=sys.stderr)
        return 1


def _parser(cfg: config.Config) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kobo-send",
        description="Convert EPUB to KEPUB (kepubify) and PDF to a screen-fitted PDF (k2pdfopt) "
        "or a reflowable KEPUB (marker), then copy the books to the Kobo, check them and eject it.",
        epilog=f"Settings: {config.default_path()}",
    )
    p.add_argument(
        "files",
        nargs="*",
        type=Path,
        help=f"books to send. With none, send every EPUB and PDF in {cfg.inbox} "
        f"and move each sent file to {cfg.sent}/",
    )
    p.add_argument(
        "-d", "--subdir", default=cfg.subdir,
        help="folder under Books/ on the Kobo (default: %(default)s)",
    )
    p.add_argument(
        "-k", "--keep", action="store_true",
        help="keep the Kobo mounted afterwards (default: unmount and power it off)",
    )
    p.add_argument(
        "--pdf", choices=config.PDF_MODES, default=cfg.pdf_mode,
        help="fit: k2pdfopt fits each page to the screen and keeps the layout. "
        "reflow: marker makes reflowable text and rebuilds code listings (default: %(default)s)",
    )
    return p


def _run(args: argparse.Namespace, cfg: config.Config) -> int:
    cfg = dataclasses.replace(cfg, subdir=args.subdir, pdf_mode=args.pdf)
    jobs, ok = _gather(args.files, cfg)
    if not jobs:
        print("nothing to send" if args.files else f"inbox empty: {cfg.inbox}")
        return 0 if ok else 1

    block = device.find(cfg.label)
    if block is None:
        raise Fatal(f"no filesystem labelled {cfg.label}. Plug in the Kobo and tap Connect on it.")
    mnt = device.mount(block)
    if not (mnt / ".kobo").is_dir():
        raise Fatal(f"{mnt} has no .kobo directory, so it is not a Kobo")
    dest = mnt / "Books" / cfg.subdir
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="kobo-send-") as tmp:
        work = Path(tmp)
        for job in jobs:
            ok &= _send(job, dest, work, cfg)

    if not ok:
        print(f"kobo-send: errors above, leaving {mnt} mounted", file=sys.stderr)
        return 1
    if not args.keep:
        device.eject(block)
        print("ejected. Safe to unplug.")
    return 0


def _gather(files: list[Path], cfg: config.Config) -> tuple[list[Job], bool]:
    """Return the jobs to run, and False if a command-line file had to be skipped."""
    if not files:
        plans = (books.plan(name, cfg.pdf_mode) for name in inbox.list_files(cfg.inbox))
        return [Job(p, None) for p in plans if p], True
    jobs, ok = [], True
    for f in files:
        p = books.plan(f.name, cfg.pdf_mode)
        if p is None or not f.is_file():
            print(f"SKIP {f}: {'not found' if p else 'not an EPUB or PDF'}", file=sys.stderr)
            ok = False
            continue
        jobs.append(Job(p, f))
    return jobs, ok


def _send(job: Job, dest: Path, work: Path, cfg: config.Config) -> bool:
    p = job.plan
    print(f"...  {p.source_name}", flush=True)
    start = time.monotonic()
    try:
        _send_one(job, dest, work, cfg)
    except (Failed, books.ConversionError, inbox.InboxError, OSError) as e:
        print(f"FAIL {p.source_name}: {e}", file=sys.stderr)
        return False
    print(f"OK   Books/{cfg.subdir}/{p.target} ({time.monotonic() - start:.0f}s)")
    return True


def _send_one(job: Job, dest: Path, work: Path, cfg: config.Config) -> None:
    p = job.plan
    src = work / "in" / p.source_name
    out = work / "out" / p.target
    src.parent.mkdir(exist_ok=True)
    out.parent.mkdir(exist_ok=True)
    try:
        # Convert from local disk: k2pdfopt reads a network or FUSE path several times slower.
        if job.local:
            shutil.copyfile(job.local, src)
        else:
            inbox.fetch(cfg.inbox, p.source_name, src)
        books.convert(src, out, cfg)
    finally:
        src.unlink(missing_ok=True)

    target = dest / p.target
    shutil.copyfile(out, target)
    with target.open("rb+") as f:
        os.fsync(f.fileno())
    if books.sha256(out) != books.sha256(target) or not books.opens(target):
        raise Failed("checksum or format check failed on the Kobo")
    out.unlink()

    old = dest / p.other
    if old.exists():
        old.unlink()
        print(f"     removed the old {p.other}")
    if job.local is None:
        inbox.archive(cfg.inbox, p.source_name, cfg.sent)
