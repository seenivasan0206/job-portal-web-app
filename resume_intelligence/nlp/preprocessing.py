# -*- coding: utf-8 -*-
import re

PROTECTED_TOKENS = {
    'c++', 'c#', '.net', '.net core', 'asp.net', 'node.js', 'react.js', 'vue.js',
    'next.js', 'express.js', 'power bi', 'powerbi', 'sql server', 'ci/cd', 'tcp/ip',
    'rest api', 'restful apis', 'three.js', 'd3.js', 'scikit-learn'
}

def tokenize_words(text):
    """Tokenize words preserving technical programming tokens and compounds."""
    if not text:
        return []
    token_map = {}
    lower_text = text.lower()
    for idx, pt in enumerate(sorted(PROTECTED_TOKENS, key=len, reverse=True)):
        placeholder = f"__TOKEN_{idx}__"
        if pt in lower_text:
            lower_text = lower_text.replace(pt, placeholder)
            token_map[placeholder] = pt
            
    tokens = re.findall(r'[a-zA-Z0-9_\-]+|__TOKEN_\d+__', lower_text)
    final_tokens = [token_map.get(t, t) for t in tokens]
    return final_tokens

def extract_sentences(text):
    """Split text into sentences while respecting bullet lists."""
    if not text:
        return []
    raw_sentences = re.split(r'[\n\r]+|[.!?]\s+', text)
    return [s.strip() for s in raw_sentences if len(s.strip()) > 5]
