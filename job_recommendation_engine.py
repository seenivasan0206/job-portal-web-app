# -*- coding: utf-8 -*-
"""
HireVolt AI/ML Job Recommendation Engine
========================================
A multi-factor, explainable, and cached recommendation system combining:
1. Exact and Normalized Skill Matching (35% weight)
2. Semantic / JD Text Embedding Cosine Similarity (25% weight)
3. Preferred Role & Title Alignment (12% weight)
4. Experience Level Fit (10% weight)
5. Location & Remote Preference (8% weight)
6. Salary Range & Expectation Fit (5% weight)
7. Employment Type Fit (3% weight)
8. Education Degree Match (2% weight)

Features:
- Transparent human-readable recommendation reasons
- In-memory vector caching for SentenceTransformers and TF-IDF
- Performance telemetry (latency tracking)
- Irrelevance filtering and thresholding
"""

import re
import time
import math
import hashlib
import logging
from datetime import date as dt_date, datetime
from collections import OrderedDict
import numpy as np

logger = logging.getLogger(__name__)

# =====================================================================
# 1. CANONICAL SKILL NORMALIZATION & SYNONYM DICTIONARY
# =====================================================================

CANONICAL_SKILL_SYNONYMS = {
    'python': ['python', 'python3', 'python 3', 'python 2', 'py', 'cpython'],
    'react': ['react', 'react.js', 'reactjs', 'react js', 'react native', 'react-native'],
    'node.js': ['node', 'nodejs', 'node.js', 'node js', 'node-js'],
    'javascript': ['javascript', 'js', 'es6', 'es2015', 'es2020', 'ecmascript'],
    'typescript': ['typescript', 'ts'],
    'angular': ['angular', 'angular.js', 'angularjs', 'angular 2+', 'angular2'],
    'vue.js': ['vue', 'vue.js', 'vuejs', 'vue 3', 'vue2', 'vue 2'],
    'django': ['django', 'django rest framework', 'drf'],
    'fastapi': ['fastapi', 'fast-api', 'fast api'],
    'flask': ['flask'],
    'spring boot': ['spring', 'spring boot', 'springboot', 'spring framework', 'spring mvc'],
    'java': ['java', 'core java', 'java 8', 'java 11', 'java 17', 'j2ee'],
    'c++': ['c++', 'cpp'],
    'c#': ['c#', 'csharp', 'c sharp', '.net', 'dotnet', 'asp.net', 'asp.net core'],
    'sql': ['sql', 'rdbms', 'relational database', 't-sql', 'pl/sql'],
    'postgresql': ['postgresql', 'postgres', 'psql'],
    'mysql': ['mysql'],
    'mongodb': ['mongodb', 'mongo', 'nosql document store'],
    'redis': ['redis', 'redis cache', 'in-memory db'],
    'docker': ['docker', 'containerization', 'containers'],
    'kubernetes': ['kubernetes', 'k8s', 'container orchestration'],
    'aws': ['aws', 'amazon web services', 'amazon aws', 'ec2', 's3', 'lambda'],
    'gcp': ['gcp', 'google cloud', 'google cloud platform'],
    'azure': ['azure', 'microsoft azure', 'azure cloud'],
    'machine learning': ['machine learning', 'ml', 'machine-learning', 'supervised learning', 'unsupervised learning'],
    'deep learning': ['deep learning', 'dl', 'neural networks', 'ann', 'cnn', 'rnn'],
    'artificial intelligence': ['artificial intelligence', 'ai', 'genai', 'generative ai', 'llm', 'llms'],
    'nlp': ['nlp', 'natural language processing', 'text analytics', 'transformers'],
    'computer vision': ['computer vision', 'cv', 'opencv', 'image processing'],
    'data analysis': ['data analysis', 'data analytics', 'data analyst', 'business analytics'],
    'data science': ['data science', 'data scientist'],
    'power bi': ['power bi', 'powerbi', 'dax'],
    'tableau': ['tableau', 'tableau desktop'],
    'excel': ['excel', 'advanced excel', 'ms excel', 'microsoft excel', 'vlookup', 'pivot tables'],
    'html/css': ['html', 'html5', 'css', 'css3', 'html/css', 'html5/css3'],
    'tailwind css': ['tailwind', 'tailwind css', 'tailwindcss'],
    'bootstrap': ['bootstrap', 'bootstrap 4', 'bootstrap 5'],
    'git': ['git', 'github', 'gitlab', 'version control', 'bitbucket'],
    'devops': ['devops', 'ci/cd', 'cicd', 'jenkins', 'github actions', 'terraform', 'ansible'],
    'rest api': ['rest api', 'restful api', 'rest apis', 'rest', 'api development', 'api design'],
    'graphql': ['graphql'],
    'linux': ['linux', 'unix', 'ubuntu', 'bash', 'shell scripting'],
    'pandas': ['pandas'],
    'numpy': ['numpy'],
    'tensorflow': ['tensorflow', 'tf'],
    'pytorch': ['pytorch', 'torch'],
    'scikit-learn': ['scikit-learn', 'sklearn'],
    'spark': ['spark', 'apache spark', 'pyspark'],
    'kafka': ['kafka', 'apache kafka'],
    'php': ['php', 'laravel', 'symfony', 'codeigniter'],
    'go': ['go', 'golang'],
    'rust': ['rust'],
    'kotlin': ['kotlin', 'android kotlin'],
    'swift': ['swift', 'ios swift', 'swiftui'],
    'ui/ux': ['ui/ux', 'ui/ux design', 'figma', 'adobe xd', 'wireframing', 'user experience', 'user interface'],
    'cybersecurity': ['cybersecurity', 'information security', 'network security', 'penetration testing', 'soc', 'siem']
}

