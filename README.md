# kobo-send

Send EPUB and PDF books to a Kobo e-reader over USB.

- EPUB files are converted to KEPUB with kepubify.
- PDF files are fitted to the Kobo screen with k2pdfopt. The tool does not reflow the text, so code listings keep their layout.

`wsl/kobo-send` is the first version. It is a Bash script for a Windows laptop with WSL2 and Google Drive for Desktop. It is kept for reference.
