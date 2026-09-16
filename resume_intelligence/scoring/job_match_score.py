import re
from ..nlp.skill_extraction import extract_skills_with_confidence
from ..ml.similarity_model import compute_semantic_similarity

# Related skills ontology for partial matching
SKILL_RELATIONSHIPS = {
    'Power BI': ['Tableau', 'Looker', 'Data Visualization', 'Microsoft Excel', 'QlikView/Qlik Sense'],
    'Tableau': ['Power BI', 'Looker', 'Data Visualization', 'QlikView/Qlik Sense'],
    'React': ['Vue.js', 'Angular', 'Next.js', 'JavaScript', 'TypeScript', 'Svelte'],
    'Vue.js': ['React', 'Angular', 'JavaScript', 'TypeScript'],
    'Angular': ['React', 'Vue.js', 'TypeScript', 'JavaScript'],
    'Node.js': ['Express.js', 'NestJS', 'FastAPI', 'Flask', 'Django'],
    'Python': ['Django', 'Flask', 'FastAPI', 'Pandas', 'NumPy', 'PySpark'],
    'Java': ['Spring Boot', 'Kotlin', 'Scala', 'C#'],
    'PostgreSQL': ['MySQL', 'SQL Server', 'Oracle DB', 'SQLite', 'SQL'],
    'MySQL': ['PostgreSQL', 'MariaDB', 'SQL Server', 'SQL'],
    'MongoDB': ['DynamoDB', 'Cassandra', 'Firebase', 'Redis'],
    'AWS': ['Microsoft Azure', 'Google Cloud (GCP)', 'Cloud & DevOps'],
    'Microsoft Azure': ['AWS', 'Google Cloud (GCP)', 'Cloud & DevOps'],
    'Google Cloud (GCP)': ['AWS', 'Microsoft Azure', 'Cloud & DevOps'],
    'Docker': ['Kubernetes', 'Containerization', 'Helm'],
    'Kubernetes': ['Docker', 'Helm', 'ArgoCD', 'Cloud & DevOps'],
    'PyTorch': ['TensorFlow', 'Keras', 'Deep Learning', 'Machine Learning'],
    'TensorFlow': ['PyTorch', 'Keras', 'Deep Learning', 'Machine Learning'],
    'Snowflake': ['BigQuery', 'Redshift', 'Databricks', 'Data Warehousing'],
    'BigQuery': ['Snowflake', 'Redshift', 'Databricks', 'Data Warehousing'],
    'Apache Spark': ['PySpark', 'Hadoop', 'Databricks', 'Flink'],
    'PySpark': ['Apache Spark', 'Pandas', 'Python', 'Databricks']
}

def decompose_job_description(jd_text):
    """
    Decomposes job description into structured sections and extracted skill lists:
    - required_text
    - preferred_text
    - responsibilities_text
    - full_text
    - required_skills
    - preferred_skills
    """
    lines = jd_text.split('\n')
    current_section = 'general'
    sections = {'required': [], 'preferred': [], 'responsibilities': [], 'general': []}

    req_pat = r'\b(required|requirements|must have|basic qualifications|minimum qualifications|core requirements)\b'
    pref_pat = r'\b(preferred|nice to have|good to have|plus|bonus|desired qualifications|preferred qualifications)\b'
    resp_pat = r'\b(responsibilities|what you\'ll do|what you will do|duties|role overview|about the role)\b'

    for line in lines:
        l_lower = line.strip().lower()
        if re.search(req_pat, l_lower) and len(l_lower) < 60:
            current_section = 'required'
            continue
        elif re.search(pref_pat, l_lower) and len(l_lower) < 60:
            current_section = 'preferred'
            continue
        elif re.search(resp_pat, l_lower) and len(l_lower) < 60:
            current_section = 'responsibilities'
            continue

        sections[current_section].append(line)

    req_text = '\n'.join(sections['required'])
    pref_text = '\n'.join(sections['preferred'])
    resp_text = '\n'.join(sections['responsibilities'])

    if req_text.strip():
        req_skills_raw = extract_skills_with_confidence(req_text)
        required_skills = [s['skill'] for s in req_skills_raw]
    else:
        all_skills_raw = extract_skills_with_confidence(jd_text)
        all_jd_skills = [s['skill'] for s in all_skills_raw]
        required_skills = all_jd_skills[:min(5, len(all_jd_skills))]

    if pref_text.strip():
        pref_skills_raw = extract_skills_with_confidence(pref_text)
        preferred_skills = [s['skill'] for s in pref_skills_raw if s['skill'] not in required_skills]
    else:
        all_skills_raw = extract_skills_with_confidence(jd_text)
        all_jd_skills = [s['skill'] for s in all_skills_raw]
        preferred_skills = [s for s in all_jd_skills if s not in required_skills]

    return {
        'required_text': req_text,
        'preferred_text': pref_text,
        'responsibilities_text': resp_text,
        'full_text': jd_text,
        'required_skills': required_skills,
        'preferred_skills': preferred_skills
    }

