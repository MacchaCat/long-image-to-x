---
name: long-image-to-x
description: Slice one long image (an illustrated essay, webcomic, infographic, long screenshot, or paged PDF export) into a set of images ready to post on X (Twitter). Trims side margins, finds cut points between content blocks, writes each set to its own folder, optionally stamps a watermark, checks the result visually, and gives posting advice. Use this whenever the user wants to split, cut, crop or slice a long image, long-form post, comic or document into several images for X or Twitter, asks for a four-image post, or says something like "make this fit X", even if they never say "slice" or "skill". Produces the images and a plan only; it does not post anything.
license: MIT
---

# Long image to X

Turn one very long image into a few images that fit in a single post and read well on a phone. The mechanical work (measuring gaps, trimming, cutting, contact sheets) is done by `scripts/slice.py`. Your job is deciding where to cut.

The script declares its own dependencies, so run it with `uv run` (system Python usually has no Pillow):

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/slice.py <subcommand> --help
```

`${CLAUDE_SKILL_DIR}` is the folder that contains this SKILL.md. If it shows up unexpanded in your environment, substitute that folder's path.

Every coordinate is a y value in **source pixels**. There is no 1x / 2x conversion.

## Workflow

### 1. Find the file to slice, and make sure it is the sharpest copy

- The user often gives a short name. Search the place they point to (often the Downloads folder) by keyword, and ask only if nothing turns up.
- The same piece may exist as several files: an `@2x` PNG, a plain PNG, a PDF. Prefer the widest one. Trimming the side margins removes roughly a third of the width, so a 1x image ends up soft on phones.
- For a PDF, run `pdfimages -list` to see whether the pages are embedded bitmaps. If so, extract them with `pdfimages -j`. If the PDF is vector, render it with `pdftoppm -r 300 -png`.
- When the copies have different modification times, the content may have changed. Go with the newest, and always look at the exact file you are about to slice rather than reading the PDF and slicing the PNG.
- If only a 1x source exists, slice it anyway, and tell the user the result is small and that a 2x export would be sharper.

When page images are sharper but only the long image has the right layout, use `stitch` to rebuild a high-resolution long image from the pages, then slice that. It checks each page's height against the long image and fails on a mismatch, which means the two files were laid out differently: do not force it, slice the long image itself. Matching heights only prove the layout is the same, not the content; an older draft with a few words changed can pass. So use `stitch` only when the pages and the long image come from the same export, and not when their modification times are far apart.

### 2. Measure the gaps and read the content

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/slice.py gaps    <long image>
uv run ${CLAUDE_SKILL_DIR}/scripts/slice.py preview <long image> --out <temp dir>
```

`preview` writes segment images with a ruler on the left: grey numbers are y coordinates, green bars are gaps, and the green number is the gap's midpoint. Read every preview and work out what sits above and below each gap. Choosing cut points without reading them is how an illustration ends up in a different image from the paragraph that explains it.

Keep previews in a temporary directory, not in the delivery folder.

### 3. Choose the cut points

In order of importance:

1. **Cut by content block, not by equal height.** A heading, its body text, an illustration and the caption that follows it are one block and belong in one image. Readers see one image at a time, and a figure separated from its text stops making sense.
2. **Cut at the midpoint of a large gap** (the green number in the preview). The script refuses a cut that lands on text or art.
3. **One set is one post, ideally 4 images.** A post on X holds at most 4 images. Do not squeeze in a fifth, and do not push one leftover image into a reply or into a set of its own.
4. **With more than 4 content blocks, first try merging down to 4 images of similar height.** List the height of each section and look for the grouping whose tallest image is shortest. If cutting only between sections cannot balance it, cut inside a section: pick a gap between paragraphs where the earlier image ends on something complete (a concluding sentence, say) and the later one opens naturally (with "Finally, ..." for instance). Figures still stay with their text.
5. **If 4 images cannot hold it, split into two sets: 4 in the first, 2 to 4 in the second, for 6, 7 or 8 in total.** "Cannot hold it" means every grouping leaves an image narrower than about 0.45 (width / height, thinner than 1:2), where text gets small on phones. Fill the first set with 4 and give the rest to the second, placing the boundary on a section break so the first set reads as a complete piece. `--split-after 4` cuts both at once: the first 4 go to `<issue>_<title>_part1/`, the rest to `<issue+1>_<title>_part2/`. The total must not be 5, because the second set would be a single image and that is not worth a post. With exactly 5 blocks, either merge down to 4 or add one more cut inside a section to make 6.
6. **Closing footnotes, notes and references go with the last block.** Endings often say "see the notes below", and the notes should be in the same image as that line. Links inside an image cannot be clicked, so suggest the user paste them as text in a reply.