# Reverse mapping for O(1) canonical lookup
SKILL_ALIAS_MAP = {}
for canonical, aliases in CANONICAL_SKILL_SYNONYMS.items():
    SKILL_ALIAS_MAP[canonical.lower()] = canonical.lower()
    for alias in aliases:
        SKILL_ALIAS_MAP[alias.lower()] = canonical.lower()


def normalize_skill(skill_str):
    """
    Normalizes a skill string to its canonical form if available, or a clean lowercased string.
    """
    if not skill_str:
        return ''
    clean = str(skill_str).strip().lower()
    clean = re.sub(r'[\(\)\[\]\{\}]', '', clean).strip()
    return SKILL_ALIAS_MAP.get(clean, clean)


def match_skill_lists(required_skills, candidate_skills):
    """
    Matches required job skills against candidate skills using exact, canonical, and token boundary matching.
    Returns: (matched_skills, missing_skills, match_ratio)
    """
    if not required_skills:
        return [], [], 1.0

    cand_raw_map = {}
    cand_norm_set = set()
    cand_raw_set = set()

    for s in candidate_skills:
        clean = str(s).strip()
        if not clean:
            continue
        c_low = clean.lower()
        cand_raw_set.add(c_low)
        cand_raw_map[c_low] = clean
        norm = normalize_skill(c_low)
        if norm:
            cand_norm_set.add(norm)

    matched = []
    missing = []

    for req in required_skills:
        req_clean = str(req).strip()
        if not req_clean:
            continue
        req_low = req_clean.lower()
        req_norm = normalize_skill(req_low)

        # 1. Exact match
        if req_low in cand_raw_set:
            matched.append(req_clean)
            continue

        # 2. Canonical synonym match
        if req_norm in cand_norm_set:
            matched.append(req_clean)
            continue

        # 3. Substring / Token match (word boundary checked)
        found = False
        for c_low in cand_raw_set:
            if req_low == c_low or req_norm == normalize_skill(c_low):
                matched.append(req_clean)
                found = True
                break
            # Word boundary matching for phrases like 'Python Developer' or 'React.js Frontend'
            if len(req_low) >= 3 and len(c_low) >= 3:
                if re.search(r'\b' + re.escape(req_low) + r'\b', c_low) or re.search(r'\b' + re.escape(c_low) + r'\b', req_low):
                    matched.append(req_clean)
                    found = True
                    break

        if not found:
            missing.append(req_clean)

    ratio = (len(matched) / len(required_skills)) if required_skills else 1.0
    return matched, missing, ratio


# =====================================================================
# 2. LRU VECTOR CACHING & SEMANTIC SIMILARITY
# =====================================================================

_EMBEDDING_VECTOR_CACHE = OrderedDict()
_EMBEDDING_VECTOR_CACHE_MAX = 5000


