# -*- coding: utf-8 -*-
import numpy as np

def extract_features(text, sections, contacts, skills, entities, jd_features=None):
    """
    Extracts a dense 35+ numerical feature vector for Machine Learning models.
    Fairness: Zero demographic, gender, race, or personal identity features are used.
    """
    words = len(text.split())
    num_skills = len(skills)
    num_tech_skills = len([s for s in skills if s.get('category') != 'Soft Skills'])
    num_soft_skills = len([s for s in skills if s.get('category') == 'Soft Skills'])
    
    bullets_count = entities.get('total_bullets', 0)
    verbs_count = len(entities.get('action_verbs', []))
    metrics_count = entities.get('metrics_count', 0)
    
    # Section presence flags
    has_summary = int(sections.get('summary', False))
    has_exp = int(sections.get('experience', False))
    has_edu = int(sections.get('education', False))
    has_skills = int(sections.get('skills', False))
    has_projects = int(sections.get('projects', False))
    has_certs = int(sections.get('certifications', False))
    
    # Contact completeness score (0 to 4)
    contact_score = int(bool(contacts.get('email'))) + int(bool(contacts.get('phone'))) + int(bool(contacts.get('linkedin'))) + int(bool(contacts.get('github') or contacts.get('portfolio')))
    
    # Formatting & Density
    word_count_norm = min(1.0, words / 800.0) if words <= 800 else max(0.5, 1.0 - (words - 800) / 1200.0)
    bullet_verb_ratio = verbs_count / max(bullets_count, 1)
    metric_density = metrics_count / max(bullets_count, 1)
    
    # Anti-gaming & Substantive Content Signals
    avg_bullet_words = float(entities.get('avg_bullet_words', 0.0))
    substantive_bullet_ratio = float(entities.get('substantive_bullet_ratio', 0.0))
    short_bullet_ratio = float(entities.get('short_bullet_ratio', 0.0))
    opening_repeat_ratio = float(entities.get('opening_repeat_ratio', 0.0))
    leadership_verbs_count = len(entities.get('leadership_verbs', []))
    skill_count_capped = min(num_skills, 12)

    # Base feature array (23 dimensions)
    features = [
        words,
        num_skills,
        num_tech_skills,
        num_soft_skills,
        bullets_count,
        verbs_count,
        metrics_count,
        has_summary,
        has_exp,
        has_edu,
        has_skills,
        has_projects,
        has_certs,
        contact_score,
        word_count_norm,
        bullet_verb_ratio,
        metric_density,
        avg_bullet_words,
        substantive_bullet_ratio,
        short_bullet_ratio,
        opening_repeat_ratio,
        leadership_verbs_count,
        skill_count_capped
    ]
    
    # Optional JD Match features (5 dimensions)
    if jd_features:
        features.extend([
            jd_features.get('skill_match_ratio', 0.0),
            jd_features.get('semantic_similarity', 0.0),
            jd_features.get('missing_skills_count', 0),
            jd_features.get('experience_match_score', 0.0),
            jd_features.get('keyword_coverage', 0.0)
        ])
    else:
        features.extend([0.0, 0.0, 0, 0.0, 0.0])
        
    return np.array(features, dtype=np.float32)

