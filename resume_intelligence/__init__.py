import time
import logging
from .parser.pdf_parser import parse_pdf
from .parser.docx_parser import parse_docx
from .parser.text_cleaner import clean_text
from .parser.extraction_quality import evaluate_extraction_quality
from .nlp.section_detection import detect_sections
from .nlp.entity_extraction import (
    extract_contacts,
    extract_candidate_name,
    extract_metrics_and_verbs,
    evaluate_date_consistency_and_timeline
)
from .nlp.skill_extraction import extract_skills_with_confidence
from .scoring.job_match_score import analyze_and_match_job_description
from .scoring.ats_score import compute_hybrid_ats_and_quality_scores
from .scoring.explainability import generate_score_explanations
from .recommendations.recommendation_engine import (
    detect_issues_and_recommendations,
    generate_ai_section_enhancements,
    generate_action_plan
)

logger = logging.getLogger(__name__)

def extract_resume_text_with_report(stream, filename):
    """Extract plain text and return diagnostic extraction report."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext == 'pdf':
        return parse_pdf(stream)
    elif ext == 'docx':
        return parse_docx(stream)
    elif ext == 'txt':
        try:
            stream.seek(0)
            txt = clean_text(stream.read().decode('utf-8', errors='ignore'))
            return txt, evaluate_extraction_quality(txt, page_count=1, source_type="txt", extraction_method="plain_text")
        except Exception:
            return '', evaluate_extraction_quality('', page_count=1, source_type="txt", extraction_method="plain_text")
    return '', evaluate_extraction_quality('', page_count=1, source_type="unknown")

def analyze_resume_pipeline(stream, filename, job_description=None):
    """
    Master pipeline executing Calibrated ML & NLP Resume Intelligence analysis.
    Produces calibrated ATS Compatibility, Resume Quality, and Job Match scores
    alongside diagnostic reports, explainable drivers, and timing telemetry.
    """
    t0 = time.time()
    
    # 1. Extraction Stage
    t_ext_start = time.time()
    text, extraction_report = extract_resume_text_with_report(stream, filename)
    t_ext_end = time.time()
    extraction_time_ms = int((t_ext_end - t_ext_start) * 1000)

    if not text or len(text.strip()) < 20:
        return {
            'success': False,
            'message': 'Unable to extract text from the uploaded file. Please ensure it is not an empty or unsupported image document.',
            'extraction_report': extraction_report
        }

    # 2. NLP Information Extraction Stage
    t_nlp_start = time.time()
    candidate_name = extract_candidate_name(text)
    contacts = extract_contacts(text)
    sections = detect_sections(text)
    skills = extract_skills_with_confidence(text)
    entities = extract_metrics_and_verbs(text)
    date_info = evaluate_date_consistency_and_timeline(text)
    t_nlp_end = time.time()
    nlp_time_ms = int((t_nlp_end - t_nlp_start) * 1000)

    # 3. Multi-Signal Job Description Matching (if provided) & ML Inference
    t_inf_start = time.time()
    jd_match = analyze_and_match_job_description(text, skills, job_description) if job_description else None

    # 4. Calibrated Multi-Score Engine
    scoring_result = compute_hybrid_ats_and_quality_scores(
        text, sections, contacts, skills, entities, date_info, extraction_report, jd_match
    )
    t_inf_end = time.time()
    inference_time_ms = int((t_inf_end - t_inf_start) * 1000)

    # 5. Evidence-Based Issue Detection & AI Rewrites
    issues = detect_issues_and_recommendations(
        text, sections, contacts, skills, entities, date_info, extraction_report, jd_match
    )
    ai_enhancements = generate_ai_section_enhancements(skills, entities, candidate_name)
    action_plan = generate_action_plan(issues, jd_match)

    # 6. Explainable AI Driver Explanations
    resume_meta = {'skills': skills, 'sections': sections, 'entities': entities, 'contacts': contacts}
    explanations = generate_score_explanations(resume_meta, jd_match, scoring_result)

    skill_names = [s['skill'] for s in skills]
    total_time_ms = int((time.time() - t0) * 1000)

    return {
        'success': True,
        'filename': filename,
        'candidate_name': candidate_name,
        'overall_score': scoring_result['overall_score'],
        'ats_score': scoring_result['ats_score'],
        'resume_quality_score': scoring_result['resume_quality_score'],
        'job_match_score': jd_match['jd_match_score'] if jd_match else None,
        'rating_tier': scoring_result['tier_name'],
        'rating_class': scoring_result['tier_class'],
        'ml_confidence': scoring_result['ml_confidence'],
        'model_version': scoring_result['model_version'],
        'score_breakdown': scoring_result['score_breakdown'],
        'extraction_report': extraction_report,
        'date_info': date_info,
        'word_count': len(text.split()),
        'has_job_description': bool(jd_match),
        'jd_match': jd_match,
        'meta': {
            'extraction_time_ms': extraction_time_ms,
            'nlp_time_ms': nlp_time_ms,
            'inference_time_ms': inference_time_ms,
            'total_time_ms': total_time_ms,
            'extraction_method': extraction_report.get('extraction_method', 'primary'),
            'extraction_confidence': extraction_report.get('confidence_score', 0.95),
            'has_tables': extraction_report.get('has_tables', False),
            'multi_column': extraction_report.get('multi_column', False),
            'is_ocr': extraction_report.get('is_ocr', False)
        },
        'extracted_info': {
            'name': candidate_name,
            'contact_info': contacts,
            'sections_detected': sections,
            'skills': skill_names,
            'skills_detailed': skills,
            'experience': {
                'total_bullets': entities['total_bullets'],
                'quantified_bullets_count': entities['quantified_bullets_count'],
                'quantified_ratio': entities['quantified_ratio'],
                'action_verbs_count': len(entities['action_verbs']),
                'action_verbs': entities['action_verbs'][:10],
                'leadership_verbs': entities.get('leadership_verbs', [])[:6],
                'metrics_count': entities['metrics_count'],
                'metrics_samples': entities['metrics_samples'],
                'sample_bullets': entities['sample_bullets']
            }
        },
        'explanations': explanations,
        'issues': issues,
        'ai_improvements': ai_enhancements,
        'action_plan': action_plan,
        # Legacy compatibility keys
        'extracted_skills': skill_names,
        'detected_keywords': skill_names[:8],
        'missing_keywords': jd_match['missing_skills'][:6] if jd_match else ['Cloud Security', 'CI/CD Pipelines', 'System Design'],
        'sections_detected': sections,
        'suggestions': [
            {'category': i['category'], 'title': i['category'], 'desc': i['recommendation'], 'impact': i['severity']}
            for i in issues[:5]
        ]
    }
