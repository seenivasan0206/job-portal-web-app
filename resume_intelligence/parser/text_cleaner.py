# -*- coding: utf-8 -*-
import re
import unicodedata

def clean_text(text):
    """Normalize unicode, whitespace, linebreaks, null bytes, and non-printable characters."""
    if not text:
        return ""
    text = text.replace('\x00', '')
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[\u2022\u2023\u25E6\u2043\u2219\u25CF\u25CB\u25A0\u25AA]', ' • ', text)
    text = re.sub(r'[\u2018\u2019]', "'", text)
    text = re.sub(r'[\u201C\u201D]', '"', text)
    text = re.sub(r'[\u2013\u2014]', '-', text)
    # Fix spaced out heading artifacts e.g. "S k i l l s" -> "Skills" or "E X P E R I E N C E" -> "EXPERIENCE"
    text = re.sub(r'\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b', lambda m: m.group(0).replace(' ', ''), text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()



# Alias for backwards compatibility
clean_extracted_text = clean_text

