# -*- coding: utf-8 -*-
"""
Production Test Suite for Calibrated Machine Learning & NLP Resume Intelligence System.
"""
import io
import os
import pytest
from app import app
from docx import Document

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def create_sample_docx(text):
    doc = Document()
    for paragraph in text.split('\n'):
        if paragraph.strip():
            doc.add_paragraph(paragraph.strip())
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio

def test_resume_intelligence_page_rendering(client):
    res = client.get('/resume_intelligence')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Calibrated Resume Intelligence' in html
    assert 'Extraction Quality:' in html
    assert 'ATS Compatibility' in html
    assert 'Resume Quality' in html
    assert 'Overall Score' in html
    print("\n[PASS] Calibrated Resume Intelligence dashboard rendered successfully.")

def test_calibrated_scoring_and_unquantified_resume(client):
    """
    Verifies that an average developer resume with generic/unquantified bullet points
    scores realistically in the 55-68 range (previously inflated to 89).
    """
    resume_content = """
    Rahul Verma
    Email: rahul.verma@example.com | Phone: +91 9876543210
    
    Professional Summary
    Software developer with experience in Python, SQL and web applications.
    
    Experience
    Software Engineer | Infosys (2021 - Present)
    • Worked on backend APIs using Python and Flask.
    • Assisted in database queries and maintenance with MySQL.
    • Fixed bug reports and participated in team meetings.
    • Handled application deployment on Linux server.
    
    Skills
    Python, Flask, MySQL, HTML, CSS, Git, Linux
    
    Education
    B.Tech in Computer Science | Anna University (2017 - 2021)
    """
    docx_stream = create_sample_docx(resume_content)
    data = {'resume': (docx_stream, 'rahul_verma_resume.docx')}
    res = client.post('/api/resume_intelligence/analyze', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is True
    
    # Check calibrated scores
    overall = json_data['overall_score']
    ats_comp = json_data['ats_score']
    res_qual = json_data['resume_quality_score']
    
    assert 55 <= overall <= 68, f"Score {overall} should be calibrated between 55 and 68"
    assert res_qual < 50, f"Resume Quality {res_qual} should reflect lack of metrics"
    assert ats_comp >= 75, f"ATS Compatibility {ats_comp} should reflect machine readability"
    assert json_data['extraction_report']['quality_score'] >= 85
    print(f"[PASS] Calibrated average resume score verified: Overall={overall}/100, ATS Comp={ats_comp}/100, Quality={res_qual}/100")

def test_high_impact_quantified_resume(client):
    """
    Verifies that a senior candidate with multiple quantified metrics (45%, $120k, 2M+)
    and strong action verbs achieves a top tier score (82-95).
    """
    resume_content = """
    Alex Mercer
    Email: alex.mercer@example.com | Phone: +1 555-0199 | Location: San Francisco, CA
    LinkedIn: linkedin.com/in/alex-mercer | GitHub: github.com/alex-mercer

    Professional Summary
    Lead AI Engineer with 6+ years of experience architecting distributed transformer systems and production ML pipelines.

    Experience
    Lead AI Engineer | Apex Intelligence (2021 - Present)
    • Architected and deployed end-to-end transformer NLP models, reducing inference latency by 45% and saving $120,000 annually.
    • Spearheaded development of automated feature extraction pipelines processing 2,000,000+ daily transactions.
    • Mentored 8 junior data scientists and automated testing with 98% code coverage.

    Senior Machine Learning Engineer | DataFlow (2018 - 2021)
    • Engineered predictive classification algorithms with 92% precision using Scikit-Learn and PostgreSQL.
    • Optimized 30+ complex SQL queries, cutting batch reporting time by 60% for 45,000 active users.

    Technical Skills
    Languages: Python, SQL, C++, Go, PyTorch, TensorFlow, Scikit-Learn, FastAPI, React, Docker, Kubernetes, AWS

    Education
    Master of Science in Computer Science | Stanford University (2016 - 2018)
    """
    docx_stream = create_sample_docx(resume_content)
    data = {'resume': (docx_stream, 'alex_mercer_resume.docx')}
    res = client.post('/api/resume_intelligence/analyze', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is True
    
    overall = json_data['overall_score']
    assert overall >= 80, f"High impact resume should score >= 80, got {overall}"
    assert json_data['extracted_info']['experience']['metrics_count'] >= 3
    assert json_data['extracted_info']['experience']['action_verbs_count'] >= 5
    print(f"[PASS] High impact quantified resume scored: Overall={overall}/100 (Tier: {json_data['rating_tier']})")

def test_required_skill_rule_with_jd(client):
    """
    Verifies that missing hard-required JD skills strictly penalizes and caps the Job Match score.
    """
    resume_content = """
    Priya Sharma
    Email: priya.sharma@example.com | Phone: +91 9876543210
    Summary: Frontend developer with React and JavaScript experience.
    Experience: Developed web UIs using React, Redux, and Tailwind CSS.
    Skills: React, Redux, JavaScript, HTML, CSS, Git
    """

    job_description = """
    Job Title: Lead Snowflake & Cloud Data Engineer
    Required Skills:
    - Snowflake (Must have)
    - Apache Spark & PySpark
    - BigQuery
    - Apache Airflow
    - Python and SQL
    """
    docx_stream = create_sample_docx(resume_content)
    data = {
        'resume': (docx_stream, 'priya_resume.docx'),
        'job_description': job_description
    }
    res = client.post('/api/resume_intelligence/analyze', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is True
    
    job_match = json_data['job_match_score']
    # Because candidate lacks Snowflake, Spark, BigQuery, Airflow, score must be capped <= 55%
    assert job_match <= 55, f"Job match {job_match}% should be <= 55% due to missing required skills"
    assert len(json_data['jd_match']['missing_required']) >= 3
    print(f"[PASS] Required Skill Rule enforced: Job Match={job_match}%, Missing Required={json_data['jd_match']['missing_required']}")

def test_invalid_file_handling(client):
    empty_stream = io.BytesIO(b"")
    data = {'resume': (empty_stream, 'empty.pdf')}
    res = client.post('/api/resume_intelligence/analyze', data=data, content_type='multipart/form-data')
    assert res.status_code == 400 or res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is False
    print("[PASS] Invalid/empty file rejected safely.")

def test_pymupdf_pdf_parsing_and_fallback():
    import pymupdf
    from resume_intelligence.parser.pdf_parser import parse_pdf
    from unittest.mock import patch

    # Create in-memory PDF using PyMuPDF
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Priya Sharma\nEmail: priya@example.com\nExperience: Python Engineer.", fontsize=11)
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Education\nB.Tech Computer Science\nSkills: Python, Flask, PyMuPDF, Docker", fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()

    # 1. Test PyMuPDF as fallback engine when pdfplumber is bypassed
    with patch.dict('sys.modules', {'pdfplumber': None}):
        text, report = parse_pdf(io.BytesIO(pdf_bytes))
    assert 'priya' in text.lower()
    assert 'pymupdf' in text.lower()
    assert report['page_count'] == 2
    print("[PASS] PyMuPDF fallback extraction and multi-page count verified.")

def test_pdf_upload_endpoint(client):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Ananya Verma\nEmail: ananya@example.com\nSummary: Data Scientist\nSkills: Python, SQL", fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()

    data = {'resume': (io.BytesIO(pdf_bytes), 'ananya_resume.pdf')}
    res = client.post('/api/resume_intelligence/analyze', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is True
    assert json_data['extraction_report']['source_type'] == 'pdf'
    print("[PASS] PDF upload and analysis via PyMuPDF/pdfplumber pipeline verified.")

def test_portfolio_extraction_no_false_match_from_email_domain():
    """
    Asserts that email addresses (like john@email.com or dev@company.io)
    are not falsely extracted as portfolio URLs, and common email providers are ignored.
    """
    from resume_intelligence.nlp.entity_extraction import extract_contacts

    resume_text_email_only = """
    John Doe
    Email: john.doe@email.com | Phone: +1 555-0100
    Secondary Email: candidate@gmail.com, work@techcorp.io
    
    Professional Experience
    Senior Software Engineer with 5+ years building distributed backend APIs.
    """
    contacts = extract_contacts(resume_text_email_only)
    assert contacts['email'] == 'john.doe@email.com'
    assert contacts['portfolio'] is None, f"Expected portfolio to be None, got: {contacts['portfolio']}"

    # Also test with various common providers
    for provider in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'protonmail.com']:
        text = f"Candidate Name\nEmail: alex@{provider}\nSkills: Python, React"
        c = extract_contacts(text)
        assert c['portfolio'] is None, f"Provider {provider} falsely identified as portfolio: {c['portfolio']}"
    print("\n[PASS] Portfolio extraction safely ignores candidate email domains and mail providers.")

def test_portfolio_extraction_with_real_portfolio_url():
    """
    Asserts that authentic portfolio URLs (e.g. janedoe.dev, https://alex.io)
    are still detected accurately.
    """
    from resume_intelligence.nlp.entity_extraction import extract_contacts

    resume_text_with_portfolio = """
    Jane Doe
    Email: jane.doe@gmail.com | Phone: +1 555-0100
    Portfolio: https://janedoe.dev | GitHub: github.com/janedoe
    
    Professional Experience
    Full Stack Developer building web applications.
    """
    contacts = extract_contacts(resume_text_with_portfolio)
    assert contacts['email'] == 'jane.doe@gmail.com'
    assert contacts['portfolio'] is not None
    assert 'janedoe.dev' in contacts['portfolio']
    print(f"[PASS] Real portfolio accurately extracted: {contacts['portfolio']}")

def test_resume_intelligence_csrf_enforcement():
    """
    Asserts that /api/resume_intelligence/analyze enforces CSRF validation when enabled:
    - Missing CSRF token -> 400 Bad Request
    - Valid CSRF token in header or form field -> 200 OK
    """
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = True
    with app.test_client() as client:
        # Fetch valid CSRF token
        csrf_res = client.get('/api/csrf_token')
        csrf_token = csrf_res.get_json()['csrf_token']

        # 1. Request without CSRF token should fail
        resume_content = "Test Candidate\nEmail: test@example.com\nSkills: Python, SQL"
        docx_stream1 = create_sample_docx(resume_content)
        bad_data = {'resume': (docx_stream1, 'test_resume.docx')}
        bad_res = client.post('/api/resume_intelligence/analyze', data=bad_data, content_type='multipart/form-data')
        assert bad_res.status_code == 400
        assert 'CSRF' in bad_res.get_json()['message']

        # 2. Request with X-CSRFToken header should succeed
        docx_stream2 = create_sample_docx(resume_content)
        good_data = {'resume': (docx_stream2, 'test_resume.docx')}
        good_res = client.post(
            '/api/resume_intelligence/analyze',
            data=good_data,
            content_type='multipart/form-data',
            headers={'X-CSRFToken': csrf_token}
        )
        assert good_res.status_code == 200
        assert good_res.get_json()['success'] is True

        # 3. Request with csrf_token form field should also succeed
        docx_stream3 = create_sample_docx(resume_content)
        good_data_form = {
            'resume': (docx_stream3, 'test_resume.docx'),
            'csrf_token': csrf_token
        }
        good_res2 = client.post(
            '/api/resume_intelligence/analyze',
            data=good_data_form,
            content_type='multipart/form-data'
        )
        assert good_res2.status_code == 200
        assert good_res2.get_json()['success'] is True
        print("[PASS] /api/resume_intelligence/analyze CSRF enforcement verified.")

    # Reset WTF_CSRF_ENABLED for standard test runners
    app.config['WTF_CSRF_ENABLED'] = False


def test_extraction_quality_metrics_and_diagnostics():
    """
    Tests extraction quality calculation, confidence scoring, and layout diagnostics.
    """
    from resume_intelligence.parser.extraction_quality import compute_extraction_quality

    # High quality clean text with multiple sections
    clean_text = """
    John Doe
    Email: john@example.com | Phone: +1 555-0100
    Professional Summary
    Senior Backend Engineer with 7 years experience in Python and AWS.
    Experience
    Senior Engineer | TechCorp (2020 - 2024)
    • Architected microservices with 99.99% uptime.
    Education
    B.S. Computer Science | MIT (2016 - 2020)
    Skills
    Python, Django, AWS, Docker, Kubernetes
    """
    report = compute_extraction_quality(clean_text, source_type='pdf', has_tables=True, table_count=2, multi_column=False)
    assert report['quality_score'] >= 80
    assert 0.8 <= report['confidence_score'] <= 1.0
    assert report['has_tables'] is True
    assert report['table_count'] == 2
    assert report['multi_column'] is False
    assert report['is_ocr'] is False

    # Low quality garbled/empty text
    garbled_text = "asdf #$ 123"
    garbled_report = compute_extraction_quality(garbled_text, source_type='pdf', is_ocr=True)
    assert garbled_report['quality_score'] < 50
    assert garbled_report['confidence_score'] < 0.5
    assert garbled_report['is_ocr'] is True
    print("[PASS] Extraction quality and confidence diagnostics verified.")


def test_text_cleaner_spaced_out_headings():
    """
    Tests text cleaner normalization for spaced-out PDF heading artifacts.
    """
    from resume_intelligence.parser.text_cleaner import clean_extracted_text

    raw_text = "E X P E R I E N C E\nSoftware Engineer\nS K I L L S\nPython, Docker\nE D U C A T I O N\nB.Tech"
    cleaned = clean_extracted_text(raw_text)
    assert "EXPERIENCE" in cleaned
    assert "SKILLS" in cleaned
    assert "EDUCATION" in cleaned
    print("[PASS] Spaced-out heading normalization verified.")


def test_skill_normalization_and_aliases():
    """
    Tests skill alias normalization (e.g., Microsoft Power BI -> Power BI, k8s -> Kubernetes).
    """
    from resume_intelligence.nlp.skill_normalization import normalize_skill

    assert normalize_skill("Microsoft Power BI")[0] == "Power BI"
    assert normalize_skill("k8s")[0] == "Kubernetes"
    assert normalize_skill("Fast-API")[0] == "FastAPI"
    assert normalize_skill("PostgreSQL")[0] == "PostgreSQL"
    assert normalize_skill("Postgres")[0] == "PostgreSQL"
    assert normalize_skill("React.js")[0] == "React"
    assert normalize_skill("ReactJS")[0] == "React"
    assert normalize_skill("Node.js")[0] == "Node.js"
    assert normalize_skill("Golang")[0] == "Go"
    print("[PASS] Skill normalization & alias resolution verified.")


def test_9_section_detection_and_missing_sections():
    """
    Tests detection of all 9 standard sections and missing mandatory vs recommended sections.
    """
    from resume_intelligence.nlp.section_detection import detect_sections

    full_text = """
    Alex Mercer
    Email: alex@example.com | Phone: 555-0100
    Summary: Lead AI engineer
    Experience: 8 years building distributed systems.
    Education: MS in CS Stanford
    Skills: Python, PyTorch
    Projects: Distributed Cache in Go
    Certifications: AWS Certified Solutions Architect
    Achievements: 1st Place National Hackathon
    Languages: English, Spanish
    """
    sections = detect_sections(full_text)
    assert sections.get('contact') is True or sections.get('contact_info') is True
    assert sections['summary'] is True
    assert sections['experience'] is True
    assert sections['education'] is True
    assert sections['skills'] is True
    assert sections['projects'] is True
    assert sections['certifications'] is True
    assert sections['achievements'] is True
    assert sections['languages'] is True
    assert len(sections['missing_mandatory']) == 0
    assert len(sections['missing_recommended']) == 0
    assert sections['total_detected_count'] == 9

    # Test incomplete resume missing education and projects
    incomplete_text = """
    Rahul Verma
    Email: rahul@example.com
    Experience: Software Engineer at Infosys
    Skills: Python, MySQL
    """
    inc_sections = detect_sections(incomplete_text)
    assert 'education' in inc_sections['missing_mandatory']
    assert 'projects' in inc_sections['missing_recommended']
    assert 'summary' in inc_sections['missing_recommended']
    print("[PASS] 9-section structure and missing section auditing verified.")


def test_multi_currency_and_latency_metric_extraction():
    """
    Tests extraction of multi-currency, latency, throughput, and scale metrics.
    """
    from resume_intelligence.nlp.entity_extraction import extract_metrics_and_verbs

    sample = """
    • Reduced API latency from 450ms to 45ms across all microservices.
    • Generated ₹25 Lakhs / 25 LPA in annual recurring revenue.
    • Scaled distributed system to process 50,000+ requests per second.
    • Optimized AWS infrastructure saving $150,000 yearly.
    • Managed a team of 12 engineers delivering 3x throughput improvements.
    """
    metrics = extract_metrics_and_verbs(sample)
    assert metrics['metrics_count'] >= 4
    samples_str = ' '.join(metrics['metrics_samples']).lower()
    assert '45ms' in samples_str or 'latency' in samples_str or 'ms' in samples_str
    assert '₹' in samples_str or 'lakhs' in samples_str or 'lpa' in samples_str or '$150,000' in samples_str or '50,000+' in samples_str
    print(f"[PASS] Multi-currency and latency metric extraction verified (Detected: {metrics['metrics_samples']}).")


def test_jd_decomposition_and_required_caps():
    """
    Tests JD decomposition into required vs preferred skills, and verifies scoring cap.
    """
    from resume_intelligence.scoring.job_match_score import decompose_job_description, analyze_and_match_job_description

    jd = """
    Senior Cloud Architect
    Required Qualifications:
    - Must have 5+ years Kubernetes (k8s) and Docker
    - Expert in AWS and Terraform
    - Proficiency in Go or Python
    
    Preferred Qualifications:
    - Experience with Kafka or RabbitMQ
    - Knowledge of GraphQL
    
    Responsibilities:
    - Architect scalable distributed systems
    """
    decomp = decompose_job_description(jd)
    req_skills_lower = [s.lower() for s in decomp['required_skills']]
    pref_skills_lower = [s.lower() for s in decomp['preferred_skills']]
    assert any(k in req_skills_lower for k in ['kubernetes', 'docker', 'aws', 'terraform', 'go', 'python'])
    assert any(p in pref_skills_lower for p in ['kafka', 'graphql', 'rabbitmq'])

    # Candidate with only Python and SQL (missing Kubernetes, Terraform, AWS)
    candidate_skills = ['python', 'sql', 'mysql']
    candidate_text = "Software Developer with Python and SQL experience."
    res = analyze_and_match_job_description(candidate_text, candidate_skills, jd)
    assert res['job_match_score'] <= 55
    assert len(res['missing_required']) >= 2
    assert res['required_match_ratio'] < 0.5
    print(f"[PASS] JD decomposition and missing required caps verified (Score: {res['job_match_score']}%).")



def test_timing_telemetry_meta():
    """
    Tests that timing telemetry (extraction_time_ms, nlp_time_ms, inference_time_ms, total_time_ms)
    is recorded and returned in meta dictionary.
    """
    from resume_intelligence import analyze_resume_pipeline

    resume_text = """
    Jane Doe
    Email: jane.doe@example.com | Phone: 555-0100
    Experience: 5 years building web applications with Python and React.
    Skills: Python, React, Docker, SQL
    Education: B.S. in Computer Science
    """
    res = analyze_resume_pipeline(io.BytesIO(resume_text.encode('utf-8')), 'test_meta.txt')
    assert res['success'] is True
    assert 'meta' in res
    meta = res['meta']
    assert 'extraction_time_ms' in meta
    assert 'nlp_time_ms' in meta
    assert 'inference_time_ms' in meta
    assert 'total_time_ms' in meta
    assert meta['total_time_ms'] >= 0
    print(f"[PASS] Timing telemetry meta verified: {meta}")


if __name__ == '__main__':
    pytest.main(['-s', __file__])

