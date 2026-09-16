# -*- coding: utf-8 -*-
import re

def evaluate_extraction_quality(
    text,
    page_count=1,
    source_type="pdf",
    extraction_method="primary",
    has_tables=False,
    table_count=0,
    multi_column=False,
    is_ocr=False
):

    """
    Evaluates extraction quality (0–100%) and generates a comprehensive diagnostic report.
    Checks character density, broken words, non-printable characters, readable words, and extraction confidence.
    """
    if not text or not text.strip():
        return {
            'quality_score': 0,
            'confidence_score': 0.0,
            'status': 'Failed',
            'source_type': source_type,
            'extraction_method': extraction_method,
            'word_count': 0,
            'char_count': 0,
            'page_count': page_count,
            'chars_per_page': 0,
            'has_tables': False,
            'table_count': 0,
            'multi_column': False,
            'is_ocr': is_ocr,
            'issues': ['No text could be extracted from document. Document may be an empty or unsupported image scan.']
        }

    char_count = len(text)
    words = text.split()
    word_count = len(words)
    chars_per_page = char_count / max(1, page_count)

    issues = []
    deductions = 0

    # 1. Check text density per page
    if chars_per_page < 120:
        issues.append('Very low text density per page (< 120 characters). Content may be clipped or poorly rendered.')
        deductions += 40
    elif chars_per_page < 300:
        issues.append('Moderate text density. Some sidebar or multi-column text may be omitted.')
        deductions += 15

    # 2. Check for non-printable or corrupted characters
    non_ascii_or_control = len(re.findall(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', text))
    if non_ascii_or_control > 20:
        issues.append('Significant non-printable or corrupted character encoding detected.')
        deductions += 20
    elif non_ascii_or_control > 5:
        issues.append('Minor corrupted font characters detected.')
        deductions += 10

    # 3. Check for broken or fragmented words (e.g. single letters with spaces: "E x p e r i e n c e")
    spaced_letters = len(re.findall(r'\b[a-zA-Z]\s+[a-zA-Z]\s+[a-zA-Z]\b', text))
    if spaced_letters > 4:
        issues.append('Spaced-out character artifact detected in headings.')
        deductions += 10

    # 4. Check for standard sections
    lower = text.lower()
    found_core_sec = sum(1 for sec in ['experience', 'education', 'skills', 'summary', 'projects', 'certifications'] if sec in lower)
    if found_core_sec < 2:
        issues.append('Fewer than 2 standard section keywords identified in extracted text.')
        deductions += 20

    # 5. Check dictionary words ratio / gibberish detection
    clean_words = [w for w in words if re.match(r'^[a-zA-Z]{2,}$', w)]
    clean_word_ratio = len(clean_words) / max(1, word_count)
    if clean_word_ratio < 0.60:
        issues.append('High proportion of non-standard symbols or fragmented tokens.')
        deductions += 15

    # 6. OCR specific note
    if is_ocr:
        issues.append('Document was extracted via Optical Character Recognition (OCR).')

    quality_score = max(10, min(100, 100 - deductions))
    confidence_score = round(min(0.99, max(0.10, (quality_score / 100.0) * (0.95 if is_ocr else 1.0))), 2)

    if quality_score >= 88:
        status = 'Excellent'
    elif quality_score >= 70:
        status = 'Good'
    elif quality_score >= 50:
        status = 'Fair'
    else:
        status = 'Poor'

    return {
        'quality_score': quality_score,
        'confidence_score': confidence_score,
        'status': status,
        'source_type': source_type,
        'extraction_method': extraction_method,
        'word_count': word_count,
        'char_count': char_count,
        'page_count': page_count,
        'chars_per_page': int(chars_per_page),
        'has_tables': has_tables,
        'table_count': table_count,
        'multi_column': multi_column,
        'is_ocr': is_ocr,
        'issues': issues
    }


# Alias for backwards compatibility
compute_extraction_quality = evaluate_extraction_quality

