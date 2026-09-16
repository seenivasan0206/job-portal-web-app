# -*- coding: utf-8 -*-
def generate_score_explanations(resume_data, jd_match=None, ml_result=None):
    """
    Generates transparent, explainable natural language rationale (+ / - drivers)
    explaining exactly why the ATS & Job Match scores were assigned.
    """
    positive_drivers = []
    negative_drivers = []

    skills = resume_data.get('skills', [])
    sections = resume_data.get('sections', {})
    entities = resume_data.get('entities', {})
    contacts = resume_data.get('contacts', {})

    # Skills Evaluation
    if len(skills) >= 10:
        positive_drivers.append(f"Strong technical breadth with {len(skills)} recognized industry skills detected.")
    elif len(skills) < 6:
        negative_drivers.append(f"Low skill count: only {len(skills)} recognized skills detected.")

    # Measurable Outcomes & Action Verbs
    metrics_cnt = entities.get('metrics_count', 0)
    if metrics_cnt >= 3:
        positive_drivers.append(f"Strong quantitative proof of work ({metrics_cnt} measurable outcome metrics identified).")
    else:
        negative_drivers.append("Limited quantitative metrics: experience bullets lack measurable business numbers or percentages.")

    verbs_cnt = len(entities.get('action_verbs', []))
    if verbs_cnt >= 6:
        positive_drivers.append(f"Active leadership voice utilizing {verbs_cnt} strong action verbs.")
    else:
        negative_drivers.append("Passive wording: experience descriptions rely on passive phrases instead of dynamic action verbs.")

    # Section Completeness
    if sections.get('summary') and sections.get('experience') and sections.get('education') and sections.get('skills'):
        positive_drivers.append("Complete core resume structure with all standard ATS sections present.")
    else:
        missing_sec = [k.title() for k, v in sections.items() if not v and k in ['summary', 'projects', 'certifications']]
        if missing_sec:
            negative_drivers.append(f"Missing recommended sections: {', '.join(missing_sec)}.")

    # JD Match Drivers
    if jd_match:
        matched_cnt = len(jd_match.get('matched_skills', []))
        missing_cnt = len(jd_match.get('missing_skills', []))
        if matched_cnt >= 3:
            positive_drivers.append(f"High keyword overlap matching {matched_cnt} core JD requirements ({', '.join(jd_match['matched_skills'][:3])}).")
        if missing_cnt > 0:
            sample_missing = ', '.join(jd_match['missing_skills'][:3])
            negative_drivers.append(f"Missing {missing_cnt} required JD skills ({sample_missing}).")
            
        sem_sim = jd_match.get('semantic_similarity', 0.0)
        if sem_sim >= 0.75:
            positive_drivers.append(f"Excellent semantic alignment ({int(sem_sim*100)}%) between your experience and target role responsibilities.")
        elif sem_sim < 0.5:
            negative_drivers.append(f"Low semantic similarity ({int(sem_sim*100)}%) against job description phrasing.")

    return {
        'positive_drivers': positive_drivers[:4],
        'negative_drivers': negative_drivers[:4],
        'confidence_level': (ml_result.get('confidence', 0.88) * 100) if ml_result else 90.0
    }
