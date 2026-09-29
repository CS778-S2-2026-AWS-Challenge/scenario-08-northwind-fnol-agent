"""Bounded file usability checks, independent of extraction and Claim facts."""

from io import BytesIO

from PIL import Image, UnidentifiedImageError

IMAGE_MEDIA_TYPES = frozenset({'image/jpeg', 'image/png'})
MAX_IMAGE_PIXELS = 25_000_000
IMAGE_VALIDATION_VERSION = 'decoded-v1'


def validate_image_content(content: bytes, media_type: str) -> bool:
    """Check declared image format and fully decode a bounded static image.

    Args:
        content: Size-bounded bytes obtained from the finalised object.
        media_type: Registered JPEG or PNG media type.

    Returns:
        Whether the bytes form a decodable, single-frame image within the pixel limit.
        This is neither malware scanning nor verification of the image's meaning.
    """
    expected_format = {'image/jpeg': 'JPEG', 'image/png': 'PNG'}.get(media_type)
    if expected_format is None:
        return False
    try:
        with Image.open(BytesIO(content), formats=[expected_format]) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, 'n_frames', 1) != 1:
                return False
            image.verify()
        with Image.open(BytesIO(content), formats=[expected_format]) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False
    return True
