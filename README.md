# long-image-to-x

A Claude Code skill that slices one long image into a set of images ready to post on X (Twitter).

Give it an illustrated essay, a webcomic, an infographic, a long screenshot or a paged PDF export, and it produces a folder of images that fit in one post and read well on a phone.

## What it does

- **Trims the side margins**, so text is as large as possible on a phone.
- **Cuts between content blocks**, never through text or art. A figure stays with the paragraph that explains it.
- **Keeps to 4 images per post.** If the content does not fit in 4, it splits into two sets (4 + 2, 4 + 3 or 4 + 4). It never leaves a set with a single image.
- **Writes each set to its own folder**, numbered by issue: `x-post/01_<title>/`, `x-post/02_<title>/`, and so on.
- **Optional watermark**, such as your @handle, in the bottom-right padding of every image. It never covers content.
- **Checks the result visually** with a contact sheet before handing it over.
- **Gives posting advice.** It does not post anything for you.

Light and dark backgrounds both work.

## Requirements

- [uv](https://docs.astral.sh/uv/) to run the bundled script. On first run, uv downloads Pillow and NumPy from PyPI. The script makes no other network requests.
- Optional: [poppler](https://poppler.freedesktop.org/) (`pdfimages`, `pdftoppm`) when the source is a PDF.

## Install

```
/plugin marketplace add MacchaCat/long-image-to-x
/plugin install long-image-to-x@long-image-to-x-marketplace
```

## Use

Ask in plain words, for example:

> Slice ~/Downloads/my-essay@2x.png into images for X. It's issue 3, and put @myhandle on them.

Claude finds the file, reads it, chooses the cut points, slices, checks the result and tells you what is in each image.

## Using the script on its own

`skills/long-image-to-x/scripts/slice.py` also works as a standalone command-line tool:

```bash
uv run slice.py gaps    long.png                       # list safe cut points
uv run slice.py preview long.png --out /tmp/preview    # previews with a y-axis ruler
uv run slice.py slice   long.png --cuts 1676,3308,5010 --out x-post --name my-essay --issue 3 --watermark "@myhandle"
uv run slice.py sheet   x-post/03_my-essay/*.png --out /tmp/sheet.png
```

Run `uv run slice.py <subcommand> --help` for every option.

## A note on X's limits

The limits built into the script (4096 px on the long side, 5 MB per image) are conservative values and were not confirmed against official X documentation. Exceeding them only prints a warning.

## License

MIT
