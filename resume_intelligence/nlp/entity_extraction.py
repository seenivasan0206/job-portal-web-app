# -*- coding: utf-8 -*-
import re
from datetime import datetime

ACTION_VERBS = [
    'achieved', 'accelerated', 'administered', 'analyzed', 'architected',
    'automated', 'built', 'championed', 'collaborated', 'configured',
    'coordinated', 'created', 'customized', 'decreased', 'delivered',
    'deployed', 'designed', 'developed', 'devised', 'directed',
    'engineered', 'enhanced', 'established', 'executed', 'expanded',
    'expedited', 'facilitated', 'formulated', 'generated', 'guided',
    'headed', 'implemented', 'improved', 'increased', 'initiated',
    'innovated', 'installed', 'instituted', 'integrated', 'introduced',
    'launched', 'led', 'managed', 'maximized', 'mentored', 'minimized',
    'modernized', 'negotiated', 'optimized', 'orchestrated', 'organized',
    'overhauled', 'oversaw', 'pioneered', 'planned', 'produced',
    'programmed', 'reduced', 'refactored', 'resolved', 'restructured',
    'revamped', 'scaled', 'simplified', 'spearheaded', 'streamlined',
    'strengthened', 'structured', 'supervised', 'surpassed', 'transformed',
    'troubleshot', 'upgraded', 'validated'
]

COMMON_EMAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com',
    'protonmail.com', 'proton.me', 'mail.com', 'zoho.com', 'yandex.com',
    'aol.com', 'gmx.com', 'live.com', 'msn.com', 'me.com', 'mac.com'
}

def extract_contacts(text):
    """Extract candidate email, phone, location, and social links with validation."""
    email_pat = r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b'
    phone_pat = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\b[6-9]\d{9}\b'
    linkedin_pat = r'(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+'
    github_pat = r'(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9_-]+'
    portfolio_pat = r'(?:https?://)?(?:www\.)?[a-zA-Z0-9_-]+\.(?:io|dev|com|me|tech)/?[a-zA-Z0-9_-]*'

    email = re.findall(email_pat, text)
    phone = re.findall(phone_pat, text)
    linkedin = re.findall(linkedin_pat, text, re.IGNORECASE)
    github = re.findall(github_pat, text, re.IGNORECASE)

    # 1. Strip all matched emails from text before running portfolio regex
    text_without_emails = re.sub(email_pat, ' ', text)
    portfolio = re.findall(portfolio_pat, text_without_emails, re.IGNORECASE)

    # 2. Extract domain part of candidate's own emails
    extracted_email_domains = {e.split('@')[-1].lower().strip() for e in email if '@' in e}

    # 3. Filter portfolio matches against email domains, common providers, and standard social networks
    clean_portfolio = []
    for p in portfolio:
        p_clean = p.strip().rstrip('.,;:')
        p_lower = p_clean.lower()
        # Extract host/domain part
        host = re.sub(r'^https?://', '', p_lower)
        host = re.sub(r'^www\.', '', host)
        domain = host.split('/')[0].strip()

        if domain in COMMON_EMAIL_DOMAINS:
            continue
        if domain in extracted_email_domains:
            continue
        if 'linkedin.com' in domain or 'github.com' in domain or 'gitlab.com' in domain:
            continue
        clean_portfolio.append(p_clean)

    loc_match = re.search(r'\b(Bangalore|Bengaluru|Chennai|Hyderabad|Pune|Mumbai|Delhi|Noida|Gurgaon|Coimbatore|Madurai|Kochi|Kolkata|Ahmedabad|San Francisco|New York|London|Singapore|Remote|India|USA|UK)\b', text, re.IGNORECASE)

    # Contact Completeness Score (0 - 100)
    score = 0
    if email: score += 35
    if phone: score += 25
    if linkedin: score += 20
    if github or clean_portfolio: score += 10
    if loc_match: score += 10

    return {
        'email': email[0] if email else None,
        'phone': phone[0] if phone else None,
        'linkedin': linkedin[0] if linkedin else None,
        'github': github[0] if github else None,
        'portfolio': clean_portfolio[0] if clean_portfolio else None,
        'location': loc_match.group(0).title() if loc_match else None,
        'contact_score': score
    }

