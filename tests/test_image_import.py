import io
import unittest

from PIL import Image, ImageDraw, ImageFont

from backend.extract import extract_items


class ImageImportTests(unittest.TestCase):
    def test_recognizes_text_in_transparent_png(self):
        for color in ("black", "white"):
            with self.subTest(color=color):
                image = Image.new("RGBA", (720, 210))
                ImageDraw.Draw(image).text(
                    (35, 50), "HELLO WHEEL", fill=color, font=ImageFont.load_default(size=68)
                )
                data = io.BytesIO()
                image.save(data, format="PNG")

                self.assertEqual(extract_items("text.png", data.getvalue()), ["HELLO WHEEL"])
