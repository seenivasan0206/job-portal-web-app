# -*- coding: utf-8 -*-
import re
from .skill_normalization import SKILL_TAXONOMY, normalize_skill

def extract_skills_with_confidence(text):
    """
    Extract skills using token-aware taxonomy matching with confidence scoring.
    Returns list of dicts: [{'skill': 'Python', 'category': 'Programming Languages', 'confidence': 0.98, 'count': 4}]
    """
    if not text:
        return []
    
    lower_text = text.lower()
    found_skills = {}
    
    sorted_keys = sorted(SKILL_TAXONOMY.keys(), key=len, reverse=True)
    
    for key in sorted_keys:
        meta = SKILL_TAXONOMY[key]
        canonical = meta['canonical']
        category = meta['category']
        
        escaped = re.escape(key)
        if key in ['c++', 'c#', '.net', 'next.js', 'node.js', 'vue.js', 'express.js', 'ci/cd', 'asp.net']:
            pattern = r'(?:^|[\s,;:\(\)\[\]/|•\n])' + escaped + r'(?:$|[\s,;:\(\)\[\]/|•\n])'
        elif key in ['c', 'r']:
            pattern = r'(?:^|[\s/|•\n])(?:' + key.upper() + r')(?:[,\s\n\.\)\(\]\[/|•]|$)'
        else:
            pattern = r'(?:^|[\s,;:\(\)\[\]/|•\n])' + escaped + r'(?:$|[\s,;:\(\)\[\]/|•\n])'
            
        matches = re.findall(pattern, lower_text)
        if matches:
            count = len(matches)
            confidence = min(0.99, 0.92 + (0.02 * min(count, 3)))
            if canonical not in found_skills:
                found_skills[canonical] = {
                    'skill': canonical,
                    'category': category,
                    'confidence': round(confidence, 2),
                    'count': count
                }
            else:
                found_skills[canonical]['count'] += count

    return sorted(list(found_skills.values()), key=lambda x: x['count'], reverse=True)