def analyze_and_match_job_description(resume_text, candidate_skills, jd_text):
    """
    Multi-Signal Job Description Matching with Required Skill Verification.
    Signals:
    1. Exact Required Skill Matches (40%)
    2. Preferred Skill Matches (15%)
    3. Dense SentenceTransformer Semantic Similarity (35%)
    4. Partial / Related Skill Matches (10%)
    
    Required Skill Rule: Missing core required skills imposes a strict mathematical cap.
    """
    if not jd_text or len(jd_text.strip()) < 10:
        return None

    candidate_skills_set = set([
        (s['skill'] if isinstance(s, dict) else str(s)).strip().lower()
        for s in candidate_skills
    ] if candidate_skills else [])
    
    decomposed = decompose_job_description(jd_text)
    required_skills = decomposed['required_skills']
    preferred_skills = decomposed['preferred_skills']

    # Ensure required_skills is not empty if JD has any skills
    if not required_skills and not preferred_skills:
        all_skills_raw = extract_skills_with_confidence(jd_text)
        all_jd_skills = [s['skill'] for s in all_skills_raw]
        required_skills = all_jd_skills[:min(5, len(all_jd_skills))]
        preferred_skills = all_jd_skills[min(5, len(all_jd_skills)):]

    matched_required = [s for s in required_skills if s.lower() in candidate_skills_set]
    missing_required = [s for s in required_skills if s.lower() not in candidate_skills_set]
    
    matched_preferred = [s for s in preferred_skills if s.lower() in candidate_skills_set]
    missing_preferred = [s for s in preferred_skills if s.lower() not in candidate_skills_set]


    matched_all = list(dict.fromkeys(matched_required + matched_preferred))
    missing_all = list(dict.fromkeys(missing_required + missing_preferred))

    # Partially matched skills
    partially_matched = []
    missing_prioritized = []

    for miss in missing_all:
        related = SKILL_RELATIONSHIPS.get(miss, [])
        found_related = [r for r in related if r in candidate_skills_set]
        if found_related:
            partially_matched.append({
                'required_skill': miss,
                'candidate_has': found_related[0]
            })
        else:
            priority = 'High' if miss in required_skills else 'Medium'
            missing_prioritized.append({
                'skill': miss,
                'priority': priority,
                'suggested_placement': 'Skills section and experience bullet points'
            })

    # Signal 3: Dense Semantic Embedding Similarity
    semantic_sim = compute_semantic_similarity(resume_text[:2500], jd_text[:2500])

    # Skill Ratios
    req_ratio = (len(matched_required) / max(1, len(required_skills))) if required_skills else 1.0
    pref_ratio = (len(matched_preferred) / max(1, len(preferred_skills))) if preferred_skills else 1.0
    partial_bonus = min(1.0, len(partially_matched) * 0.10)

    # Calculate Multi-Signal Raw Match Score
    raw_match = (
        (req_ratio * 40.0) +
        (pref_ratio * 15.0) +
        (partial_bonus * 10.0) +
        (semantic_sim * 35.0)
    )

    # REQUIRED SKILL RULE:
    # If 3 or more required skills are missing, score cannot exceed 55%
    # If 2 or more required skills are missing, score cannot exceed 68%
    # If 1 required skill is missing, score cannot exceed 82%
    if len(missing_required) >= 3:
        raw_match = min(55.0, raw_match)
    elif len(missing_required) >= 2:
        raw_match = min(68.0, raw_match)
    elif len(missing_required) == 1:
        raw_match = min(82.0, raw_match)

    job_match_score = int(round(raw_match))
    job_match_score = max(10, min(98, job_match_score))

    return {
        'jd_match_score': job_match_score,
        'job_match_score': job_match_score,
        'semantic_similarity': round(semantic_sim, 2),
        'required_skills': required_skills,
        'preferred_skills': preferred_skills,
        'required_skills_count': len(required_skills),
        'preferred_skills_count': len(preferred_skills),
        'matched_required': matched_required,
        'missing_required': missing_required,
        'matched_preferred': matched_preferred,
        'missing_preferred': missing_preferred,
        'matched_skills': matched_all,
        'missing_skills': [m['skill'] for m in missing_prioritized],
        'missing_prioritized': missing_prioritized,
        'partially_matched': partially_matched,
        'total_jd_skills': len(required_skills) + len(preferred_skills),
        'matched_count': len(matched_all),
        'missing_count': len(missing_prioritized),
        'required_match_ratio': round(req_ratio, 2),
        'preferred_match_ratio': round(pref_ratio, 2)
    }
