from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageSequence
except ImportError:
    sys.exit("Missing dependency. Install it with: pip install Pillow")

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif"}

# Formats that can contain multiple frames/pages worth preserving.
MULTI_FRAME_FORMATS = {"GIF", "TIFF", "WEBP"}


class StripResult:
    def __init__(self, path: Path):
        self.path = path
        self.had_exif = False
        self.had_icc = False
        self.other_keys: list[str] = []
        self.frame_count = 1
        self.error: str | None = None

    @property
    def had_metadata(self) -> bool:
        return self.had_exif or self.had_icc or bool(self.other_keys)


def _clean_frame(frame: "Image.Image") -> "Image.Image":
    """Return a new image containing only pixel data — no .info dict at all."""
    frame = frame.convert(frame.mode)
    clean = Image.new(frame.mode, frame.size)
    if hasattr(frame, "get_flattened_data"):
        clean.putdata(frame.get_flattened_data())
    else:  # Pillow < 12 fallback
        clean.putdata(list(frame.getdata()))
    return clean


def strip_image_metadata(
    input_path: Path,
    output_path: Path,
    keep_icc: bool = False,
    quality: int = 95,
    dry_run: bool = False,
) -> StripResult:
    """Strip metadata from a single image file and write the result to output_path."""
    result = StripResult(input_path)

    try:
        img = Image.open(input_path)
        img.load()
    except Exception as exc:  # noqa: BLE001
        result.error = f"could not open image ({exc})"
        return result

    result.had_exif = bool(img.getexif())
    result.had_icc = "icc_profile" in img.info
    result.other_keys = [k for k in img.info.keys() if k not in ("exif", "icc_profile")]
    fmt = (img.format or "").upper()

    if dry_run:
        return result

    icc_profile = img.info.get("icc_profile") if keep_icc else None
    save_kwargs: dict = {}
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    try:
        if fmt in MULTI_FRAME_FORMATS and getattr(img, "n_frames", 1) > 1:
            frames = [_clean_frame(f) for f in ImageSequence.Iterator(img)]
            result.frame_count = len(frames)
            first, rest = frames[0], frames[1:]
            extra = {}
            # Preserve animation timing/loop info if present, without any
            # other metadata (comments, XMP, application extensions, etc.)
            if "duration" in img.info:
                extra["duration"] = img.info["duration"]
            if "loop" in img.info:
                extra["loop"] = img.info["loop"]
            first.save(
                output_path,
                format=fmt,
                save_all=True,
                append_images=rest,
                **extra,
                **save_kwargs,
            )
        else:
            clean = _clean_frame(img)
            if fmt == "JPEG":
                save_kwargs.setdefault("quality", quality)
                save_kwargs.setdefault("optimize", True)
            clean.save(output_path, format=fmt, **save_kwargs)
    except Exception as exc:  # noqa: BLE001
        result.error = f"could not save image ({exc})"

    return result


def collect_targets(paths: list[Path], recursive: bool) -> list[Path]:
    targets: list[Path] = []
    for p in paths:
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            targets.extend(
                f for f in p.glob(pattern)
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif p.is_file():
            targets.append(p)
        else:
            print(f"skip: {p} (not found)", file=sys.stderr)
    return targets


def build_output_path(src: Path, args: argparse.Namespace) -> Path:
    if args.in_place:
        return src
    if args.output and len(args.targets) == 1 and args.targets[0].is_file():
        return Path(args.output)
    out_dir = Path(args.output) if args.output else src.parent / "cleaned"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / src.name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strip EXIF/IPTC/XMP/ICC/GPS metadata from images.",
    )
    parser.add_argument("targets", nargs="+", type=Path, help="Image file(s) or director(y/ies)")
    parser.add_argument("-o", "--output", help="Output file (single input) or directory (default: ./cleaned)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the original files")
    parser.add_argument("--keep-icc", action="store_true", help="Preserve the ICC color profile (keeps colors accurate, minimal privacy risk)")
    parser.add_argument("--quality", type=int, default=95, help="JPEG quality when re-encoding (default: 95)")
    parser.add_argument("--dry-run", action="store_true", help="Report found metadata without writing any files")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only print a final summary")
    args = parser.parse_args()

    files = collect_targets(args.targets, args.recursive)
    if not files:
        print("No supported image files found.", file=sys.stderr)
        return 1

    cleaned, skipped, failed = 0, 0, 0

    for src in files:
        result = strip_image_metadata(
            src,
            build_output_path(src, args) if not args.dry_run else src,
            keep_icc=args.keep_icc,
            quality=args.quality,
            dry_run=args.dry_run,
        )

        if result.error:
            failed += 1
            print(f"FAILED  {src}: {result.error}", file=sys.stderr)
            continue

        if not result.had_metadata:
            skipped += 1
            if not args.quiet:
                print(f"clean   {src} (no metadata found)")
            continue

        cleaned += 1
        if not args.quiet:
            tags = []
            if result.had_exif:
                tags.append("EXIF")
            if result.had_icc:
                tags.append("ICC" + (" [kept]" if args.keep_icc else ""))
            if result.other_keys:
                tags.append(",".join(result.other_keys))
            frame_note = f", {result.frame_count} frames" if result.frame_count > 1 else ""
            verb = "found" if args.dry_run else "stripped"
            print(f"{verb:9}{src}: {' + '.join(tags)}{frame_note}")

    print(
        f"\n{'Would clean' if args.dry_run else 'Cleaned'}: {cleaned}  "
        f"Already clean: {skipped}  Failed: {failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())