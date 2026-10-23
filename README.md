# kobo-send

Send EPUB and PDF books to a Kobo e-reader over USB. EPUB becomes KEPUB, the native Kobo format. PDF is fitted to the screen or converted to reflowable text. kobo-send checks each book on the Kobo after the copy. A book replaces the other format of the same name, for example `X.pdf` replaces `X.kepub.epub`.

## Requirements

- Linux with a desktop session. udisks2 mounts the Kobo without root, but only for the active local session. Over SSH, the mount fails with "Not authorized".
- Python 3.11 or later. kobo-send uses the standard library only.
- [kepubify](https://github.com/pgaskin/kepubify/releases) v4.0.4.
- [k2pdfopt](https://www.willus.com/k2pdfopt/download/) v2.55. Do not use v2.54, because it drops the PDF bookmarks that the Kobo uses as the table of contents.
- [rclone](https://rclone.org/), only for an inbox on a cloud remote.

## Install

```bash
git clone https://github.com/dkoutavas/kobo-send.git
ln -s "$PWD/kobo-send/kobo-send" ~/.local/bin/kobo-send
install -m755 kepubify-linux-64bit ~/.local/bin/kepubify
install -m755 k2pdfopt ~/.local/bin/k2pdfopt
```

## Use

1. Connect the Kobo with USB and tap **Connect** on its screen.
2. Run one of these commands:

```bash
kobo-send book.epub notes.pdf  # send these files to Books/
kobo-send -d Fiction book.epub # send to Books/Fiction/
kobo-send --pdf reflow a.pdf   # reflow the PDF instead of fitting it
kobo-send -k book.epub         # keep the Kobo mounted afterwards
kobo-send                      # send the inbox, see Configure
```

3. When kobo-send prints "unmounted", unplug the cable. The Kobo adds the new books to its library only after you unplug it.

If a book fails, kobo-send continues with the next book. At the end, it leaves the Kobo mounted so that you can examine it, and the failed inbox file stays in the inbox.

## Configure

To send from an inbox folder, set `KOBO_SEND_INBOX` in your shell startup file. A value in the form `remote:path` is an rclone remote. Any other value is a local folder. Each sent file moves to the `Sent` subfolder of the inbox, so the next run skips it.

```bash
export KOBO_SEND_INBOX=~/kobo-inbox   # a local folder
export KOBO_SEND_INBOX=gdrive:Books   # a folder on the rclone remote "gdrive"
```

The other defaults are constants at the top of `src/kobo_send/cli.py` and `src/kobo_send/books.py`. They set the PDF mode (`fit`), the Kobo folder (`Books/`) and the path of the marker environment. They also set the k2pdfopt device profile, `koc`, which matches the screen of the Clara HD and the Clara BW. For another Kobo model, run `k2pdfopt -ui- -dev ?` to list the profiles.

## PDF modes

PDF pages are fixed, so the text does not flow to the screen size. Select a mode with `--pdf`:

- `fit` (default): k2pdfopt fits each page to the screen width and keeps the layout and the vector text. Use it for short documents. A long book makes the Kobo slow. A 41.8 MB fitted PDF of 739 pages made it unresponsive.
- `reflow`: marker reads the text and the layout, and kobo-send rebuilds each code listing from the glyph positions, so the indentation stays correct. The PDF bookmarks become the chapters and the table of contents. The result is a KEPUB, so the font size can change. The PDF must have a text layer, so a scanned PDF fails. Equations and complex tables can be imperfect.

Set up the marker environment once before you use reflow mode. It needs about 6 GB, and the first run downloads the layout models. A GPU makes marker faster, but it is not necessary.

```bash
python3.13 -m venv ~/.local/share/kobo-send/marker
~/.local/share/kobo-send/marker/bin/pip install marker-pdf==2.0.0
```

These approaches were tried for reflow and rejected:

- Calibre `ebook-convert` splits watermarks into one paragraph per word and mixes margin notes into code.
- k2pdfopt with reflow (`-wrap`) mixes margin notes into code and breaks tables.
- marker balanced mode (a vision language model) is about 7 times slower and also loses the code indentation.
- marker without the code rebuild puts each listing on one line.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## License

MIT. Reflow mode runs marker (Apache-2.0) as a separate program. The marker model weights have their own license (a modified OpenRAIL-M, free for personal use), and marker downloads them on first use.
