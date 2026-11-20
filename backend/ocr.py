from functools import cache
from threading import Lock

from PIL import Image, ImageOps, ImageStat

OCR_LOCK = Lock()


class OCRUnavailable(RuntimeError):
    pass


@cache
def engine():
    from rapidocr import RapidOCR

    return RapidOCR(params={
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Global.log_level": "warning",
    })


def prepare_image(image):
    image = ImageOps.exif_transpose(image)
    if image.has_transparency_data:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        luminance = ImageStat.Stat(rgba.convert("L"), mask=alpha).mean[0]
        background = Image.new("RGBA", rgba.size, "#202020" if luminance > 170 else "white")
        background.alpha_composite(rgba)
        image = background
    image = image.convert("RGB")
    image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
    return image


def recognize(image):
    if all(low == high for low, high in image.getextrema()):
        return ""
    with OCR_LOCK:
        try:
            reader = engine()
            for rotation in (None, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_270):
                candidate = image if rotation is None else image.transpose(rotation)
                result = reader(candidate)
                if result.txts:
                    return "\n".join(result.txts)
            return ""
        except Exception as error:
            raise OCRUnavailable("图片文字识别暂时不可用，请查看启动终端中的错误信息") from error