def _get_text_hash(text):
    return hashlib.md5((text or '').encode('utf-8')).hexdigest()


def get_cached_dense_embedding(text, model_getter=None):
    """
    Computes or retrieves cached normalized dense vector embedding for a text string.
    """
    if not text:
        return None

    clean_text = text.strip()[:3500]
    t_hash = _get_text_hash(clean_text)

    if t_hash in _EMBEDDING_VECTOR_CACHE:
        # Move to end for LRU
        _EMBEDDING_VECTOR_CACHE.move_to_end(t_hash)
        return _EMBEDDING_VECTOR_CACHE[t_hash]

    model = None
    if model_getter:
        try:
            model = model_getter()
        except Exception:
            model = None

    vec = None
    if model is not None:
        try:
            raw_vec = model.encode(clean_text, convert_to_numpy=True, normalize_embeddings=True)
            vec = np.array(raw_vec, dtype=np.float32)
        except Exception as e:
            logger.debug(f"Dense vector encoding error: {e}")
            vec = None

    if vec is not None:
        _EMBEDDING_VECTOR_CACHE[t_hash] = vec
        if len(_EMBEDDING_VECTOR_CACHE) > _EMBEDDING_VECTOR_CACHE_MAX:
            _EMBEDDING_VECTOR_CACHE.popitem(last=False)

    return vec


def compute_cached_semantic_similarity(text_a, text_b, model_getter=None):
    """
    Computes semantic cosine similarity (0.0 to 1.0) with LRU embedding caching and TF-IDF fallback.
    """
    if not text_a or not text_b:
        return 0.0

    vec_a = get_cached_dense_embedding(text_a, model_getter)
    vec_b = get_cached_dense_embedding(text_b, model_getter)

    if vec_a is not None and vec_b is not None:
        try:
            dot = float(np.dot(vec_a, vec_b))
            return max(0.0, min(1.0, dot))
        except Exception:
            pass

    # TF-IDF Cosine Similarity Fallback
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words='english', max_features=3000, ngram_range=(1, 2))
        tfidf = vec.fit_transform([text_a[:3000], text_b[:3000]])
        sim = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
        return max(0.0, min(1.0, sim))
    except Exception as err:
        logger.debug(f"TF-IDF fallback similarity calculation: {err}")
        # Jaccard word set fallback
        words_a = set(re.findall(r'\w+', text_a.lower()))
        words_b = set(re.findall(r'\w+', text_b.lower()))
        if not words_a or not words_b:
            return 0.5
        intersect = len(words_a & words_b)
        union = len(words_a | words_b)
        return max(0.0, min(1.0, intersect / union if union > 0 else 0.5))


# =====================================================================
# 3. SALARY, EXPERIENCE & EDUCATION PARSERS
# =====================================================================

def parse_salary_value_inr(val_str):
    """
    Converts various salary formats (e.g. '₹18 LPA', '1200000', '18.5 L', '25000/mo') into annual INR float.
    """
    if val_str is None:
        return None
    if isinstance(val_str, (int, float)):
        return float(val_str)
    s = str(val_str).strip().lower().replace(',', '')
    if not s:
        return None

    nums = re.findall(r'\d+(?:\.\d+)?', s)
    if not nums:
        return None

    val = float(nums[0])
    if 'lpa' in s or 'lac' in s or 'lakh' in s or 'l' in s or (0 < val < 150):
        return val * 100000.0
    if 'k' in s:
        return val * 1000.0
    if 'month' in s or 'pm' in s or '/mo' in s:
        return val * 12.0
    return val


def parse_experience_years_num(exp_val):
    """
    Parses experience strings (e.g. '3-5 Years', 'Fresher', '5+ Yrs') into numerical required years float.
    """
    if exp_val is None:
        return 0.0
    if isinstance(exp_val, (int, float)):
        return float(exp_val)
    s = str(exp_val).strip().lower()
    if not s or any(w in s for w in ['fresher', 'entry', '0 year', '0-1', 'intern']):
        return 0.0
    nums = re.findall(r'\d+(?:\.\d+)?', s)
    if nums:
        return float(nums[0])
    return 0.0


# =====================================================================
# 4. CANDIDATE PROFILE AGGREGATOR
# =====================================================================

