"""Decode image content into a small, metadata-free JPEG for all downstream tools."""
import io
import threading
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()
MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_SOURCE_PIXELS = 80_000_000
_decode_slot = threading.BoundedSemaphore(1)


class PhotoError(ValueError):
    pass


def normalize_photo(data):
    if not data:
        raise PhotoError('The image file is empty. Choose another photo.')
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoError('This image exceeds the 20 MB upload limit. Export a smaller copy.')
    if not _decode_slot.acquire(blocking=False):
        raise PhotoError('Another photo is being processed. Please try again shortly.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_SOURCE_PIXELS:
                    raise PhotoError('This photo exceeds 80 megapixels. Export a lower-resolution copy.')
                image.draft('RGB', (1280, 1280))
                image.thumbnail((1280, 1280))
                image = ImageOps.exif_transpose(image)
                if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                    rgba = image.convert('RGBA')
                    rgb = Image.new('RGB', rgba.size, 'white')
                    rgb.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    rgb = image.convert('RGB')
                output = io.BytesIO()
                rgb.save(output, 'JPEG', quality=85)
                return output.getvalue()
    except PhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PhotoError('This photo exceeds the supported resolution. Export a lower-resolution copy.') from None
    except MemoryError:
        raise PhotoError('There is not enough server memory to decode this photo. Export a lower-resolution copy.') from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise PhotoError('This image is damaged or its format cannot be decoded. Export it as JPEG, PNG, WebP, HEIC or AVIF and try again.') from None
    finally:
        _decode_slot.release()
