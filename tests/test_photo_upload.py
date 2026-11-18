import base64
import io
import pytest
from PIL import Image
from fitplate.photo_upload import normalize_photo, PhotoError
from fitplate.model_client import prepare_image


def encoded(image, format, **kwargs):
    output = io.BytesIO()
    image.save(output, format, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize('format', ['JPEG','PNG','WEBP','GIF','BMP','TIFF','HEIF','AVIF','ICO','PPM','TGA'])
def test_content_decoded_and_normalized(format):
    raw = encoded(Image.new('RGB',(64,48),'green'), format)
    with Image.open(io.BytesIO(normalize_photo(raw))) as image:
        assert image.format == 'JPEG' and image.mode == 'RGB'
        assert image.width <= 1280 and image.height <= 1280
    assert prepare_image(raw).startswith('data:image/jpeg;base64,')


@pytest.mark.parametrize('megabytes',[1,6])
def test_48mp_mobile_jpeg_not_rejected_by_old_pixel_limit(megabytes):
    raw = encoded(Image.new('RGB',(8000,6000),'green'),'JPEG',quality=85)
    raw += b'\0' * max(0,megabytes*1024*1024-len(raw))
    with Image.open(io.BytesIO(normalize_photo(raw))) as image:
        assert image.size == (1280,960)


def test_exif_orientation_and_private_metadata_removed():
    image=Image.new('RGB',(20,40),'red')
    exif=Image.Exif();exif[274]=6;exif[270]='private test description'
    with Image.open(io.BytesIO(normalize_photo(encoded(image,'JPEG',exif=exif)))) as result:
        assert result.size == (40,20) and not result.getexif()


def test_alpha_composited_on_white_and_cmyk_supported():
    image=Image.new('RGBA',(10,10),(0,0,0,0))
    with Image.open(io.BytesIO(normalize_photo(encoded(image,'PNG')))) as result:
        assert min(result.getpixel((0,0))) > 245
    normalize_photo(encoded(Image.new('CMYK',(10,10)),'JPEG'))


def test_animation_uses_first_frame():
    raw=encoded(Image.new('RGB',(24,24),'red'),'GIF',save_all=True,
                append_images=[Image.new('RGB',(24,24),'blue')])
    with Image.open(io.BytesIO(normalize_photo(raw))) as result:
        assert result.getpixel((0,0))[0] > 200


def test_corrupt_size_and_resolution_errors_are_distinct(monkeypatch):
    with pytest.raises(PhotoError,match='empty'):normalize_photo(b'')
    with pytest.raises(PhotoError,match='damaged'):normalize_photo(b'not an image')
    monkeypatch.setattr('fitplate.photo_upload.MAX_PHOTO_BYTES',10)
    with pytest.raises(PhotoError,match='20 MB'):normalize_photo(b'0'*11)
    monkeypatch.setattr('fitplate.photo_upload.MAX_PHOTO_BYTES',20*1024*1024)
    monkeypatch.setattr('fitplate.photo_upload.MAX_SOURCE_PIXELS',100)
    with pytest.raises(PhotoError,match='megapixels'):
        normalize_photo(encoded(Image.new('RGB',(20,20)),'PNG'))