def get_candidate_recommendation_profile(user_id, cur):
    """
    Gathers comprehensive candidate data across user, candidate_profile, preferences,
    personal details, employment, education, key_skills, it_skills, and resume_analyses.
    """
    if not user_id:
        return None

    # 1. Base User
    cur.execute("SELECT id, name, email, headline, skills, experience, location FROM user WHERE id = %s", (user_id,))
    user_row = cur.fetchone() or {}

    # 2. Candidate Profile
    cur.execute("SELECT headline, summary, skills, general_resume_path FROM candidate_profile WHERE user_id = %s", (user_id,))
    cp_row = cur.fetchone() or {}

    # 3. Preferences
    cur.execute("""
        SELECT current_job_role, desired_job_type, desired_employment_type, preferred_location,
               workplace_type, current_ctc, expected_ctc, notice_period, open_to_relocate, current_industry
        FROM candidate_preferences WHERE user_id = %s
    """, (user_id,))
    pref_row = cur.fetchone() or {}

    # 4. Personal Details
    cur.execute("SELECT current_location, hometown FROM candidate_personal_details WHERE user_id = %s", (user_id,))
    personal_row = cur.fetchone() or {}

    # 5. Profile Summary
    cur.execute("SELECT summary FROM candidate_profile_summary WHERE user_id = %s", (user_id,))
    summary_row = cur.fetchone() or {}

    # 6. Key Skills
    cur.execute("SELECT skill_name FROM key_skills WHERE user_id = %s", (user_id,))
    ks_rows = cur.fetchall() or []

    # 7. IT Skills
    cur.execute("SELECT skill_name, experience_years, proficiency FROM it_skills WHERE user_id = %s", (user_id,))
    it_rows = cur.fetchall() or []

    # 8. Resume Analyses (latest)
    cur.execute("""
        SELECT extracted_skills, detected_keywords, ats_score
        FROM resume_analyses WHERE user_id = %s ORDER BY id DESC LIMIT 1
    """, (user_id,))
    ra_row = cur.fetchone() or {}

    # 9. Employment History
    cur.execute("""
        SELECT company_name, job_title, start_date, end_date, is_current, skills_used, job_profile
        FROM employment WHERE user_id = %s ORDER BY is_current DESC, id DESC
    """, (user_id,))
    emp_rows = cur.fetchall() or []

    # 10. Education
    cur.execute("""
        SELECT education_level, course_degree, specialization, institute, year_of_passing
        FROM education WHERE user_id = %s ORDER BY id DESC
    """, (user_id,))
    edu_rows = cur.fetchall() or []

    # Combine Skills
    all_skills_list = []
    for raw in [user_row.get('skills'), cp_row.get('skills')]:
        if raw:
            all_skills_list.extend([s.strip() for s in re.split(r'[,;\n|]', str(raw)) if s.strip()])
    for r in ks_rows:
        if r.get('skill_name'):
            all_skills_list.append(str(r['skill_name']).strip())
    for r in it_rows:
        if r.get('skill_name'):
            all_skills_list.append(str(r['skill_name']).strip())
    if ra_row.get('extracted_skills'):
        raw_es = ra_row['extracted_skills']
        if isinstance(raw_es, list):
            for s in raw_es:
                if s: all_skills_list.append(str(s).strip())
        elif isinstance(raw_es, str):
            try:
                parsed_es = json.loads(raw_es)
                if isinstance(parsed_es, list):
                    for s in parsed_es:
                        if s: all_skills_list.append(str(s).strip())
                else:
                    all_skills_list.extend([s.strip() for s in re.split(r'[,;\n|]', str(raw_es)) if s.strip()])
            except Exception:
                all_skills_list.extend([s.strip() for s in re.split(r'[,;\n|]', str(raw_es)) if s.strip()])

    dedup_skills = []
    seen = set()
    for s in all_skills_list:
        if s.lower() not in seen:
            seen.add(s.lower())
            dedup_skills.append(s)

    # Compute Total Verified Experience Years
    total_exp_years = 0.0
    if emp_rows:
        for emp in emp_rows:
            s_date = emp.get('start_date')
            e_date = emp.get('end_date')
            is_cur = emp.get('is_current')
            if is_cur or not e_date:
                e_date = dt_date.today()
            if isinstance(s_date, str):
                try: s_date = datetime.strptime(s_date[:10], '%Y-%m-%d').date()
                except Exception: s_date = None
            if isinstance(e_date, str):
                try: e_date = datetime.strptime(e_date[:10], '%Y-%m-%d').date()
                except Exception: e_date = None
            if s_date and e_date and e_date >= s_date:
                total_exp_years += (e_date - s_date).days / 365.25
    if total_exp_years == 0.0:
        try:
            total_exp_years = float(user_row.get('experience') or 0)
        except Exception:
            total_exp_years = 0.0

    total_exp_years = round(total_exp_years, 1)

    # Preferred Role & Location
    headline = cp_row.get('headline') or user_row.get('headline') or ''
    preferred_role = pref_row.get('current_job_role') or headline or ''
    current_location = personal_row.get('current_location') or user_row.get('location') or ''
    preferred_location = pref_row.get('preferred_location') or current_location or ''
    workplace_type = pref_row.get('workplace_type') or 'Flexible / Any'
    open_to_relocate = bool(pref_row.get('open_to_relocate'))
    expected_ctc_inr = parse_salary_value_inr(pref_row.get('expected_ctc'))
    desired_emp_type = pref_row.get('desired_employment_type') or 'Full-time'

    # Education string
    cand_edu_text = ' '.join([
        f"{e.get('course_degree', '')} {e.get('specialization', '')} {e.get('education_level', '')}"
        for e in edu_rows
    ]).lower()

    # Consolidated semantic text representation
    summary_text = summary_row.get('summary') or cp_row.get('summary') or ''
    detected_kws = str(ra_row.get('detected_keywords') or '')
    text_chunks = [
        headline,
        preferred_role,
        f"Skills: {', '.join(dedup_skills)}",
        summary_text[:1000],
        detected_kws[:500]
    ]
    cand_text = ' '.join(c for c in text_chunks if c).strip()

    return {
        'user_id': user_id,
        'name': user_row.get('name') or 'Candidate',
        'email': user_row.get('email') or '',
        'headline': headline,
        'preferred_role': preferred_role,
        'current_location': current_location,
        'preferred_location': preferred_location,
        'workplace_type': workplace_type,
        'open_to_relocate': open_to_relocate,
        'expected_ctc_inr': expected_ctc_inr,
        'expected_ctc_raw': pref_row.get('expected_ctc'),
        'desired_emp_type': desired_emp_type,
        'experience_years': total_exp_years,
        'skills': dedup_skills,
        'skills_str': ', '.join(dedup_skills),
        'education_text': cand_edu_text,
        'education_rows': edu_rows,
        'employment_rows': emp_rows,
        'summary': summary_text,
        'resume_text': detected_kws,
        'semantic_text': cand_text,
        'is_sparse': len(dedup_skills) == 0 and len(cand_text) < 20 and total_exp_years == 0.0
    }


