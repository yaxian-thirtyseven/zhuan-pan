import io
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pymupdf
import xlrd
from docx import Document
from docx.table import Table
from openpyxl import load_workbook
from PIL import Image
from pillow_heif import register_heif_opener

from .ocr import OCRUnavailable, prepare_image, recognize

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 20 * 1024 * 1024
MAX_PAGES = 100
MAX_SCAN_PAGES = 15
MAX_EXTRACTED_ITEMS = 501
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
Image.MAX_IMAGE_PIXELS = 24_000_000
register_heif_opener()


def legacy_word_text(raw):
    with TemporaryDirectory(prefix="wheel-word-") as temp:
        file = Path(temp) / "document.doc"
        file.write_bytes(raw)
        result = subprocess.run(
            [os.environ.get("WHEEL_NODE", "node"), str(ROOT / "scripts" / "extract.mjs"), str(file)],
            capture_output=True, timeout=30, check=True,
        )
    return json.loads(result.stdout)


def pdf_text(raw):
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        if pdf.needs_pass:
            raise ValueError("无法导入加密的 PDF")
        if len(pdf) > MAX_PAGES:
            raise ValueError(f"PDF 最多支持 {MAX_PAGES} 页，请拆分后导入")
        pages = [page.get_text(sort=True) for page in pdf]
        scans = [index for index, text in enumerate(pages) if not text.strip()]
        if len(scans) > MAX_SCAN_PAGES:
            raise ValueError(f"扫描页最多支持 {MAX_SCAN_PAGES} 页，请拆分后导入")
        for index, text in enumerate(pages):
            if text.strip():
                yield text
                continue
            page = pdf[index]
            scale = min(2.5, 2400 / max(page.rect.width, page.rect.height))
            pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB)
            yield recognize(Image.frombytes("RGB", (pixels.width, pixels.height), pixels.samples))


def row_text(values):
    return " · ".join(str(value).strip() for value in values if value is not None and str(value).strip())


def word_text(raw):
    for block in Document(io.BytesIO(raw)).iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                yield row_text(cell.text.replace("\n", " ") for cell in row.cells)
        else:
            yield block.text


def excel_text(suffix, raw):
    if suffix == ".xls":
        book = xlrd.open_workbook(file_contents=raw, on_demand=True)
        try:
            for sheet in book.sheets():
                for index in range(sheet.nrows):
                    yield row_text(sheet.row_values(index))
        finally:
            book.release_resources()
    else:
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            for sheet in book.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    yield row_text(row)
        finally:
            book.close()


def document_lines(suffix, raw):
    if suffix in {".docx", ".xlsx"}:
        with ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 80 * 1024 * 1024:
                raise ValueError("文档解压后过大，请拆分后导入")
    if suffix == ".docx":
        return word_text(raw)
    if suffix in {".xlsx", ".xls"}:
        return excel_text(suffix, raw)
    if suffix == ".doc":
        return legacy_word_text(raw)
    if suffix == ".pdf":
        return pdf_text(raw)
    if suffix in IMAGE_SUFFIXES:
        with Image.open(io.BytesIO(raw)) as image:
            return [recognize(prepare_image(image))]
    raise ValueError("请选择图片、Word、Excel 或 PDF 文件")


def extract_items(filename, raw):
    suffix = Path(filename).suffix.lower()
    items = []
    try:
        for block in document_lines(suffix, raw):
            for line in block.splitlines():
                value = " ".join(line.split())
                for start in range(0, len(value), 250):
                    items.append(value[start:start + 250])
                    if len(items) >= MAX_EXTRACTED_ITEMS:
                        return items
    except subprocess.TimeoutExpired as error:
        raise ValueError("文字识别超时，请使用较小的文件") from error
    except subprocess.CalledProcessError as error:
        raise ValueError("文字识别失败，请检查文件内容与格式") from error
    except (ValueError, OCRUnavailable):
        raise
    except Exception as error:
        raise ValueError("无法读取文件，请检查格式或文件是否损坏") from error
    return items
