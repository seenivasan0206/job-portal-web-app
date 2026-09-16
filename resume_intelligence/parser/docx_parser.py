# -*- coding: utf-8 -*-
import io
import logging
from docx import Document
from .text_cleaner import clean_text
from .extraction_quality import evaluate_extraction_quality

logger = logging.getLogger(__name__)

def parse_docx(stream):
    """Extract text from DOCX stream including paragraphs and tables with formatting audit."""
    try:
        stream.seek(0)
        raw_bytes = stream.read()
        byte_io = io.BytesIO(raw_bytes)
        doc = Document(byte_io)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        table_cells = []
        table_count = len(doc.tables)
        for table in doc.tables:
            for row in table.rows:
                row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_texts:
                    table_cells.append(" | ".join(row_texts))
        full_text = "\n\n".join(paragraphs + table_cells)
        cleaned = clean_text(full_text)
        report = evaluate_extraction_quality(
            cleaned,
            page_count=max(1, len(paragraphs) // 25 + max(1, table_count // 3)),
            source_type="docx",
            extraction_method="python-docx",
            has_tables=(table_count > 0),
            table_count=table_count,
            multi_column=False,
            is_ocr=False
        )
        return cleaned, report
    except Exception as e:
        logger.error(f"DOCX parsing error: {e}")
        return "", evaluate_extraction_quality("", page_count=1, source_type="docx", extraction_method="python-docx")
