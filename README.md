# exif_remover

A small, dependency-light CLI for stripping hidden metadata out of images —
EXIF (including GPS coordinates and camera serial numbers), ICC profiles,
XMP, IPTC, and format-specific text/comment chunks.

Most "resave the image" approaches quietly carry metadata over. This tool
instead rebuilds a brand-new image from raw pixel data, so nothing survives
unless you explicitly ask to keep it (`--keep-icc`).

## Why

Photos taken on phones often embed GPS coordinates and device info in EXIF.
Screenshots and scans can carry software/author fields. Before posting an
image publicly, it's worth stripping that out.

## Install

```bash
pip install -r requirements.txt
```

Only dependency is [Pillow](https://python-pillow.org/).

## GUI

If you'd rather click than type, there's a tiny file-picker front end
(uses `tkinter`, which ships with most Python installs — no extra install):

```bash
python gui.py
```

Add files or a whole folder, tick your options, hit **Strip Metadata**.
Output goes to a `cleaned/` folder next to each source file, unless you
check "Overwrite originals."

## CLI usage

```bash
# Single file -> writes ./cleaned/photo.jpg
python cli.py photo.jpg

# Explicit output path
python cli.py photo.jpg -o clean.jpg

# Whole folder, recursively
python cli.py ./photos --recursive

# Overwrite originals instead of writing to ./cleaned
python cli.py ./photos -r --in-place

# See what metadata exists without changing anything
python cli.py photo.jpg --dry-run

# Keep the ICC color profile (safe to keep — no personal info in it)
python cli.py photo.jpg --keep-icc
```

Run `python cli.py --help` for the full option list.

## Supported formats

JPEG, PNG, WEBP, TIFF, BMP, GIF — including animated GIF/WEBP and
multi-page TIFF (frames/pages and timing are preserved; metadata isn't).

## Notes / limitations

- When processing a directory without `-o`, each subdirectory gets its own
  `cleaned/` folder next to the originals in that subdirectory (not one
  mirrored tree at the top). Use `-o some/output/dir` if you want everything
  collected in one place instead (works best for a flat, non-recursive run).
- A few purely structural fields are intentionally left in place because
  they're required for the file to work at all — e.g. GIF's `NETSCAPE2.0`
  loop extension, JFIF density markers. These carry no identifying
  information.
- Re-encoding JPEGs (`--quality`, default 95) causes a small, usually
  invisible, generation loss — this is unavoidable if you want the EXIF
  orientation tag gone too, since the pixels are re-written upright.

## License

MIT — do whatever you want with it.
