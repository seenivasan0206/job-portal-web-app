# -*- coding: utf-8 -*-
import re

SECTION_PATTERNS = {
    'summary': r'\b(professional summary|summary|about me|career summary|profile|objective|career objective|executive summary)\b',
    'experience': r'\b(experience|work experience|employment|professional experience|work history|employment history|internships)\b',
    'education': r'\b(education|academic background|qualifications|academic history|degrees|university|college)\b',
    'skills': r'\b(skills|technical skills|key skills|core competencies|technologies|tools & technologies|skill set)\b',
    'projects': r'\b(projects|personal projects|academic projects|key projects|portfolio projects)\b',
    'certifications': r'\b(certifications|certificates|licenses|courses|accreditations|credentials)\b',
    'achievements': r'\b(achievements|awards|honors|accomplishments|publications|patents)\b',
    'languages': r'\b(languages|languages spoken|language proficiency)\b'
}

MANDATORY_SECTIONS = ['experience', 'education', 'skills']
RECOMMENDED_SECTIONS = ['summary', 'projects', 'certifications']

def detect_sections(text):
    """
    Detect standard and semantic resume sections.
    Returns dictionary with detected flags, missing sections, and section completeness metrics.
    """
    lower_text = text.lower()
    detected = {sec: bool(re.search(pat, lower_text)) for sec, pat in SECTION_PATTERNS.items()}
    if '@' in text or re.search(r'\b\d{10}\b', text):
        detected['contact'] = True
    else:
        detected['contact'] = False

    detected['missing_mandatory'] = [s for s in MANDATORY_SECTIONS if not detected.get(s)]
    detected['missing_recommended'] = [s for s in RECOMMENDED_SECTIONS if not detected.get(s)]
    detected['total_detected_count'] = sum(1 for k in SECTION_PATTERNS if detected.get(k)) + (1 if detected.get('contact') else 0)

    return detected
