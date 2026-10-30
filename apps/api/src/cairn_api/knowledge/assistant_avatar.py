"""Validate the small PNG produced by the avatar picker at the request boundary."""

import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError

AVATAR_MAX_LENGTH = 90_000
AVATAR_PREFIX = "data:image/png;base64,"


def validate_avatar(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(AVATAR_PREFIX):
        raise ValueError("头像必须是上传的 PNG 图片")
    try:
        raw = base64.b64decode(value[len(AVATAR_PREFIX) :], validate=True)
        with Image.open(BytesIO(raw), formats=["PNG"]) as image:
            if image.width > 128 or image.height > 128 or image.width < 1 or image.height < 1:
                raise ValueError("头像尺寸不能超过 128×128")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("头像必须是静态图片")
            image.load()
    except (binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("头像图片无效，请重新选择 PNG、JPEG 或 WebP 图片") from None
    return value