# =====================================================================
# 5. MULTI-FACTOR SCORING & TRANSPARENT REASON GENERATION
# =====================================================================

def calculate_job_recommendation_score(job, cand, model_getter=None):
    """
    Computes a calibrated, weighted 0-100 recommendation score matching candidate against a job opening.
    Weights:
    - Skills Match: 35%
    - Semantic / JD Relevance: 25%
    - Role / Title Fit: 12%
    - Experience Fit: 10%
    - Location & Remote Fit: 8%
    - Salary Range Fit: 5%
    - Employment Type Fit: 3%
    - Education Degree Match: 2%

    Returns: { final_score, skill_score, semantic_score, role_score, experience_score,
               location_score, salary_score, work_mode_score, education_score,
               matched_skills, missing_skills, match_reason, breakdown }
    """
    if not job or not cand:
        return {
            'final_score': 0.0,
            'match_reason': 'Insufficient data to compute match score.',
            'matched_skills': [],
            'missing_skills': []
        }

    # 1. Skills Match (35% Weight)
    job_skills_raw = str(job.get('skills') or '').strip()
    required_skills = [s.strip() for s in re.split(r'[,;\n|]', job_skills_raw) if s.strip()]
    cand_skills = cand.get('skills', [])

    if not required_skills:
        matched_skills = []
        missing_skills = []
        skill_score = 100.0
    else:
        matched_skills, missing_skills, match_ratio = match_skill_lists(required_skills, cand_skills)
        skill_score = round(match_ratio * 100.0, 2)

    # 2. Semantic Relevance (25% Weight)
    jd_parts = [
        str(job.get('title') or ''),
        str(job.get('category') or ''),
        str(job.get('skills') or ''),
        str(job.get('description') or '')
    ]
    jd_text = ' '.join(p for p in jd_parts if p).strip()
    cand_text = cand.get('semantic_text') or cand.get('summary') or cand.get('headline') or ''

    if not jd_text or not cand_text or len(cand_text) < 10:
        semantic_score = 50.0
    else:
        sim = compute_cached_semantic_similarity(jd_text, cand_text, model_getter)
        semantic_score = round(float(sim) * 100.0, 2)

    # 3. Role & Title Alignment (12% Weight)
    job_title = str(job.get('title') or '').strip().lower()
    job_cat = str(job.get('category') or '').strip().lower()
    cand_role = str(cand.get('preferred_role') or cand.get('headline') or '').strip().lower()

    if not cand_role or not job_title:
        role_score = 70.0
    else:
        title_tokens = set(re.findall(r'\w+', job_title))
        role_tokens = set(re.findall(r'\w+', cand_role))
        overlap = title_tokens & role_tokens

        if cand_role in job_title or job_title in cand_role:
            role_score = 100.0
        elif len(overlap) >= 2:
            role_score = 90.0
        elif len(overlap) == 1:
            role_score = 75.0
        elif job_cat and (job_cat in cand_role or cand_role in job_cat):
            role_score = 65.0
        else:
            # Semantic role title similarity
            role_sim = compute_cached_semantic_similarity(job_title, cand_role, model_getter)
            role_score = round(max(30.0, float(role_sim) * 100.0), 2)

    # 4. Experience Fit (10% Weight)
    req_exp_years = parse_experience_years_num(job.get('experience'))
    cand_exp_years = float(cand.get('experience_years') or 0.0)

    if req_exp_years <= 0.0:
        experience_score = 100.0
    else:
        diff = cand_exp_years - req_exp_years
        if diff >= 0:
            experience_score = 100.0
        elif diff >= -1.0:
            experience_score = 80.0
        elif diff >= -2.0:
            experience_score = 60.0
        else:
            experience_score = round(max(20.0, (cand_exp_years / req_exp_years) * 100.0), 2)

    # 5. Location & Remote Fit (8% Weight)
    job_loc = str(job.get('location') or '').strip().lower()
    job_work_mode = str(job.get('work_mode') or '').strip().lower()
    cand_loc = str(cand.get('preferred_location') or cand.get('current_location') or '').strip().lower()
    cand_workplace = str(cand.get('workplace_type') or '').strip().lower()
    open_relocate = bool(cand.get('open_to_relocate'))

    is_job_remote = 'remote' in job_loc or job_work_mode == 'remote' or 'any' in job_loc or 'pan india' in job_loc
    prefers_remote = 'remote' in cand_workplace or 'flexible' in cand_workplace or cand_workplace == ''

    if is_job_remote:
        location_score = 100.0
    elif not cand_loc or not job_loc:
        location_score = 85.0 if open_relocate else 70.0
    elif job_loc in cand_loc or cand_loc in job_loc:
        location_score = 100.0
    elif open_relocate:
        location_score = 80.0
    elif prefers_remote and job_work_mode == 'onsite':
        location_score = 40.0
    else:
        location_score = 30.0

    # 6. Salary Fit (5% Weight)
    cand_ctc = cand.get('expected_ctc_inr')
    job_min = parse_salary_value_inr(job.get('salary_min'))
    job_max = parse_salary_value_inr(job.get('salary_max'))
    if not job_max and job.get('salary'):
        job_max = parse_salary_value_inr(job.get('salary'))

    if cand_ctc is None or cand_ctc <= 0 or (not job_min and not job_max):
        salary_score = 100.0
    else:
        eff_max = job_max or (job_min * 1.3 if job_min else 0)
        eff_min = job_min or (job_max * 0.7 if job_max else 0)
        if cand_ctc <= eff_max:
            salary_score = 100.0
        elif cand_ctc <= eff_max * 1.25:
            salary_score = 75.0
        else:
            salary_score = 40.0

    # 7. Employment Type Fit (3% Weight)
    job_emp_type = str(job.get('job_type') or '').strip().lower()
    cand_emp_type = str(cand.get('desired_emp_type') or '').strip().lower()

    if not cand_emp_type or not job_emp_type or 'flexible' in cand_emp_type or 'any' in cand_emp_type:
        work_mode_score = 100.0
    elif job_emp_type == cand_emp_type or job_emp_type in cand_emp_type or cand_emp_type in job_emp_type:
        work_mode_score = 100.0
    else:
        work_mode_score = 50.0

    # 8. Education Match (2% Weight)
    cand_edu_text = cand.get('education_text') or ''
    desc_lower = str(job.get('description') or '').lower()
    edu_keywords = ['b.tech', 'btech', 'b.e', 'm.tech', 'mtech', 'bca', 'mca', 'b.sc', 'bsc', 'mba', 'master', 'bachelor', 'phd', 'doctorate', 'diploma']
    job_required_edu = [kw for kw in edu_keywords if re.search(r'\b' + re.escape(kw) + r'\b', desc_lower)]

    if not job_required_edu:
        education_score = 100.0
    else:
        matched_edu = [kw for kw in job_required_edu if kw in cand_edu_text]
        if matched_edu:
            education_score = 100.0
        elif 'bachelor' in desc_lower or 'degree' in desc_lower or 'graduation' in desc_lower:
            education_score = 80.0 if any(deg in cand_edu_text for deg in ['b.tech', 'btech', 'b.e', 'bca', 'b.sc', 'bsc', 'bachelor', 'graduation']) else 40.0
        else:
            education_score = 50.0

    # Final Weighted Formula:
    # Skills: 35%, Semantic: 25%, Role: 12%, Exp: 10%, Location: 8%, Salary: 5%, WorkMode: 3%, Edu: 2%
    final_score = round(
        (skill_score * 0.35) +
        (semantic_score * 0.25) +
        (role_score * 0.12) +
        (experience_score * 0.10) +
        (location_score * 0.08) +
        (salary_score * 0.05) +
        (work_mode_score * 0.03) +
        (education_score * 0.02),
        2
    )

    # =====================================================================
    # TRANSPARENT EXPLAINABILITY REASON GENERATOR
    # =====================================================================
    display_title = job.get('title') or 'this'
    sample_matched = matched_skills[:3]
    sample_skills_str = ', '.join(sample_matched) if sample_matched else ''

    if required_skills and len(matched_skills) >= len(required_skills) and len(required_skills) >= 2:
        if sample_skills_str:
            match_reason = f"Recommended because you match all {len(required_skills)} required skills ({sample_skills_str})."
        else:
            match_reason = f"Recommended because you match all {len(required_skills)} required skills."
    elif required_skills and len(matched_skills) >= 2 and (len(matched_skills) / len(required_skills)) >= 0.5:
        match_reason = f"Recommended because this {display_title} role matches your {sample_skills_str} skills."
    elif is_job_remote and sample_skills_str:
        match_reason = f"Recommended because this Remote position matches your {sample_skills_str} skills."
    elif role_score >= 85.0 and sample_skills_str:
        match_reason = f"Recommended because this {display_title} role matches your {sample_skills_str} skills and preferred role."
    elif role_score >= 85.0:
        match_reason = f"Recommended because this role matches your target job title ({cand.get('preferred_role') or 'specialization'})."
    elif sample_skills_str:
        match_reason = f"Recommended because you match skills in {sample_skills_str}."
    elif semantic_score >= 70.0:
        match_reason = f"Recommended because your background strongly aligns with the {display_title} responsibilities."
    elif experience_score >= 90.0:
        match_reason = f"Recommended because this opportunity fits your experience profile."
    else:
        match_reason = f"Recommended based on your career interests and profile qualifications."

    return {
        'final_score': final_score,
        'skill_score': skill_score,
        'semantic_score': semantic_score,
        'role_score': role_score,
        'experience_score': experience_score,
        'location_score': location_score,
        'salary_score': salary_score,
        'work_mode_score': work_mode_score,
        'education_score': education_score,
        'matched_skills': matched_skills,
        'missing_skills': missing_skills,
        'match_reason': match_reason,
        'breakdown': {
            'skills': {'score': skill_score, 'weight': 35},
            'semantic': {'score': semantic_score, 'weight': 25},
            'role': {'score': role_score, 'weight': 12},
            'experience': {'score': experience_score, 'weight': 10},
            'location_remote': {'score': location_score, 'weight': 8},
            'salary': {'score': salary_score, 'weight': 5},
            'employment_type': {'score': work_mode_score, 'weight': 3},
            'education': {'score': education_score, 'weight': 2}
        }
    }


