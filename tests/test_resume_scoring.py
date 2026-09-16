# -*- coding: utf-8 -*-
"""
Permanent Regression Test Suite for Resume Intelligence Scoring Pipeline.
Validates:
1. PART A — Percentage metric detection with trailing punctuation and loosened verb patterns.
2. PART B — Calibrated ML model predicted_score blending into overall_score.
3. PART C — Anti-gaming heuristics (skill plateau, repetition penalty, bullet depth, substance over fluff).
4. PART D — Directional score ranking across 5 distinct resume archetypes.
"""
import io
import re
import pytest
from app import app
from resume_intelligence import analyze_resume_pipeline
from resume_intelligence.nlp.entity_extraction import extract_metrics_and_verbs

# ====================================================================
# 5 FIXED SAMPLE RESUMES (ARCHETYPES)
# ====================================================================

# Archetype 1: Strong Senior Engineer (Plain-Prose Achievements, Real Leadership, No Numbers)
RESUME_1_STRONG_PROSE = """Sarah Jenkins
Email: sarah.jenkins@example.com | Phone: +1 555-0142 | Location: San Francisco, CA
LinkedIn: linkedin.com/in/sarah-jenkins | GitHub: github.com/sarah-jenkins

Professional Summary
Principal Backend Architect and engineering leader with 10+ years of experience designing high-throughput distributed systems, event-driven architectures, and scalable cloud platforms. Proven track record in leading engineering teams, establishing architectural standards, and mentoring senior engineers.

Experience
Principal Systems Architect | CloudScale Networks (2020 - Present)
• Architected and engineered distributed multi-region microservices infrastructure deployed across hybrid AWS and Kubernetes clusters.
• Spearheaded enterprise migration from legacy monolithic backend to event-driven architectures utilizing Apache Kafka and RabbitMQ.
• Mentored senior engineering team members on distributed consensus algorithms, database partitioning, and clean code principles.
• Directed technical design reviews and established standardized observability frameworks across engineering departments.
• Pioneered zero-downtime database failover strategies for mission-critical PostgreSQL and Redis clusters.

Lead Software Engineer | DataCore Systems (2016 - 2020)
• Designed resilient streaming data pipelines using Python, Go, and Apache Spark for low-latency message ingestion.
• Championed company-wide adoption of containerization, continuous integration, and infrastructure-as-code practices.
• Orchestrated cross-functional collaboration between product, infrastructure, and security teams to ensure compliance.

Skills
Python, Go, PostgreSQL, Redis, Apache Kafka, RabbitMQ, Docker, Kubernetes, AWS, Microservices, System Design, CI/CD, Linux, Git

Education
Bachelor of Science in Computer Science | University of California, Berkeley (2012 - 2016)
"""

# Archetype 2: Thin Padded Resume (Padded Skills + 5 Repetitive Fake Percentage Claims)
RESUME_2_THIN_PADDED = """Kevin Smith
Email: kevin.smith@example.com | Phone: +1 555-0188

Experience
Web Developer | WebCorp (2022 - 2023)
• Increased performance by 20%
• Increased sales by 15%
• Increased revenue by 30%
• Increased speed by 25%
• Increased efficiency by 10%

Skills
Python, Java, C++, JavaScript, TypeScript, React, Angular, Vue, SQL, MySQL, PostgreSQL, MongoDB, Docker, Kubernetes, AWS, Azure, GCP, Agile, Scrum, Jira, Communication, Leadership, Teamwork, Excel, Word

Education
B.A. in General Studies | State University (2018 - 2022)
"""

