# kobo-send

Send EPUB and PDF books to a Kobo e-reader over USB.

- EPUB files are converted to KEPUB with kepubify. KEPUB is the native Kobo format.
- PDF files are fitted to the Kobo screen with k2pdfopt (fit mode), or converted to reflowable KEPUB with marker (reflow mode). In both modes, code listings keep their layout.
- Each book is checked on the Kobo after the copy (SHA-256 and a format check).
- A book replaces the other format of the same name on the Kobo. For example, `X.pdf` replaces `X.kepub.epub`.
- At the end, the Kobo is unmounted and powered off, so it is safe to unplug.

With no arguments, `kobo-send` sends every EPUB and PDF in an inbox folder on Google Drive. Each sent file moves to the `Sent` subfolder of the inbox, so the next run skips it.

## Requirements

- Linux with a desktop session. udisks2 lets the user of the active local session mount the Kobo without root. Over SSH, mount and eject fail with "Not authorized".
- Python 3.11 or later. The tool uses the standard library only.
- [kepubify](https://github.com/pgaskin/kepubify/releases) v4.0.4, `kepubify-linux-64bit`.
- [k2pdfopt](https://www.willus.com/k2pdfopt/download/) v2.55, Linux 64-bit. The download page has a captcha, so use a browser. Use v2.55, not v2.54: v2.54 drops the PDF bookmarks, and the Kobo uses them as the table of contents.
- [rclone](https://rclone.org/) with a Google Drive remote, for the inbox.

Known SHA-256 values of the binaries:

| Binary | SHA-256 |
|---|---|
| kepubify v4.0.4 linux-64bit | `37d7628d26c5c906f607f24b36f781f306075e7073a6fe7820a751bb60431fc5` |
| k2pdfopt v2.55 linux x64 | `2abf6613aac1a65c0ba468a9055f6bda7d6ba7ad6b98a2754a677609e67ec552` |

The k2pdfopt value is published by willus.com. kepubify does not publish checksums. Its value comes from the copy in use.

## Install

```bash
git clone git@github.com:dkoutavas/kobo-send.git ~/dev/kobo-send
ln -s ~/dev/kobo-send/kobo-send ~/.local/bin/kobo-send
install -m755 kepubify-linux-64bit ~/.local/bin/kepubify
install -m755 k2pdfopt ~/.local/bin/k2pdfopt
```

## Configure

There is no settings file. The defaults are constants at the top of two files. Edit them to change a default:

| Constant | File | Default |
|---|---|---|
| `INBOX`, `SENT` | `src/kobo_send/cli.py` | `gdrive:Books`, `Sent` |
| `SUBDIR` (or `-d`) | `src/kobo_send/cli.py` | `Technical` |
| `LABEL` | `src/kobo_send/cli.py` | `KOBOeReader` |
| `PDF_MODE` (or `--pdf`) | `src/kobo_send/cli.py` | `fit` |
| `K2PDFOPT_DEVICE` | `src/kobo_send/books.py` | `koc` (Kobo Clara HD profile: same 1072 px, 300 dpi panel as the Clara BW) |
| `MARKER_PYTHON` | `src/kobo_send/books.py` | `~/.local/share/kobo-send/marker/bin/python` |

For another Kobo model, run `k2pdfopt -ui- -dev ?` to list the device profiles.

## Use

1. Connect the Kobo with USB and tap **Connect** on its screen.
2. Run one of these commands:

```bash
kobo-send                      # send the inbox
kobo-send book.epub notes.pdf  # send these files. The inbox is not changed.
kobo-send -d Fiction book.epub # send to Books/Fiction/ on the Kobo
kobo-send -k book.epub         # keep the Kobo mounted afterwards
```

If a book fails, the tool continues with the next book. At the end, it keeps the Kobo mounted so that you can examine it. A failed inbox file stays in the inbox.

## PDF handling

A PDF has fixed page positions, not a text flow. kobo-send has two PDF modes. Select one with `--pdf`. `PDF_MODE` in `src/kobo_send/cli.py` sets the default.

| Mode | Output on the Kobo | Font size can change | Needs |
|---|---|---|---|
| `fit` (default) | PDF, each page fitted to the screen | no | k2pdfopt |
| `reflow` | KEPUB with reflowable text | yes | the marker environment |

### Fit mode

kobo-send uses k2pdfopt with `-wrap- -col 1 -n`. This fits each page region to the screen width without reflow, and keeps the vector text. The page layout stays correct. k2pdfopt takes about 0.2 to 0.5 seconds for each source page.

### Reflow mode

Reflow mode makes a reflowable book from a PDF and keeps the code listings correct:

1. marker 2.0 (fast mode, OCR off) reads the PDF text layer and finds the layout: paragraphs, headings, tables, figures and captions.
2. marker labels each line of a code listing as a separate paragraph, so the indentation is lost. kobo-send finds the lines in a fixed-pitch font with pdftext. It places each glyph at its column and writes the listing as preformatted text. This restores the indentation and the column alignment, for example in command output tables.
3. Prose that marker merged into a listing, such as a margin note, becomes a separate note.
4. A listing caption moves in front of its listing.
5. The PDF bookmarks give the chapters and the table of contents. The book is split at the deepest bookmark level that gives at most 100 chapters. Every bookmark becomes a table of contents entry with its own target: the heading that the bookmark names, or else the top of its page. A PDF without bookmarks is split at its level 1 headings. The first page of the PDF becomes the cover.
6. Links are removed and their text is kept. The link areas of a PDF overlap the body text, so marker puts links on unrelated words.
7. kepubify converts the EPUB to KEPUB.

Set up the marker environment once. It needs about 6 GB:

```bash
python3.13 -m venv ~/.local/share/kobo-send/marker
~/.local/share/kobo-send/marker/bin/pip install marker-pdf==2.0.0
```

The first run downloads the marker layout models. A GPU makes marker faster, but it is not necessary. Fast mode with OCR off does not start the marker inference server.

Limits:

- The PDF must have a text layer. A scanned PDF fails with an error. Use fit mode for it.
- Mathematical equations and complex tables can be imperfect.
- The marker code is Apache-2.0. The marker model weights have a modified OpenRAIL-M license: personal use is free.

Other approaches that were tested and rejected:

- Calibre (`ebook-convert`) PDF to EPUB splits watermarks into one paragraph per word and mixes margin notes into code.
- k2pdfopt with reflow (`-wrap`) also mixes margin notes into code and breaks tables.
- marker balanced mode (a vision language model through llama.cpp) is about 7 times slower and also loses the code indentation.
- marker fast mode without the code rebuild puts each code listing on one line.
- k2pdfopt fit mode for whole books keeps the layout, but a long book makes the Kobo unresponsive. A 41.8 MB fitted PDF (739 source pages) did.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## WSL version

`wsl/kobo-send` is the first version. It is a Bash script for a Windows laptop with WSL2 and Google Drive for Desktop. It is kept for reference and is not maintained.
