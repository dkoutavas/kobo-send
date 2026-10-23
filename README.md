# kobo-send

Send EPUB and PDF books to a Kobo e-reader over USB.

- EPUB files are converted to KEPUB with kepubify. KEPUB is the native Kobo format.
- PDF files are fitted to the Kobo screen with k2pdfopt. The tool does not reflow the text, so code listings and margin notes keep their layout.
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

All settings are optional. The defaults are:

```toml
# ~/.config/kobo-send/config.toml
inbox = "gdrive:Books"      # rclone remote folder to send from
sent = "Sent"               # subfolder of the inbox that receives sent files
subdir = "Technical"        # folder under Books/ on the Kobo
label = "KOBOeReader"       # filesystem label of the Kobo
k2pdfopt_device = "koc"     # Kobo Clara HD profile: same 1072 px, 300 dpi panel as the Clara BW
```

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

A PDF has fixed page positions, not a text flow. Two approaches were tested:

- Calibre (`ebook-convert`) PDF to EPUB guesses the text flow from word positions. It splits watermarks into one paragraph per word and mixes margin notes into code. The result is not reliable.
- k2pdfopt with reflow (`-wrap`) also mixes margin notes into code and breaks tables.

kobo-send uses k2pdfopt with `-wrap- -col 1 -n`. This fits each page region to the screen width without reflow, and keeps the vector text. You cannot change the font size on the Kobo, but the page layout stays correct. k2pdfopt takes about 0.2 to 0.5 seconds for each source page.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## WSL version

`wsl/kobo-send` is the first version. It is a Bash script for a Windows laptop with WSL2 and Google Drive for Desktop. It is kept for reference and is not maintained.
