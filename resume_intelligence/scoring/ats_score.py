# -*- coding: utf-8 -*-
from ..ml.feature_engineering import extract_features
from ..ml.ats_model import predict_ats_compatibility

def compute_hybrid_ats_and_quality_scores(resume_text, sections, contacts, skills, entities, date_info, extraction_report, jd_match=None):
    """
    Rigorously computes separate, calibrated scores:
    1. ATS Compatibility Score (0–100): Machine readability, extraction quality, structure, contacts, dates.
    2. Resume Quality Score (0–100): Content depth, action verbs, quantified achievements, readability.
    3. Job Match Score (0–100%): When JD provided.
    4. Overall Calibrated Resume Intelligence Score (0–100).
    """
    words = len(resume_text.split())
    num_skills = len(skills)
    verbs_cnt = len(entities.get('action_verbs', []))
    metrics_cnt = entities.get('metrics_count', 0)
    quantified_ratio = entities.get('quantified_ratio', 0.0)
    extraction_score = extraction_report.get('quality_score', 90)
    date_score = date_info.get('date_score', 85)
    contact_score = contacts.get('contact_score', 80)

    # ---------------------------------------------------------
    # 1. ATS COMPATIBILITY SCORE (0–100)
    # ---------------------------------------------------------
    # Evaluates whether ATS robots can parse and extract clean data
    sec_pts = 0
    if sections.get('experience'): sec_pts += 25
    if sections.get('education'): sec_pts += 20
    if sections.get('skills'): sec_pts += 20
    if sections.get('summary'): sec_pts += 15
    if sections.get('projects') or sections.get('certifications'): sec_pts += 10
    if sections.get('contact', True): sec_pts += 10
    
    # Format penalty for extreme word counts (too short or 5-page bloated resumes)
    format_pts = 100
    if words < 200: format_pts = 50
    elif words > 1800: format_pts = 70
    elif words < 350: format_pts = 80

    # ATS Compatibility is a weighted composite of machine readability factors:
    ats_compatibility_score = int(round(
        (extraction_score * 0.30) +
        (sec_pts * 0.30) +
        (contact_score * 0.15) +
        (date_score * 0.15) +
        (format_pts * 0.10)
    ))
    ats_compatibility_score = max(20, min(98, ats_compatibility_score))

    # ---------------------------------------------------------
    # 2. RESUME QUALITY SCORE (0–100)
    # ---------------------------------------------------------
    # Evaluates content depth, quantifiable impact, and professional writing
    # Anti-gaming signals from NLP entity extraction:
    avg_bullet_words = float(entities.get('avg_bullet_words', 0.0))
    substantive_bullet_ratio = float(entities.get('substantive_bullet_ratio', 0.0))
    short_bullet_ratio = float(entities.get('short_bullet_ratio', 0.0))
    opening_repeat_ratio = float(entities.get('opening_repeat_ratio', 0.0))
    leadership_verbs = entities.get('leadership_verbs', [])
    leadership_cnt = len(leadership_verbs)

    # Base writing score with leadership bonus:
    leadership_bonus = min(20, leadership_cnt * 5)
    action_verb_pts = min(100, (verbs_cnt * 10) + leadership_bonus)

    # Quantified metric points with anti-gaming checks & substantive prose baseline:
    if metrics_cnt == 0:
        # Check if candidate demonstrates senior substantive prose (strong leadership + deep bullets)
        if (verbs_cnt >= 4 or leadership_cnt >= 2) and avg_bullet_words >= 9 and substantive_bullet_ratio >= 0.6:
            metric_pts = 60  # Substantive senior leadership prose baseline
        elif verbs_cnt >= 2 and avg_bullet_words >= 7:
            metric_pts = 45
        else:
            metric_pts = 25  # Generic unquantified junior bullet points
    elif metrics_cnt <= 2:
        metric_pts = 55
    elif metrics_cnt <= 5:
        metric_pts = 80
    else:
        metric_pts = 95

    # Anti-gaming penalties:
    # 1. Repetition penalty: identical opening verbs/structure across bullets
    repetition_penalty = 0
    if opening_repeat_ratio > 0.35 and entities.get('total_bullets', 0) >= 3:
        repetition_penalty = int(round((opening_repeat_ratio - 0.30) * 45))

    # 2. Stub bullet penalty: extremely short bullets (< 6 words) paired with bare metrics
    stub_penalty = 0
    if avg_bullet_words < 6.0 and entities.get('total_bullets', 0) >= 3:
        stub_penalty = 25
    elif avg_bullet_words < 8.0 and entities.get('total_bullets', 0) >= 3:
        stub_penalty = 12

    metric_pts = max(25, metric_pts - repetition_penalty - stub_penalty)

    # Skill breadth points with aggressive plateau around 10-12 skills and padding penalty:
    if num_skills <= 10:
        skill_pts = num_skills * 8.5
    elif num_skills <= 14:
        skill_pts = 85 + (num_skills - 10) * 2.5  # 10->85, 12->90, 14->95
    elif num_skills <= 18:
        skill_pts = 95 + (num_skills - 14) * 1.0  # 18->99
    else:
        # Penalty for keyword stuffed lists (19+ skills with generic buzzwords)
        skill_pts = max(75, 95 - (num_skills - 18) * 2.5)
    skill_pts = int(round(min(100, max(0, skill_pts))))

    # Bullet quality points:
    bullet_pts = int(round(quantified_ratio * 100))

    resume_quality_score = int(round(
        (metric_pts * 0.35) +
        (action_verb_pts * 0.25) +
        (skill_pts * 0.25) +
        (sec_pts * 0.15)
    ))
    resume_quality_score = max(15, min(96, resume_quality_score))

    # ---------------------------------------------------------
    # 3. FEATURE ENGINEERING & CALIBRATED ML MODEL
    # ---------------------------------------------------------
    # When NO JD is provided, pass strictly None/zeros (never fake high JD values!)
    jd_feats = None
    if jd_match:
        jd_feats = {
            'skill_match_ratio': jd_match.get('required_match_ratio', 0.5),
            'semantic_similarity': jd_match.get('semantic_similarity', 0.5),
            'missing_skills_count': jd_match.get('missing_count', 0),
            'experience_match_score': 0.7,
            'keyword_coverage': jd_match.get('required_match_ratio', 0.5)
        }

    feat_vector = extract_features(resume_text, sections, contacts, skills, entities, jd_feats)
    ml_result = predict_ats_compatibility(feat_vector)
    ml_predicted_score = ml_result['predicted_score']

    # ---------------------------------------------------------
    # 4. OVERALL RESUME INTELLIGENCE SCORE (CALIBRATED BLEND)
    # ---------------------------------------------------------
    if jd_match:
        # Blended with Job Description Match (Weights sum to 1.00):
        # - 25% ats_compatibility_score: Machine readability, structural layout, contact details, date consistency
        # - 30% resume_quality_score: Content depth, action verbs, quantified achievements, substance vs fluff
        # - 20% ml_predicted_score: Calibrated Machine Learning gradient boosting regressor benchmark
        # - 25% jd_match_score: Core required skills match ratio & dense semantic similarity to target job
        overall_score = int(round(
            (ats_compatibility_score * 0.25) +
            (resume_quality_score * 0.30) +
            (ml_predicted_score * 0.20) +
            (jd_match['jd_match_score'] * 0.25)
        ))
    else:
        # Pure Resume Quality & ATS Readiness without Job Description (Weights sum to 1.00):
        # - 35% ats_compatibility_score: Machine readability, structural layout, contact details, date consistency
        # - 40% resume_quality_score: Content depth, action verbs, quantified achievements, substance vs fluff
        # - 25% ml_predicted_score: Calibrated Machine Learning gradient boosting regressor benchmark
        overall_score = int(round(
            (ats_compatibility_score * 0.35) +
            (resume_quality_score * 0.40) +
            (ml_predicted_score * 0.25)
        ))

    overall_score = max(15, min(96, overall_score))

    # Determine Realistic Tier
    if overall_score >= 82:
        tier_name = 'Excellent Fit'
        tier_class = 'success'
    elif overall_score >= 70:
        tier_name = 'Good Fit'
        tier_class = 'info'
    elif overall_score >= 52:
        tier_name = 'Moderate Fit'
        tier_class = 'warning'
    else:
        tier_name = 'Needs Improvement'
        tier_class = 'danger'

    score_breakdown = {
        'ats_compatibility': ats_compatibility_score,
        'resume_quality': resume_quality_score,
        'ml_predicted_score': ml_predicted_score,
        'extraction_quality': extraction_score,
        'quantified_impact': metric_pts,
        'action_verbs_strength': action_verb_pts,
        'section_structure': sec_pts,
        'contact_completeness': contact_score,
        'date_consistency': date_score,
        'job_description_match': jd_match['jd_match_score'] if jd_match else None
    }

    return {
        'overall_score': overall_score,
        'ats_score': ats_compatibility_score,
        'resume_quality_score': resume_quality_score,
        'ml_predicted_score': ml_predicted_score,
        'job_match_score': jd_match['jd_match_score'] if jd_match else None,
        'tier_name': tier_name,
        'tier_class': tier_class,
        'ml_confidence': ml_result['confidence'],
        'model_version': ml_result['model_version'],
        'model_metrics': ml_result.get('model_metrics', {}),
        'score_breakdown': score_breakdown,
        'extraction_report': extraction_report,
        'date_info': date_info
    }

