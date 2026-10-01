"""Deterministic transforms that turn a normal material into a boundary variant."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageFilter
from pypdf import PdfReader, PdfWriter


def blur(src: str, dst: str, radius: float = 9, quality: int = 45) -> dict[str, Any]:
    """Illegible photo: strong blur plus heavy JPEG compression."""
    img = Image.open(src).convert('RGB').filter(ImageFilter.GaussianBlur(radius))
    img.save(dst, format='JPEG', quality=quality)
    return {'transform': 'blur', 'radius': radius, 'jpeg_quality': quality}


def crop(src: str, dst: str, box: list[int], quality: int = 88) -> dict[str, Any]:
    """Remove part of the frame, for example a plate edge the image model drew. \
Box is (left, top, right, bottom)."""
    img = Image.open(src).convert('RGB').crop(cast(tuple[int, int, int, int], tuple(box)))
    img.save(dst, format='JPEG', quality=quality, optimize=True)
    return {'transform': 'crop', 'box': list(box), 'jpeg_quality': quality}


def keep_pages(src: str, dst: str, pages: list[int]) -> dict[str, Any]:
    """Missing page: keep only the listed zero-based pages."""
    reader = PdfReader(src)
    writer = PdfWriter()
    for index in pages:
        writer.add_page(reader.pages[index])
    with open(dst, 'wb') as handle:
        writer.write(handle)
    return {'transform': 'keep_pages', 'kept': pages, 'original_pages': len(reader.pages)}


def truncate(src: str, dst: str, keep_fraction: float = 0.4) -> dict[str, Any]:
    """Corrupt file: the first part of the bytes only."""
    data = Path(src).read_bytes()
    Path(dst).write_bytes(data[: int(len(data) * keep_fraction)])
    return {'transform': 'truncate', 'keep_fraction': keep_fraction}


def to_unsupported(src: str, dst: str) -> dict[str, Any]:
    """Unsupported format: the same image saved as TIFF."""
    Image.open(src).save(dst, format='TIFF')
    return {'transform': 'to_tiff'}


TRANSFORMS: dict[str, Callable[..., dict[str, Any]]] = {
    'blur': blur,
    'crop': crop,
    'keep_pages': keep_pages,
    'truncate': truncate,
    'to_unsupported': to_unsupported,
}
