"""Bounded decoding for browser webcam frames and registration data URLs."""
import base64
import binascii
import re

import cv2
import numpy as np

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


def decode_image(image_bytes):
    if not image_bytes:
        raise ValueError("The captured image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large. Use a frame smaller than 4 MB.")
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode the image. Capture a JPEG or PNG again.")
    if image.shape[0] * image.shape[1] > MAX_IMAGE_PIXELS:
        raise ValueError("Image dimensions are too large.")
    return image


def decode_data_url(value):
    if not isinstance(value, str) or len(value) > (MAX_IMAGE_BYTES * 4 // 3 + 128):
        raise ValueError("Captured image is too large or invalid.")
    match = re.fullmatch(r"data:image/(?:jpeg|png);base64,([A-Za-z0-9+/]+={0,2})", value.strip())
    if not match:
        raise ValueError("Capture a JPEG or PNG face image before submitting.")
    try:
        image_bytes = base64.b64decode(match.group(1), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid Base64 image data.") from error
    return decode_image(image_bytes)