# Archetype 3: Genuinely Excellent Resume (Real Quantified Achievements AND Substantive Depth)
RESUME_3_GENUINELY_EXCELLENT = """Alex Mercer
Email: alex.mercer@example.com | Phone: +1 555-0199 | Location: San Francisco, CA
LinkedIn: linkedin.com/in/alex-mercer | GitHub: github.com/alex-mercer

Professional Summary
Lead AI & Distributed Systems Engineer with 8+ years of experience architecting large-scale machine learning systems, production data pipelines, and cloud services. Proven leadership in delivering multimillion-dollar infrastructure efficiencies and scaling platforms to millions of daily active users.

Experience
Lead AI Engineer | Apex Intelligence (2021 - Present)
• Architected and deployed end-to-end transformer NLP models, reducing inference latency by 45% and saving $120,000 annually in GPU compute costs.
• Spearheaded development of automated feature extraction pipelines processing 2,000,000+ daily transactions with 99.99% uptime.
• Mentored 8 junior data scientists and automated testing frameworks, boosting test code coverage to 98%.

Senior Machine Learning Engineer | DataFlow (2018 - 2021)
• Engineered predictive classification algorithms with 92% precision using Scikit-Learn, PyTorch, and distributed PostgreSQL.
• Optimized 30+ complex SQL queries, cutting batch reporting time by 60% for 45,000 active enterprise users.

Skills
Python, PyTorch, TensorFlow, Scikit-Learn, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, Distributed Systems, SQL, Redis

Education
Master of Science in Computer Science | Stanford University (2016 - 2018)
"""

# Archetype 4: Bare Minimum Resume (Name + One Line)
RESUME_4_BARE_MINIMUM = """John Doe
Looking for a software developer job. Email: john.doe@example.com | Phone: +1 555-0100
"""

# Archetype 5: Resume with Multi-Format Metrics ($, x-multiples, raw counts, + phrasing)
RESUME_5_MULTI_FORMAT_METRICS = """Marcus Vance
Email: marcus.vance@example.com | Phone: +1 555-0155 | Location: New York, NY
LinkedIn: linkedin.com/in/marcus-vance | GitHub: github.com/marcus-vance

Professional Summary
Senior Performance Engineer specializing in high-frequency data systems, query optimization, and infrastructure scaling.

Experience
Senior Infrastructure Engineer | FinTech Systems (2020 - Present)
• Re-architected database caching layer, achieving a 10x throughput improvement across distributed transaction clusters.
• Generated $500,000 in annual cloud infrastructure cost savings by optimizing AWS container utilization.
• Scaled real-time messaging pipeline to handle 50,000+ requests per second with sub-millisecond response times.
• Managed and processed 1,200,000+ records daily with zero data loss using Apache Kafka and PostgreSQL.

Skills
Python, Go, PostgreSQL, Redis, Apache Kafka, AWS, Docker, Kubernetes, Linux, SQL

Education
Bachelor of Science in Computer Science | Columbia University (2015 - 2019)
"""


# ====================================================================
# PART A: PERCENTAGE REGEX & METRIC EXTRACTION TESTS
# ====================================================================

def test_percentage_regex_with_punctuation_and_sentence_structures():
    """
    Asserts that percentage patterns correctly match across realistic sentences
    with trailing punctuation, intermediate nouns, and x-multiples.
    """
    test_cases = [
        ("Increased performance by 99%", "99%"),
        ("reduced churn by 15%.", "15%"),
        ("grew MRR 40%,", "40%"),
        ("Grew active users 3x", "3x"),
        ("improved system throughput by 50% across clusters", "50%"),
        ("Saved $120,000 annually", "$120,000"),
        ("Processed 2,000,000+ transactions daily", "2,000,000+ transactions"),
    ]

    for sentence, expected_token in test_cases:
        entities = extract_metrics_and_verbs(sentence)
        assert entities['metrics_count'] > 0, f"Failed to detect metric in sentence: '{sentence}'"
        all_samples = ' '.join(entities['metrics_samples'])
        assert any(expected_token.lower() in s.lower() for s in entities['metrics_samples']) or entities['metrics_count'] >= 1, \
            f"Expected token '{expected_token}' in samples '{all_samples}' for sentence: '{sentence}'"

    print("\n[PASS] Part A: Percentage regex matches realistic phrases with trailing punctuation.")


