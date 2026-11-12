#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow", "numpy"]
# ///
"""Slice a long image into a set of images sized for a post on X.

Subcommands:
  gaps       list the blank rows where a cut is safe (coordinates are source pixels)
  preview    segment thumbnails with a y-axis ruler and gap markers, to map gaps to content
  slice      cut at the given points: trim side margins, drop extra blank rows, add even padding
  watermark  stamp a watermark onto images that are already sliced, without re-cropping
  sheet      lay finished images side by side for a visual check
  crop       extract a region at full resolution for a close look
  stitch     rebuild a high-resolution long image from page images, using a
             low-resolution long image as the layout reference

Run: uv run slice.py <subcommand> ...
"""
import argparse
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

# Upload limits on X. These two numbers are conservative values that were NOT
# confirmed against official X documentation. Exceeding them only warns.
MAX_SIDE = 4096
MAX_BYTES = 5 * 1024 * 1024
# Images per post on X. One set is one post; content that does not fit is split
# into two sets rather than squeezed into one.
MAX_IMAGES = 4
# Minimum images per set when splitting in two. A set with a single image is not
# worth its own post, so 4+1 is rejected while 4+2, 4+3 and 4+4 are fine.
MIN_PART = 2
# Anything narrower than this (width / height) is scaled to fit the phone screen
# by height when opened, which makes the text small.
MIN_RATIO = 0.45
# Output narrower than this usually means a 1x source; text looks soft on phones.
MIN_WIDTH = 1200

WATERMARK_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def watermark_font(size, path=None):
    for p in ([path] if path else []) + WATERMARK_FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    if path:
        die(f"cannot open watermark font: {path}")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_watermark(img, text, bg, pad, right_inset, font_path=None):
    """Write the text inside the bottom padding, right-aligned to the content edge,
    so it never covers content.

    The colour is the background moved 40% toward its opposite: mid-grey on a
    light background, and still visible on a dark one.
    """
    w, h = img.size
    fnt = watermark_font(max(12, round(w * 0.026)), font_path)
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=fnt)
    color = tuple(int(c + (255 - 2 * c) * 0.4) for c in bg)
    x = w - right_inset - (r - l) - l
    y = h - pad / 2 - (b - t) / 2 - t
    d.text((x, y), text, fill=color, font=fnt)
    return b - t


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def load(path):
    """Open an image and flatten it to RGB (transparency goes onto white)."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, "white")
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def bg_color(a):
    """Background = the most common colour along the four edges, so dark
    backgrounds work too."""
    edge = np.concatenate([
        a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3),
        a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3),
    ]).astype(np.int64)
    packed = (edge[:, 0] << 16) | (edge[:, 1] << 8) | edge[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    v = int(vals[counts.argmax()])
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def ink_mask(im, thresh, bg=None):
    a = np.asarray(im).astype(np.int32)
    if bg is None:
        bg = bg_color(a)
    return np.abs(a - np.array(bg)).sum(axis=2) > thresh, bg


def blank_runs(rows_ink, min_len):
    """Return [(start, end)]: runs of rows with no ink; end is exclusive."""
    runs, i, n = [], 0, len(rows_ink)
    while i < n:
        if not rows_ink[i]:
            j = i
            while j < n and not rows_ink[j]:
                j += 1
            if j - i >= min_len:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def default_min_gap(width):
    return max(8, round(width * 0.03))


def px_or_frac(value, base):
    """Values below 1 are a fraction of base; anything else is pixels."""
    v = float(value)
    return int(round(v * base)) if v < 1 else int(round(v))


def x_range(mask, args):
    """Columns to keep: the content's left/right bounds plus a margin on each side."""
    w = mask.shape[1]
    if getattr(args, "x_range", None):
        x0, x1 = (int(v) for v in args.x_range.split(","))
        return max(0, x0), min(w, x1)
    cols = np.nonzero(mask.any(axis=0))[0]
    if len(cols) == 0:
        die("the image has no content")
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    m = px_or_frac(args.margin_x, c1 - c0)
    return max(0, c0 - m), min(w, c1 + m)


# ---------------------------------------------------------------- gaps

