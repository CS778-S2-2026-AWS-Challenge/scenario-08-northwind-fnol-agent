"""Synthetic decodable image bytes for upload boundary regression tests."""

from io import BytesIO

from PIL import Image


def synthetic_image(*, media_type: str = 'image/jpeg', size_bytes: int = 0) -> bytes:
    image = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(
        image, format='PNG' if media_type == 'image/png' else 'JPEG', optimize=True
    )
    content = image.getvalue()
    if size_bytes and len(content) > size_bytes:
        raise ValueError('Requested synthetic image size is smaller than the encoded image.')
    return content.ljust(size_bytes, b'\x00')