# =====================================================================
# 6. RECOMMENDATION PIPELINE & PERSISTENCE
# =====================================================================

def recommend_jobs_for_candidate(user_id, db_cursor_factory, model_getter=None, filters=None, limit=20, offset=0):
    """
    Computes top personalized job recommendations for a candidate with execution time telemetry.
    """
    start_time = time.perf_counter()
    filters = filters or {}

    with db_cursor_factory() as cur:
        cand_profile = get_candidate_recommendation_profile(user_id, cur)
        if not cand_profile:
            return {
                'recommendations': [],
                'total': 0,
                'page': 1,
                'per_page': limit,
                'total_pages': 1,
                'meta': {'latency_ms': 0.0, 'total_evaluated': 0, 'cached': False}
            }

        # Query all active, non-expired, non-deleted jobs
        query = """
            SELECT j.*, COALESCE(e.company_name, j.company_name) AS company_name,
                   e.is_verified AS employer_is_verified, e.verification_status AS employer_verification_status
            FROM jobs j
            LEFT JOIN employee e ON j.employer_id = e.id
            WHERE j.is_active = 1
              AND (j.is_deleted IS NULL OR j.is_deleted = 0)
              AND (j.application_deadline IS NULL OR j.application_deadline >= CURDATE())
        """
        params = []
        if filters.get('category'):
            query += " AND (j.category = %s OR j.category LIKE %s)"
            params.extend([filters['category'], f"%{filters['category']}%"])
        if filters.get('work_mode'):
            query += " AND j.work_mode LIKE %s"
            params.append(f"%{filters['work_mode']}%")
        if filters.get('location'):
            query += " AND j.location LIKE %s"
            params.append(f"%{filters['location']}%")

        query += " ORDER BY j.created_at DESC LIMIT 250"
        cur.execute(query, tuple(params))
        candidate_jobs = cur.fetchall() or []

    # Score each job
    scored_items = []
    min_score_threshold = float(filters.get('min_score', 40.0))

    for job in candidate_jobs:
        scoring = calculate_job_recommendation_score(job, cand_profile, model_getter)
        final_score = scoring['final_score']

        # Filter out obviously irrelevant jobs (score < threshold)
        if not cand_profile['is_sparse'] and final_score < min_score_threshold:
            continue

        item = dict(job)
        item['match_score'] = final_score
        item['match_reason'] = scoring['match_reason']
        item['matched_skills'] = scoring['matched_skills']
        item['missing_skills'] = scoring['missing_skills']
        item['skill_score'] = scoring['skill_score']
        item['semantic_score'] = scoring['semantic_score']
        item['breakdown'] = scoring['breakdown']
        scored_items.append(item)

    # If candidate profile is sparse, sort by newest and assign clear prompt reason
    if cand_profile['is_sparse']:
        for item in scored_items:
            item['match_reason'] = "Explore this featured role — complete your profile to get personalized AI matching."
            item['is_profile_sparse'] = True
    else:
        # Rank by final_score descending
        scored_items.sort(key=lambda x: (x['match_score'], x.get('id', 0)), reverse=True)

    total_count = len(scored_items)
    paginated_items = scored_items[offset:offset + limit]

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return {
        'recommendations': paginated_items,
        'total': total_count,
        'page': (offset // limit) + 1 if limit > 0 else 1,
        'per_page': limit,
        'total_pages': max(1, math.ceil(total_count / limit)) if limit > 0 else 1,
        'meta': {
            'latency_ms': elapsed_ms,
            'total_evaluated': len(candidate_jobs),
            'total_recommended': total_count,
            'cached': True,
            'is_sparse_profile': cand_profile['is_sparse']
        }
    }