def extract_candidate_name(text):
    """Extract candidate full name from top header block."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return 'Candidate'
    stop_words = {'resume', 'curriculum', 'vitae', 'cv', 'profile', 'contact', 'email', 'phone', 'page', 'senior', 'junior', 'lead', 'developer', 'engineer', 'analyst', 'manager'}
    for line in lines[:5]:
        if '@' in line or re.search(r'\d{5,}', line) or 'http' in line or 'linkedin.com' in line:
            continue
        cleaned = re.sub(r'[^a-zA-Z\s]', '', line).strip()
        words = cleaned.split()
        if 2 <= len(words) <= 4 and not any(w.lower() in stop_words for w in words):
            return cleaned.title()
    return lines[0][:40].strip().title() if lines else 'Candidate'

def evaluate_date_consistency_and_timeline(text):
    """
    Parses dates to verify formatting consistency, chronological order, and suspicious gaps.
    """
    # Patterns for Month Year or Year only (e.g. "Jan 2021 - Present", "2019 - 2022", "06/2020 - 08/2023")
    date_patterns = [
        r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b',
        r'\b\d{1,2}/\d{4}\b',
        r'\b(?:19|20)\d{2}\s*[-–—to]+\s*(?:(?:19|20)\d{2}|Present|Current)\b',
        r'\b(?:19|20)\d{2}\b'
    ]
    found_dates = []
    for pat in date_patterns:
        found_dates.extend(re.findall(pat, text, re.IGNORECASE))

    date_count = len(found_dates)
    has_dates = date_count >= 2
    consistent_format = True
    
    # Check if mixed formats are present
    has_slash = bool(re.search(r'\d{1,2}/\d{4}', text))
    has_named_month = bool(re.search(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}', text, re.IGNORECASE))
    if has_slash and has_named_month:
        consistent_format = False

    date_score = 95 if (has_dates and consistent_format) else (75 if has_dates else 45)

    return {
        'date_count': date_count,
        'has_dates': has_dates,
        'consistent_format': consistent_format,
        'date_score': date_score
    }

LEADERSHIP_VERBS = {
    'Architected', 'Championed', 'Directed', 'Guided', 'Headed',
    'Innovated', 'Led', 'Mentored', 'Orchestrated', 'Oversaw',
    'Pioneered', 'Scaled', 'Spearheaded', 'Transformed'
}

def extract_metrics_and_verbs(text):
    """
    Extracts action verbs and rigorously detects quantified achievements with evidence.
    Includes anti-gaming signals: bullet length, repetition detection, and verb diversity.
    """
    lower = text.lower()
    found_verbs = set()
    for v in ACTION_VERBS:
        if re.search(r'\b' + re.escape(v) + r'\b', lower):
            found_verbs.add(v.capitalize())

    metric_patterns = [
        r'\b\d+(?:\.\d+)?%',
        r'\$\d+(?:,\d{3})*(?:\.\d+)?[kKmMbB]?\b',
        r'(?:₹|rs\.?|inr)\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:lpa|cr|k|lakhs?|crores?)?\b',
        r'\b\d+(?:\.\d+)?x\b',
        r'\b\d{1,3}(?:,\d{3})+\b',
        r'\b\d+\+\s*(?:users|records|clients|queries|requests|members|features|systems|endpoints|transactions|pipelines|models|jobs|customers)\b',
        r'\b\d+(?:\.\d+)?\s*(?:ms|milliseconds|seconds|mins|hours|days)\b',
        r'\b(?:increased|decreased|reduced|saved|grew|boosted|improved)\b(?:\s+\w+){0,4}?\s+(?:by\s+)?\d+(?:\.\d+)?%?',
    ]
    
    # Collect all match spans and deduplicate overlapping spans
    spans = []
    for pat in metric_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            spans.append((m.start(), m.end(), m.group(0).strip()))

    # Sort spans by start position, taking longer matches first on ties
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    merged_metrics = []
    last_end = -1
    for start, end, val in spans:
        if start >= last_end:
            merged_metrics.append(val)
            last_end = end

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    bullets = [l.lstrip('-•*–— 0123456789.').strip() for l in lines if l.startswith(('-', '•', '*', '–', '—', '1.', '2.', '3.')) or (len(l) > 30 and any(l.lower().startswith(v) for v in ACTION_VERBS))]

    # Count how many bullets contain numbers/metrics
    quantified_bullets = [b for b in bullets if any(re.search(p, b, re.IGNORECASE) for p in metric_patterns) or re.search(r'\b\d+\b', b)]
    quantified_ratio = (len(quantified_bullets) / max(1, len(bullets)))

    # Anti-gaming & substantive quality signals
    bullet_word_counts = [len(b.split()) for b in bullets] if bullets else [0]
    avg_bullet_words = sum(bullet_word_counts) / max(1, len(bullets)) if bullets else 0.0
    short_bullets = [b for b in bullets if len(b.split()) < 6]
    substantive_bullets = [b for b in bullets if len(b.split()) >= 8]
    
    short_bullet_ratio = len(short_bullets) / max(1, len(bullets)) if bullets else 0.0
    substantive_bullet_ratio = len(substantive_bullets) / max(1, len(bullets)) if bullets else 0.0

    # Check bullet opening verb repetition (e.g. starting 5 bullets with 'Increased')
    opening_words = [b.split()[0].lower() for b in bullets if b.split()]
    max_opening_repeat = max([opening_words.count(w) for w in set(opening_words)]) if opening_words else 0
    opening_repeat_ratio = max_opening_repeat / max(1, len(bullets)) if bullets else 0.0

    leadership_verbs = [v for v in found_verbs if v in LEADERSHIP_VERBS]

    return {
        'action_verbs': sorted(list(found_verbs)),
        'leadership_verbs': sorted(leadership_verbs),
        'metrics_count': len(merged_metrics),
        'metrics_samples': list(set(merged_metrics))[:6],
        'total_bullets': len(bullets),
        'quantified_bullets_count': len(quantified_bullets),
        'quantified_ratio': round(quantified_ratio, 2),
        'avg_bullet_words': round(avg_bullet_words, 1),
        'short_bullet_ratio': round(short_bullet_ratio, 2),
        'substantive_bullet_ratio': round(substantive_bullet_ratio, 2),
        'opening_repeat_ratio': round(opening_repeat_ratio, 2),
        'sample_bullets': bullets[:5]
    }