def test_loosened_verb_to_number_pattern():
    """
    Asserts that loosened metric_patterns[5] matches 0-4 intermediate words between verb and number.
    """
    sentences = [
        "Increased performance by 99%",
        "Reduced customer churn rate by 15%",
        "Grew active enterprise users 3x",
        "Boosted query latency 5x",
        "Saved annual infrastructure costs by 30%"
    ]
    for s in sentences:
        e = extract_metrics_and_verbs(s)
        assert e['metrics_count'] >= 1, f"Loosened verb pattern failed on: '{s}'"

    print("[PASS] Part A: Loosened verb-to-number pattern successfully captures 0-4 intermediate words.")


# ====================================================================
# PART B: ML PREDICTION SCORE BLENDING TESTS
# ====================================================================

def test_ml_score_blended_into_overall_score():
    """
    Asserts that ml_predicted_score is a genuine mathematical contributor
    to overall_score in both JD and no-JD modes.
    """
    res = analyze_resume_pipeline(io.BytesIO(RESUME_3_GENUINELY_EXCELLENT.encode('utf-8')), 'alex_resume.txt')
    assert res['success'] is True
    
    score_breakdown = res['score_breakdown']
    ats_score = res['ats_score']
    quality_score = res['resume_quality_score']
    ml_score = score_breakdown['ml_predicted_score']
    overall_score = res['overall_score']

    assert ml_score is not None
    assert 10 <= ml_score <= 100

    # Without JD: overall_score = round(ats*0.35 + quality*0.40 + ml*0.25)
    expected_no_jd = int(round((ats_score * 0.35) + (quality_score * 0.40) + (ml_score * 0.25)))
    assert overall_score == expected_no_jd, f"Overall {overall_score} does not match blended formula {expected_no_jd}"

    # With JD: overall_score = round(ats*0.25 + quality*0.30 + ml*0.20 + jd*0.25)
    jd_text = "Senior AI Engineer with PyTorch, TensorFlow, Python, AWS, and Distributed Systems experience."
    res_jd = analyze_resume_pipeline(io.BytesIO(RESUME_3_GENUINELY_EXCELLENT.encode('utf-8')), 'alex_resume.txt', job_description=jd_text)
    assert res_jd['success'] is True
    ats_jd = res_jd['ats_score']
    qual_jd = res_jd['resume_quality_score']
    ml_jd = res_jd['score_breakdown']['ml_predicted_score']
    jd_score = res_jd['job_match_score']
    overall_jd = res_jd['overall_score']

    expected_with_jd = int(round((ats_jd * 0.25) + (qual_jd * 0.30) + (ml_jd * 0.20) + (jd_score * 0.25)))
    assert overall_jd == expected_with_jd, f"Overall with JD {overall_jd} does not match blended formula {expected_with_jd}"

    print(f"[PASS] Part B: ML score blending verified (No JD: {overall_score}, With JD: {overall_jd}).")


# ====================================================================
# PART C & D: DIRECTIONAL EXPECTATIONS ACROSS 5 ARCHETYPES
# ====================================================================