### 4. Slice

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/slice.py slice <long image> --cuts <y1,y2,y3> --out <output root> --name <title> --issue <number>
```

- **One folder per set.** With `--issue N`, output goes to `<output root>/<2-digit issue>_<title>/` as `<title>_1.png`, `<title>_2.png` and so on. Sets never mix, and uploading in file-name order gives the right sequence.
- **Picking the issue number.** Use what the user says. Otherwise look at the existing `NN_*` folders in the output root: a new version of the same piece keeps its number and adds `--replace` (which deletes the old files first, so a changed image count leaves nothing stale); a new piece takes the next number (a piece that was split into two sets used two numbers). A line such as "as I said last time" in the text helps with ordering. Ask the user only when it really cannot be worked out.
- **The output root** defaults to `x-post/` in the current working directory. Never modify, move or overwrite the user's originals.
- The script measures the content's left and right bounds itself and trims the margins, keeping 8% of the content width on each side and adding about 6% above and below. Adjust with `--margin-x` and `--pad-y` (below 1 is a fraction, otherwise pixels).
- **Watermark.** Off by default. If the user gives a handle or signature to put on the images, pass `--watermark "<text>"`: it is written in the bottom-right padding of every image, right-aligned to the content edge, so it never covers content, in a mid-tone picked from the background colour. Stamping every image keeps the credit attached when a single image is reshared. If the user has asked for a watermark once, keep using the same text for later sets without asking again.
- **Watermarking images that are already sliced.** When only finished images exist and the long image is gone, use `slice.py watermark <images> --watermark "<text>" --out <dir>`. It only writes into each image's bottom padding and does not re-crop. `--in-place` overwrites the originals; before using it, make sure clean copies exist elsewhere, because a watermark cannot be removed afterwards. Do not stamp the same image twice; the script fails when the bottom padding is too small.
- The background colour is detected automatically, so dark backgrounds work. For noisy JPEG sources where no gaps are found, raise `--thresh`.

The script prints each image's size, ratio and file size, and warns about anything over the limits.

### 5. Check visually

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/slice.py sheet <finished images> --out <temp dir>/sheet.png
```

Read the contact sheet and confirm, image by image: no text or art is cut, no figure is separated from its text, each image opens naturally, top and bottom padding match, and any watermark is legible and clear of the content. If `stitch` was used, also extract each seam at full resolution with `crop` and confirm nothing is misaligned. Fix the cut points and re-slice when something is wrong; do not deliver with a known problem.

### 6. Deliver

The reply should include:

- The folder that holds the images, and a short table saying what each image contains.
- Posting advice: upload in order 1 to N; if this is a sequel, post it as a reply to or quote of the previous one; thumbnails in a four-image post are centre-cropped and usually hide a title at the top, so let the post text carry the title; links inside images cannot be clicked, so paste reference links into a reply.
- Anything the user needs to know: whether the source was lossy or 1x, and any warnings the script printed.

Do not post on the user's behalf. A post cannot be taken back, so the user publishes it.

## Image limits on X

The limits in the script (4096 px on the long side, 5 MB per image) are conservative values chosen in November 2026 and were **not confirmed against official X documentation**; the third-party guides found at the time disagreed with each other. While the output stays inside both numbers there is no need to dig further. If it exceeds them, or the user asks about exact limits, look up the current values first rather than presenting these two numbers as fact.
