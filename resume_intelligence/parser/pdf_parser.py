# -*- coding: utf-8 -*-
import io
import logging
from .text_cleaner import clean_text
from .extraction_quality import evaluate_extraction_quality

logger = logging.getLogger(__name__)

def parse_pdf(stream):
    """
    Layout-aware multi-column PDF extractor with OCR fallback.
    Engines:
    1. pdfplumber (Layout & table extraction)
    2. PyMuPDF (Block & text extraction)
    3. pypdf (Stream reader)
    4. pytesseract OCR (Scanned / image-based PDF fallback)
    Returns: (cleaned_text, extraction_report)
    """
    text_content = ""
    page_count = 1
    extraction_method = "pdfplumber"
    has_tables = False
    table_count = 0
    multi_column = False
    is_ocr = False

    try:
        stream.seek(0)
        raw_bytes = stream.read()
        byte_io = io.BytesIO(raw_bytes)
        
        # 1. Primary Engine: pdfplumber (Layout & multi-column sorting + tables)
        try:
            import pdfplumber
            with pdfplumber.open(byte_io) as pdf:
                page_count = len(pdf.pages)
                pages_text = []
                for p in pdf.pages:
                    # Check for tables
                    tables = p.extract_tables() or []
                    if tables:
                        has_tables = True
                        table_count += len(tables)

                    # Extract words to detect multi-column layout
                    words = p.extract_words(x_tolerance=3, y_tolerance=3) or []
                    if words and len(words) > 30:
                        # Check horizontal distribution of words
                        mid_x = (p.width or 600) / 2
                        left_words = [w for w in words if w.get('x1', 0) < mid_x]
                        right_words = [w for w in words if w.get('x0', 0) >= mid_x]
                        if len(left_words) > 20 and len(right_words) > 20:
                            multi_column = True

                    # Extract text with horizontal & vertical layout preservation
                    page_txt = p.extract_text(layout=False, x_tolerance=2, y_tolerance=3)
                    if page_txt and page_txt.strip():
                        pages_text.append(page_txt)
                text_content = "\n\n".join(pages_text)
        except Exception as e1:
            logger.warning(f"pdfplumber extraction failed, falling back to pymupdf: {e1}")

        # 2. Fallback Engine: PyMuPDF (modern import)
        if not text_content.strip() or len(text_content.strip()) < 40:
            try:
                import pymupdf
                doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
                page_count = len(doc)
                pages_text = []
                for page in doc:
                    txt = page.get_text("text")
                    if txt.strip():
                        pages_text.append(txt)
                if "\n\n".join(pages_text).strip():
                    text_content = "\n\n".join(pages_text)
                    extraction_method = "pymupdf"
            except Exception as e2:
                logger.warning(f"pymupdf extraction failed: {e2}")

        # 3. Fallback Engine: pypdf
        if not text_content.strip() or len(text_content.strip()) < 40:
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw_bytes))
                page_count = len(reader.pages)
                pages_text = [p.extract_text() or "" for p in reader.pages if (p.extract_text() or "").strip()]
                if "\n\n".join(pages_text).strip():
                    text_content = "\n\n".join(pages_text)
                    extraction_method = "pypdf"
            except Exception as e3:
                logger.warning(f"pypdf extraction failed: {e3}")

        # 4. Fallback Engine: PyTesseract OCR for image-based/scanned PDFs
        if not text_content.strip() or len(text_content.strip()) < 40:
            try:
                import pymupdf
                import pytesseract
                from PIL import Image
                doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
                page_count = len(doc)
                ocr_pages = []
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_text = pytesseract.image_to_string(img)
                    if ocr_text.strip():
                        ocr_pages.append(ocr_text)
                if "\n\n".join(ocr_pages).strip():
                    text_content = "\n\n".join(ocr_pages)
                    extraction_method = "pytesseract_ocr"
                    is_ocr = True
                    logger.info(f"Successfully extracted {len(text_content)} chars via PyTesseract OCR.")
            except Exception as e_ocr:
                logger.warning(f"PyTesseract OCR fallback failed: {e_ocr}")

    except Exception as e:
        logger.error(f"PDF stream parsing error: {e}")
        text_content = ""

    cleaned = clean_text(text_content)
    report = evaluate_extraction_quality(
        cleaned,
        page_count=page_count,
        source_type="pdf",
        extraction_method=extraction_method,
        has_tables=has_tables,
        table_count=table_count,
        multi_column=multi_column,
        is_ocr=is_ocr
    )
    return cleaned, report