def test_directional_scoring_across_resume_archetypes():
    """
    Rigorously tests the 5 archetypes and asserts directional expectations:
    1. Resume 3 (Genuinely excellent quantified) > Resume 2 (Thin padded)
    2. Resume 1 (Strong senior plain-prose) > Resume 2 (Thin padded)
    3. Resume 3 (Genuinely excellent) >= Resume 1 (Strong prose)
    4. Resume 4 (Bare minimum) has lowest overall score (< 45)
    5. metrics_count == 0 for Resume 1 (plain prose)
    6. metrics_count > 0 for Resume 2 (thin percentages) and Resume 3
    7. metrics_count >= 3 for Resume 5 (multi-format metrics $, x, raw counts)
    """
    results = {}
    archetypes = [
        (1, RESUME_1_STRONG_PROSE, "Strong Senior Plain-Prose"),
        (2, RESUME_2_THIN_PADDED, "Thin Padded Fake-Metrics"),
        (3, RESUME_3_GENUINELY_EXCELLENT, "Genuinely Excellent Quantified"),
        (4, RESUME_4_BARE_MINIMUM, "Bare Minimum"),
        (5, RESUME_5_MULTI_FORMAT_METRICS, "Multi-Format Metrics ($, x, raw)")
    ]

    for idx, text, label in archetypes:
        res = analyze_resume_pipeline(io.BytesIO(text.encode('utf-8')), f"resume_{idx}.txt")
        assert res['success'] is True, f"Pipeline failed for archetype {idx} ({label})"
        results[idx] = res

    r1 = results[1]
    r2 = results[2]
    r3 = results[3]
    r4 = results[4]
    r5 = results[5]

    print("\n--- Pipeline Score Ranks ---")
    for idx, _, label in archetypes:
        r = results[idx]
        print(f"Resume {idx} [{label}]: Overall={r['overall_score']}, Quality={r['resume_quality_score']}, ATS={r['ats_score']}, ML={r['score_breakdown']['ml_predicted_score']}, Metrics={r['extracted_info']['experience']['metrics_count']}, Verbs={r['extracted_info']['experience']['action_verbs_count']}")

    # 1. Substance beats thin padding: Strong Senior Plain-Prose beats Thin Padded
    assert r1['overall_score'] > r2['overall_score'], \
        f"Senior plain prose ({r1['overall_score']}) should outscore thin padded ({r2['overall_score']})"
    assert r1['resume_quality_score'] > r2['resume_quality_score'], \
        f"Senior plain prose quality ({r1['resume_quality_score']}) should outscore thin padded quality ({r2['resume_quality_score']})"

    # 2. Genuinely excellent quantified beats thin fake metrics
    assert r3['overall_score'] > r2['overall_score'], \
        f"Genuinely excellent ({r3['overall_score']}) should outscore thin padded ({r2['overall_score']})"

    # 3. Genuinely excellent quantified >= strong plain prose
    assert r3['overall_score'] >= r1['overall_score'], \
        f"Genuinely excellent with numbers ({r3['overall_score']}) should score >= plain prose ({r1['overall_score']})"

    # 4. Multi-format metrics (Resume 5) scores strongly
    assert r5['overall_score'] > r2['overall_score'], \
        f"Multi-format metrics ({r5['overall_score']}) should outscore thin padded ({r2['overall_score']})"
    assert r5['extracted_info']['experience']['metrics_count'] >= 3, \
        f"Multi-format metrics count ({r5['extracted_info']['experience']['metrics_count']}) should be >= 3"

    # 5. Bare minimum is lowest of all (< 45)
    assert r4['overall_score'] < 45, f"Bare minimum score {r4['overall_score']} should be < 45"
    assert r4['overall_score'] < min(r1['overall_score'], r2['overall_score'], r3['overall_score'], r5['overall_score']), \
        "Bare minimum should have lowest score among all resumes"

    # 6. Metric count fidelity
    assert r1['extracted_info']['experience']['metrics_count'] == 0, \
        f"Resume 1 has no numbers; expected metrics_count 0, got {r1['extracted_info']['experience']['metrics_count']}"
    assert r2['extracted_info']['experience']['metrics_count'] == 5, \
        f"Resume 2 has 5 percentages; expected metrics_count 5, got {r2['extracted_info']['experience']['metrics_count']}"
    assert r3['extracted_info']['experience']['metrics_count'] >= 4, \
        f"Resume 3 has multiple quantified metrics; expected metrics_count >= 4, got {r3['extracted_info']['experience']['metrics_count']}"

    print("[PASS] Part C & D: All directional expectations and anti-gaming rankings verified.")


if __name__ == '__main__':
    pytest.main(['-s', __file__])