def cmd_gaps(args):
    im = load(args.image)
    mask, bg = ink_mask(im, args.thresh)
    rows = mask.any(axis=1)
    w, h = im.size
    min_gap = args.min_gap or default_min_gap(w)
    cols = np.nonzero(mask.any(axis=0))[0]
    print(f"{args.image}")
    print(f"  size {w}x{h}  background {bg}  content columns {cols[0]}-{cols[-1] + 1}")
    print(f"  gaps (>= {min_gap}px):   start    end    len    mid")
    for s, e in blank_runs(rows, min_gap):
        print(f"                      {s:6d} {e:6d} {e - s:6d} {(s + e) // 2:6d}")


# ------------------------------------------------------------- preview

def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def cmd_preview(args):
    im = load(args.image)
    mask, bg = ink_mask(im, args.thresh)
    rows = mask.any(axis=1)
    w, h = im.size
    x0, x1 = x_range(mask, args)
    cw = x1 - x0
    seg = args.seg or int(cw * 1.5)
    f = min(1.0, args.width / cw)
    step = next(s for s in (25, 50, 100, 200, 250, 500, 1000, 2000, 5000) if s * f >= 45)
    gaps = blank_runs(rows, args.min_gap or default_min_gap(w))
    ruler = 150
    os.makedirs(args.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.image))[0]
    fnt = font(14)
    y, i = 0, 0
    while y < h:
        y1 = min(h, y + seg)
        if h - y1 < seg * 0.25:  # fold a short leftover into this segment
            y1 = h
        c = im.crop((x0, y, x1, y1))
        c = c.resize((int(cw * f), max(1, int((y1 - y) * f))), Image.LANCZOS)
        out = Image.new("RGB", (ruler + c.size[0], c.size[1]), (245, 245, 245))
        out.paste(c, (ruler, 0))
        d = ImageDraw.Draw(out)
        for s, e in gaps:  # gaps: green bar + midpoint coordinate
            if e <= y or s >= y1:
                continue
            ys, ye = (max(s, y) - y) * f, (min(e, y1) - y) * f
            d.rectangle([ruler - 14, ys, ruler - 2, ye], fill=(60, 170, 90))
            mid = (s + e) // 2
            if y <= mid < y1:
                d.text((78, (mid - y) * f - 8), str(mid), fill=(20, 120, 50), font=fnt)
        t = (y // step + (1 if y % step else 0)) * step
        while t < y1:  # ruler ticks
            ty = (t - y) * f
            d.line([0, ty, 10, ty], fill=(120, 120, 120))
            d.text((14, ty - 8), str(t), fill=(120, 120, 120), font=fnt)
            t += step
        p = os.path.join(args.out, f"{stem}_preview_{i:02d}_y{y}.png")
        out.save(p)
        print(p)
        y, i = y1, i + 1
    print("Grey ticks are source y coordinates. Green bars are gaps; the green number "
          "is the gap midpoint and can be used directly as a cut point.")


# --------------------------------------------------------------- slice

def cmd_slice(args):
    im = load(args.image)
    mask, bg = ink_mask(im, args.thresh)
    rows = mask.any(axis=1)
    w, h = im.size
    x0, x1 = x_range(mask, args)
    cuts = sorted(int(v) for v in args.cuts.split(",") if v.strip()) if args.cuts else []
    gaps = blank_runs(rows, default_min_gap(w)) or blank_runs(rows, 1)
    for c in cuts:
        if not 0 < c < h:
            die(f"cut {c} is outside the image (height {h})")
        if rows[c] or rows[c - 1]:
            near = sorted(gaps, key=lambda g: abs((g[0] + g[1]) // 2 - c))[:3]
            hint = ", ".join(f"{(s + e) // 2} (gap {s}-{e})" for s, e in sorted(near))
            die(f"cut {c} lands on a row with content and would slice through text or art. "
                f"Nearest gap midpoints: {hint}")
    pad = px_or_frac(args.pad_y, x1 - x0)
    name = args.name or os.path.splitext(os.path.basename(args.image))[0]
    n = len(cuts) + 1
    # At most MAX_IMAGES per post. Content that does not fit is split into two sets.
    if args.split_after is None:
        if n > MAX_IMAGES:
            die(f"{len(cuts)} cuts make {n} images, but a post on X holds at most {MAX_IMAGES}. "
                f"Merge neighbouring blocks down to {MAX_IMAGES} if you can; if that makes an image "
                f"too narrow, split into two sets ({MAX_IMAGES} + {MIN_PART}-{MAX_IMAGES}) with "
                f"--split-after {MAX_IMAGES}")
        groups = [("", args.issue, list(range(n)))]
    else:
        k = args.split_after
        if args.issue is None:
            die("--split-after needs --issue: the first set uses that number, the second the next one")
        if not (MIN_PART <= k <= MAX_IMAGES and MIN_PART <= n - k <= MAX_IMAGES):
            die(f"--split-after {k} gives sets of {k} and {n - k} images; each set must have "
                f"{MIN_PART}-{MAX_IMAGES} (a set with one image is not worth its own post). "
                f"With 5 images in total, merge down to 4 or add one more cut to make 6")
        groups = [("_part1", args.issue, list(range(k))), ("_part2", args.issue + 1, list(range(k, n)))]
    edges = [0] + cuts + [h]
    # Measure every segment and check every output folder before writing anything,
    # so a failure halfway never leaves a partial set behind.
    boxes = []
    for i, (y0, y1) in enumerate(zip(edges[:-1], edges[1:]), 1):
        r = np.nonzero(mask[y0:y1, x0:x1].any(axis=1))[0]
        if len(r) == 0:
            die(f"segment {i} ({y0}-{y1}) is empty; check the cut points")
        boxes.append((x0, y0 + int(r[0]), x1, y0 + int(r[-1]) + 1))
    plan = []
    for suffix, issue, idx in groups:
        prefix = name + suffix
        # One subfolder per set: <out>/<issue>_<name>/, so sets never mix.
        out_dir = os.path.join(args.out, f"{issue:02d}_{prefix}") if issue is not None else args.out
        stale = []
        if os.path.isdir(out_dir):
            stale = [f for f in os.listdir(out_dir)
                     if re.fullmatch(re.escape(prefix) + r"_\d+\.png", f)]
        if stale and not args.replace:
            die(f"{out_dir} already holds {len(stale)} file(s) named {prefix}_*.png. "
                "Pass --replace to overwrite the old version (those files are deleted first)")
        plan.append((out_dir, prefix, idx, stale))
    mark = args.watermark
    if mark:
        cols = np.nonzero(mask[:, x0:x1].any(axis=0))[0]
        right_inset = (x1 - x0) - (int(cols[-1]) + 1)
        # the bottom padding must be tall enough to hold the watermark
        pad_bottom = max(pad, round((x1 - x0) * 0.026 * 2.2))
    else:
        pad_bottom = pad
    warn = []
    print(f"columns {x0}-{x1}, top/bottom padding {pad}px, background {bg}"
          + (f", watermark {mark} (bottom right)" if mark else ""))
    if x1 - x0 < MIN_WIDTH:
        warn.append(f"output is only {x1 - x0}px wide (below {MIN_WIDTH}); the source is probably a 1x "
                    "export and text will look soft on phones. Re-slice from a 2x source if one exists")
    for out_dir, prefix, idx, stale in plan:
        os.makedirs(out_dir, exist_ok=True)
        for f in stale:
            os.remove(os.path.join(out_dir, f))
        print(f"writing to {out_dir}")
        for i, bi in enumerate(idx, 1):
            c = im.crop(boxes[bi])
            o = Image.new("RGB", (c.size[0], c.size[1] + pad + pad_bottom), bg)
            o.paste(c, (0, pad))
            if mark:
                draw_watermark(o, mark, bg, pad_bottom, right_inset, args.watermark_font)
            p = os.path.join(out_dir, f"{prefix}_{i}.png")
            o.save(p, optimize=True)
            size = os.path.getsize(p)
            ratio = o.size[0] / o.size[1]
            print(f"  {os.path.basename(p)}  {o.size[0]}x{o.size[1]}  ratio {ratio:.2f}  {size / 1024:.0f} KB")
            if max(o.size) > MAX_SIDE:
                warn.append(f"{os.path.basename(p)}: long side {max(o.size)} exceeds {MAX_SIDE}; "
                            "it may be downscaled on upload")
            if size > MAX_BYTES:
                warn.append(f"{os.path.basename(p)}: larger than {MAX_BYTES // 1024 // 1024} MB")
            if ratio < MIN_RATIO:
                warn.append(f"{os.path.basename(p)}: ratio {ratio:.2f} is very narrow and text will be small "
                            "on phones; consider splitting into two sets (--split-after)")
    for m in warn:
        print("  warning: " + m)


# ----------------------------------------------------------- watermark

def cmd_watermark(args):
    """Stamp a watermark onto finished images without re-cropping them.

    The text goes into each image's own bottom padding. All images in one run are
    right-aligned to the same line (the one whose content reaches furthest right).
    """
    text = args.watermark
    items = []
    for path in args.images:
        im = load(path)
        mask, bg = ink_mask(im, args.thresh)
        rows = np.nonzero(mask.any(axis=1))[0]
        cols = np.nonzero(mask.any(axis=0))[0]
        if len(rows) == 0:
            die(f"{path} is empty")
        w, h = im.size
        pad_bottom = h - (int(rows[-1]) + 1)
        need = round(w * 0.026 * 1.8)
        if pad_bottom < need:
            die(f"{path} has only {pad_bottom}px of bottom padding (needs at least {need}px), so the "
                "watermark does not fit. It may already be watermarked; otherwise re-slice from the long image.")
        items.append((path, im, bg, pad_bottom, w - (int(cols[-1]) + 1)))
    inset = min(it[4] for it in items)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    for path, im, bg, pad_bottom, _ in items:
        draw_watermark(im, text, bg, pad_bottom, inset, args.watermark_font)
        dest = os.path.join(args.out, os.path.basename(path)) if args.out else path
        im.save(dest, optimize=True)
        print(f"  {dest}  {im.size[0]}x{im.size[1]}  {os.path.getsize(dest) / 1024:.0f} KB")
    print(f"watermark {text} on {len(items)} image(s)")


# --------------------------------------------------------------- sheet

def cmd_sheet(args):
    ims = [load(p) for p in args.images]
    w = args.width
    rs = [im.resize((w, max(1, int(im.size[1] * w / im.size[0]))), Image.LANCZOS) for im in ims]
    gap = 10
    sheet = Image.new("RGB", (gap + len(rs) * (w + gap), max(r.size[1] for r in rs) + 2 * gap), (120, 120, 120))
    for k, r in enumerate(rs):
        sheet.paste(r, (gap + k * (w + gap), gap))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sheet.save(args.out)
    print(args.out, sheet.size)


# ---------------------------------------------------------------- crop

def cmd_crop(args):
    im = load(args.image)
    box = tuple(int(v) for v in args.box.split(","))
    if len(box) != 4:
        die("--box needs x0,y0,x1,y1")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    im.crop(box).save(args.out)
    print(args.out)


# -------------------------------------------------------------- stitch

def cmd_stitch(args):
    """When page images are sharper but the long image has the right layout:
    paste each page's content where it sits in the long image.

    Each page's content height must match the corresponding stretch of the
    reference, otherwise this fails. A mismatch means the two files were laid out
    differently and a forced stitch would be wrong.
    """
    ref = load(args.ref)
    rmask, _ = ink_mask(ref, args.thresh)
    rrows = rmask.any(axis=1)
    rw, rh = ref.size
    pages = [load(p) for p in args.pages]
    pw = pages[0].size[0]
    if any(p.size[0] != pw for p in pages):
        die("pages have different widths")
    scale = pw / rw
    tol = args.tol
    rgaps = blank_runs(rrows, 1)
    out = None
    ink = np.nonzero(rrows)[0]
    if len(ink) == 0:
        die("the reference image is empty")
    start = int(ink[0])
    for k, pg in enumerate(pages, 1):
        pmask, pbg = ink_mask(pg, args.thresh)
        r = np.nonzero(pmask.any(axis=1))[0]
        if len(r) == 0:
            die(f"page {k} is empty")
        if out is None:
            out = Image.new("RGB", (pw, int(round(rh * scale))), pbg)
        top, bot = int(r[0]), int(r[-1]) + 1
        expect_end = start + (bot - top) / scale
        # in the reference this stretch should end near expect_end, followed by a gap
        hit = [g for g in rgaps if abs(g[0] - expect_end) <= tol]
        if not hit:
            near = min(rgaps, key=lambda g: abs(g[0] - expect_end)) if rgaps else None
            die(f"page {k} content is {(bot - top) / scale:.1f} tall (in reference pixels) and should end "
                f"near y={expect_end:.1f}, but the nearest gap in the reference starts at "
                f"{near[0] if near else 'none'}. The two files have different layouts; do not stitch them.")
        out.paste(pg.crop((0, top, pw, bot)), (0, int(round(start * scale))))
        g = min(hit, key=lambda g: abs(g[0] - expect_end))
        print(f"  page {k} -> reference y {start}-{g[0]} (output y {int(round(start * scale))})")
        start = g[1]
    if start < rh and rrows[start:].any():
        die(f"the reference still has content after y={start} but the pages ran out; pages are missing")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out.save(args.out)
    print(f"{args.out}  {out.size[0]}x{out.size[1]} ({scale:g}x the reference)")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, margins=False):
        p.add_argument("--thresh", type=int, default=60,
                       help="how far from the background colour counts as ink (sum of RGB differences, "
                            "default 60; raise it for noisy JPEG sources)")
        if margins:
            p.add_argument("--margin-x", default="0.08",
                           help="margin kept on each side of the content: below 1 is a fraction of the "
                                "content width, otherwise pixels (default 0.08)")
            p.add_argument("--x-range", help="keep exactly these columns, x0,x1; overrides --margin-x")

    p = sub.add_parser("gaps", help="list blank rows")
    p.add_argument("image")
    p.add_argument("--min-gap", type=int, help="minimum height in pixels to count as a gap (default 3%% of width)")
    common(p)
    p.set_defaults(fn=cmd_gaps)

    p = sub.add_parser("preview", help="segment previews with a coordinate ruler")
    p.add_argument("image")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--seg", type=int, help="source height per segment (default 1.5x the content width)")
    p.add_argument("--width", type=int, default=800, help="preview width")
    p.add_argument("--min-gap", type=int)
    common(p, margins=True)
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("slice", help="cut at the given points")
    p.add_argument("image")
    p.add_argument("--cuts", help="y coordinates of the cuts, comma separated (N images need N-1 cuts); "
                                  "omit to only trim the margins")
    p.add_argument("--out", required=True, help="output root directory")
    p.add_argument("--name", help="file name prefix (default: the source file name)")
    p.add_argument("--issue", type=int, help="issue number; output goes to <out>/<2-digit issue>_<name>/")
    p.add_argument("--replace", action="store_true",
                   help="if the target folder already holds this set, delete the old files first")
    p.add_argument("--split-after", type=int, metavar="K",
                   help=f"when the content does not fit in {MAX_IMAGES} images, split into two sets: the first K "
                        f"(normally {MAX_IMAGES}) go to <issue>_<name>_part1, the remaining "
                        f"{MIN_PART}-{MAX_IMAGES} to <issue+1>_<name>_part2")
    p.add_argument("--watermark", help="text to stamp in the bottom-right padding of every image, "
                                       "e.g. an @handle (default: no watermark)")
    p.add_argument("--watermark-font", help="path to a font file for the watermark (default: a system sans-serif)")
    p.add_argument("--pad-y", default="0.064",
                   help="padding added above and below each image: below 1 is a fraction of the output "
                        "width, otherwise pixels (default 0.064)")
    common(p, margins=True)
    p.set_defaults(fn=cmd_slice)

    p = sub.add_parser("watermark", help="stamp a watermark on already-sliced images (no re-cropping)")
    p.add_argument("images", nargs="+")
    p.add_argument("--watermark", required=True, help="the text to stamp, e.g. an @handle")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--out", help="output directory (file names are kept)")
    g.add_argument("--in-place", action="store_true",
                   help="overwrite the originals; first make sure clean copies exist elsewhere")
    p.add_argument("--watermark-font", help="path to a font file for the watermark")
    common(p)
    p.set_defaults(fn=cmd_watermark)

    p = sub.add_parser("sheet", help="side-by-side contact sheet")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=560, help="width of each image on the sheet")
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("crop", help="extract a region at full resolution")
    p.add_argument("image")
    p.add_argument("--box", required=True, help="x0,y0,x1,y1")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_crop)

    p = sub.add_parser("stitch", help="rebuild a hi-res long image from page images using a low-res long image's layout")
    p.add_argument("--ref", required=True, help="the long image whose layout is correct")
    p.add_argument("--pages", nargs="+", required=True, help="hi-res page images, in order")
    p.add_argument("--out", required=True)
    p.add_argument("--tol", type=float, default=3, help="allowed height mismatch in reference pixels (default 3)")
    common(p)
    p.set_defaults(fn=cmd_stitch)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
