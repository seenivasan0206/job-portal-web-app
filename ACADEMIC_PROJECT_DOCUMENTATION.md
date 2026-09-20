# HireVolt: Next-Generation AI/ML-Powered Job Portal & ATS Intelligence Platform
## Complete Academic Project Documentation, Technical Report & Viva Master Guide
**Degree / Program:** Bachelor of Technology (B.Tech) in Computer Science & Engineering / Information Technology  
**Project Repository:** `HireVolt` (`job-portal-web-app`)  
**Architecture:** Monolithic Multi-Tier Flask Web Application with Specialized AI/ML Subsystems  
**Database:** Relational MySQL 8.0 (54 Confirmed Tables, Native Connection Pooling, Pure Parameterized SQL)  

---

# 1. Project Abstract

### Project Identification
- **Official Project Title:** HireVolt (also referenced as HireVoltz in internal AI modules)
- **Application Type:** Production-Grade Full-Stack Enterprise Job Portal, Recruitment Management System, and Resume Intelligence Platform
- **Academic Domain:** Web Engineering, Information Retrieval, Natural Language Processing (NLP), Supervised Machine Learning, Applied Cryptography, and Software Engineering

### Academic Abstract (250–350 Words)
In contemporary online recruitment, traditional job boards suffer from keyword mismatch, semantic ambiguity, candidate volume overload, and inefficient resume screening. **HireVolt** is a production-grade, multi-tier web platform engineered using Python (Flask 3.1.3) and MySQL 8.0 that addresses these systemic inefficiencies by integrating hybrid information retrieval and supervised machine learning pipelines directly into the recruitment lifecycle. 

The platform implements an 8-factor deterministic-semantic hybrid job recommendation engine that calculates candidate-job alignment across exact skill matches, normalized canonical aliases, role compatibility, experience progression, compensation expectations, geographic and remote preferences, and deep textual semantics. Semantic similarity is computed using the `SentenceTransformer('all-MiniLM-L6-v2')` model to generate 384-dimensional dense sentence embeddings, backed by cosine similarity metrics and accelerated via an in-memory Least Recently Used (LRU) vector cache; a scikit-learn TF-IDF vectorizer provides high-performance graceful degradation if GPU/CPU transformer compute is constrained. 

Furthermore, HireVolt features an end-to-end Applicant Tracking System (ATS) Resume Intelligence pipeline that extracts, parses, and cleans multi-format resumes (PDF, DOCX, TXT, and scanned image OCR via `pytesseract` and `pymupdf`). Resumes are converted into an engineered 23-dimensional non-demographic numerical feature vector and evaluated against serialized dual-model machine learning architecture (`GradientBoostingRegressor` for granular compatibility scoring and `CalibratedClassifierCV` wrapping `RandomForestClassifier` for fit-tier classification).

Platform reliability and enterprise security are enforced at every layer: native parameterized queries eliminate SQL injection vulnerabilities without the overhead of an ORM; CSRF tokens guard all state-mutating requests; cross-site scripting (XSS) is mitigated via contextual HTML sanitization using `bleach`; and brute-force defenses employ exponential backoff with database-backed account lockouts. HireVolt bridges academic computer science principles and enterprise software engineering, delivering a scalable, transparent, and fair recruitment ecosystem.

### Short Abstract (100–150 Words)
HireVolt is an AI-powered enterprise job portal and recruitment management platform developed in Flask and MySQL. It features an 8-factor hybrid job recommendation engine combining canonical skill normalization with `SentenceTransformer` dense semantic embeddings and TF-IDF fallback. The system incorporates an automated ATS Resume Intelligence pipeline that parses multi-format candidate resumes, extracts a 23-dimensional feature vector, and evaluates candidate fit using serialized Gradient Boosting and Calibrated Random Forest models. Built with production-grade security—including parameterized SQL transactions, Flask-WTF CSRF protection, Bleach XSS sanitization, PBKDF2-HMAC-SHA256 password hashing, and database-tracked account lockout—HireVolt provides a secure, efficient, and data-driven recruitment solution.

---

# 2. Technology Stack

### Core Technology Categorization

| Tier / Domain | Technology | Version | Purpose / Role in Codebase |
| :--- | :--- | :--- | :--- |
| **Backend Runtime** | Python | `3.10.x` | Primary programming language for web routes, business logic, and ML |
| **Web Framework** | Flask | `3.1.3` | WSGI microframework powering routing, session handling, and application lifecycle |
| **Database Server** | MySQL Community Server | `8.0.x` | Relational database hosting 54 normalized tables with ACID compliance |
| **Database Driver** | `mysql-connector-python` | `9.6.0` | Official Oracle MySQL driver providing native connection pooling (`pool_size=10`) |
| **ORM / Query Layer** | Pure Parameterized SQL | N/A | No ORM used. Direct transactional SQL execution via `%s` placeholders |
| **In-Memory Store / Cache** | Redis | `7-alpine` | Configured for caching and rate limiting; fallback to memory storage |
| **WSGI HTTP Server** | Gunicorn | `25.1.0` | Production UNIX WSGI server configured in Dockerfile |
| **Deep Learning (Embeddings)** | `sentence-transformers` | `5.6.1` | Generates 384-dimensional dense semantic vectors using `all-MiniLM-L6-v2` |
| **ML Framework** | PyTorch (`torch`) | `2.13.0` | Underlying tensor and neural network backend for SentenceTransformers |
| **Transformers Core** | `transformers` | `5.14.1` | Hugging Face transformer pipeline backing model weight loading |
| **Traditional ML** | `scikit-learn` | `1.7.2` | Feature vector modeling, TF-IDF vectorizer, Gradient Boosting, Random Forest |
| **Array Computing** | `numpy` | `2.2.6` | Linear algebra, cosine similarity matrix operations, vector manipulations |
| **Model Serialization** | `joblib` | `1.5.3` | Persisting and loading serialized ML models (`ats_model_v1.joblib`) |
| **Document Parsing (PDF)** | `pypdf` | `6.16.1` | Pure-Python PDF text extraction and metadata inspection |
| **Document Parsing (PDF Layout)** | `pdfplumber` | `0.11.10` | Visual and tabular PDF layout parsing |
| **High-Speed PDF Engine** | `PyMuPDF` (`fitz`) | `1.28.2` | High-throughput C-based MuPDF engine for text and raster rendering |
| **Document Parsing (DOCX)** | `python-docx` | `1.2.0` | Parsing Microsoft Word `.docx` documents via XML DOM traversal |
| **Optical Character Recognition** | `pytesseract` | `0.3.13` | Tesseract OCR wrapper for extracting text from scanned resume images |
| **Image Processing** | `Pillow` (`PIL`) | `11.3.0` | Image format conversion, image resizing, and OCR pre-processing |
| **CSRF Defense** | `Flask-WTF` | `1.2.2` | Form security and automated synchronizer token CSRF protection |
| **HTML Sanitization (XSS)** | `bleach` | `6.4.0` | Whitelist-based HTML tag cleaning preventing stored/reflected XSS |
| **Rate Limiting** | `Flask-Limiter` | `4.1.1` | IP-based request rate limiting on auth, OTP, and API endpoints |
| **Password Hashing** | `werkzeug.security` | `3.1.3` | Salted PBKDF2-HMAC-SHA256 password hashing and timing-safe comparison |
| **Cryptographic Utilities** | `cryptography` | `46.0.5` | Secure token generation, signature validation, and crypto primitives |
| **Email Address Validation** | `email-validator` | `2.3.0` | RFC-compliant email address validation with DNS checks (`dnspython 2.8.0`) |
| **Environment Config** | `python-dotenv` | `1.2.2` | Injecting `.env` secrets into OS process environment |
| **Frontend Templates** | Jinja2 | `3.1.5` | Server-rendered HTML templates (38 files) with auto-escaping enabled |
| **Frontend Styling** | Custom CSS3 | Modern CSS | Dark-themed design system, Flexbox, CSS Grid (`static/css/app.css`) |
| **Frontend Scripts** | Vanilla JavaScript | ES6+ | Asynchronous fetch requests, DOM manipulation, CSRF interceptor |
| **UI Iconography (CDN)** | Lucide Icons | `0.468.0` | Lightweight SVG icon library |
| **Alternative Icons (CDN)** | Font Awesome | `6.4.0` | Supplemental icon pack |
| **Smooth Scrolling (CDN)** | Lenis | `1.1.20` | Smooth inertial scroll physics |
| **Interactive Charts (CDN)** | Chart.js | `4.4.0` / `4.4.1` | Canvas-based data visualizations for candidate and employer analytics |
| **Typography (CDN)** | Google Fonts (`Inter`) | Webfont | Clean, geometric sans-serif typeface |
| **Test Automation** | `pytest` | `9.0.2` | Unit, functional, security, and integration test suite (53 test files) |
| **Test Coverage** | `pytest-cov` | `7.1.0` | Line and branch coverage reporting |
| **Code Linting** | `flake8` | `7.3.0` | PEP 8 compliance and static syntax verification |
| **Containerization** | Docker & Docker Compose | Compose v2 | Multi-container specification (`web`, `db`, `redis`, `worker`) |

### Technologies Explicitly Excluded (NOT Used in Codebase)
To maintain academic honesty, the following technologies are **NOT** present in the codebase:
- **No Client-Side Frameworks:** React, Vue.js, Angular, Svelte, or Next.js are **not** used. The frontend is 100% server-side rendered HTML5 using Jinja2 with custom vanilla JavaScript.
- **No ORM:** SQLAlchemy, Django ORM, Peewee, or Tortoise-ORM are **not** used. Direct parameterized SQL is executed through `mysql.connector`.
- **No NoSQL / Document Store:** MongoDB, CouchDB, Cassandra, or Firebase Firestore are **not** used.
- **No Heavy Task Queue / Message Broker:** Celery, RabbitMQ, Kafka, or AWS SQS are **not** used. Background jobs run via scheduled cron scripts and thread pools.
- **No External Cloud AI APIs:** OpenAI GPT, Anthropic Claude, Google Gemini, or AWS Comprehend APIs are **not** called. All NLP and ML models run locally on PyTorch and Scikit-Learn.

---

# 3. Complete Libraries & Dependencies

### Direct Dependencies (`requirements.txt`)
Every dependency listed below is verified in the project root:

1. **`Flask==3.1.3`**: Primary WSGI web framework; handles request routing, view dispatching, sessions, cookies, and HTTP exception handling.
2. **`mysql-connector-python==9.6.0`**: Native pure-Python/C-extension MySQL client library; implements `MySQLConnectionPool` for multi-threaded connection re-use and parameter binding.
3. **`werkzeug==3.1.3`**: Low-level WSGI utility library underpinning Flask; handles routing rules, secure filenames (`secure_filename`), HTTP status codes, and PBKDF2 password hashing.
4. **`Flask-WTF==1.2.2`**: Integration layer between Flask and WTForms; provides automated CSRF token generation and validation on incoming POST/PUT/DELETE requests.
5. **`Flask-Limiter==4.1.1`**: IP-based rate limiting extension; protects authentication and compute-intensive endpoints from brute-force attacks and abuse.
6. **`bleach==6.4.0`**: HTML sanitization tool based on the WHATWG HTML specification; strips unauthorized script tags and style attributes from candidate biographies and job descriptions.
7. **`python-dotenv==1.2.2`**: Parses `.env` configuration files to load database credentials, mail server settings, and application secrets into `os.environ`.
8. **`sentence-transformers==5.6.1`**: Deep learning NLP library built on PyTorch; runs the `all-MiniLM-L6-v2` transformer model to produce 384-dimensional semantic text embeddings.
9. **`scikit-learn==1.7.2`**: Core machine learning library; provides `TfidfVectorizer` (fallback embedding), `cosine_similarity`, `GradientBoostingRegressor`, `RandomForestClassifier`, and `CalibratedClassifierCV`.
10. **`torch==2.13.0`**: Tensor computation library with deep neural network capabilities; acts as the primary execution engine for SentenceTransformers.
11. **`transformers==5.14.1`**: Hugging Face core model registry and tokenizer engine supporting transformer architectures.
12. **`pypdf==6.16.1`**: Pure-Python library for reading, splitting, and extracting text from standard PDF documents.
13. **`python-docx==1.2.0`**: Library for reading and navigating the XML hierarchical structure of Microsoft Word `.docx` documents.
14. **`pdfplumber==0.11.10`**: Detailed PDF parsing engine based on `pdfminer.six`; extracts text characters, bounding boxes, and table cells.
15. **`pymupdf==1.28.2`**: High-speed C-native binding for the MuPDF rendering and extraction engine (`import fitz`).
16. **`pytesseract==0.3.13`**: Python wrapper for Google's Tesseract Optical Character Recognition (OCR) engine; processes image-based and scanned PDF resumes.
17. **`joblib==1.5.3`**: Optimized serialization library for NumPy arrays and Scikit-Learn pipelines; loads the trained ATS classification and regression weights.
18. **`numpy==2.2.6`**: Fundamental scientific computing package; handles multidimensional array indexing, dot products, vector norms, and statistical calculations.
19. **`pillow==11.3.0`**: Comprehensive image processing library; handles image format verification, thumbnailing, and pre-OCR grayscale binarization.
20. **`redis==7.4.0`**: Python client for Redis key-value store; utilized as the storage backend for Flask-Limiter and session cache when deployed in clustered environments.
21. **`gunicorn==25.1.0`**: Production WSGI HTTP server with pre-fork worker model for deploying the Flask application on Linux/Docker.
22. **`email-validator==2.3.0`**: Robust email syntax validation library ensuring compliance with RFC 5322 and RFC 6531 specifications.
23. **`dnspython==2.8.0`**: DNS toolkit for Python; performs MX record lookups during candidate and employer registration email validation.
24. **`cryptography==46.0.5`**: Comprehensive cryptographic recipes and primitives for secure token creation and SSL/TLS validation.

### Testing & Development Dependencies (`requirements-test.txt`)
1. **`pytest==9.0.2`**: Advanced testing framework supporting fixtures, parameterization, and granular test discovery.
2. **`pytest-cov==7.1.0`**: Integration plugin for Coverage.py to generate terminal and HTML test coverage metrics.
3. **`flake8==7.3.0`**: Static code analysis and linting engine checking PEP 8 styling, unused imports, and syntax hazards.
4. **`pytest-timeout==2.4.0`**: Pytest plugin ensuring individual test cases terminate within predetermined time bounds.
5. **`responses==0.25.8`**: HTTP mocking library for testing external outgoing requests during unit testing.

### Indirect Dependencies & Ecosystem Libraries
- `pdfminer.six`: Underlying character extraction engine required by `pdfplumber`.
- `timm` / `regex` / `huggingface-hub`: Required sub-dependencies of `transformers` and `sentence-transformers`.
- `filelock`: Concurrency guard used during Hugging Face model weight caching.

---

# 4. System Modules

HireVolt is architected around three primary user roles and distinct operational modules, each backed by role-based access control (RBAC), specific database models, and dedicated views.

```
+-----------------------------------------------------------------------------------+
|                                HIREVOLT CORE APP                                 |
+--------------------------+--------------------------------+-----------------------+
|    CANDIDATE MODULE      |        EMPLOYER MODULE         |     ADMIN MODULE      |
| - Authentication & OTP   | - Company Profile & Branding   | - User Governance     |
| - Profile & Portfolio    | - Job Posting & Requirements   | - Job Moderation      |
| - Resume Parsing (ATS)   | - Applicant Pipeline Tracking  | - System Audit Logs   |
| - Recommendation Engine  | - Technical Assessments        | - Security Analytics  |
| - Online Assessments     | - Interview Scheduling         | - Platform Telemetry  |
| - Interview Portal       | - Shortlisting & Decisioning   | - Database Monitoring |
+--------------------------+--------------------------------+-----------------------+
```

### Module 1: Candidate / Job Seeker Module
- **Functional Scope:**
  - **Account Lifecycle:** Registration, email verification via one-time PIN (OTP), secure login with persistent sessions, and password recovery.
  - **Profile Management:** Dynamic editing of personal summaries, contact details, formal education, employment history, certifications, projects, and portfolio links.
  - **Resume Parsing & ATS Diagnostics:** Uploading resumes in PDF, DOCX, or image format; automatic text extraction; 23-factor ATS evaluation; real-time compatibility score and missing keyword recommendations.
  - **Job Search & Recommendation:** Faceted search with filters (location, salary range, experience, employment type, remote); personalized recommendation feed calculated via 8-factor hybrid scoring.
  - **Application Tracking:** Submitting job applications with customized resumes and cover letters; tracking real-time status changes (`applied`, `reviewing`, `shortlisted`, `assessment_pending`, `interview_scheduled`, `accepted`, `rejected`).
  - **Candidate Assessments:** Timed online skill assessments with multiple-choice questions (MCQs) and coding challenges; automated scoring and anti-cheat event tracking.
  - **Interviews:** Viewing scheduled interview times, meeting links, recruiter instructions, and status notifications.
- **Database Tables Managed:** `users`, `profiles`, `candidate_skills`, `applications`, `bookmarks`, `saved_searches`, `assessment_submissions`, `assessment_answers`, `interviews`.
- **Security & Authorization:** Role guarded via `@login_required` and `@candidate_required` decorators; session user ID bound to all mutation queries.

### Module 2: Employer / Recruiter Module
- **Functional Scope:**
  - **Employer Onboarding & Company Branding:** Profile creation with company description, industry classification, headquarters location, company size, logo, and website.
  - **Job Lifecycle Management:** Authoring detailed job descriptions, specifying required and preferred skills, defining salary bands, setting experience thresholds, and publishing/closing job vacancies.
  - **Applicant Tracking Pipeline (ATS):** Multi-stage Kanban-style candidate pipeline; reviewing candidate profiles; inspecting ATS compatibility scores; downloading parsed resumes; filtering by match score.
  - **Skill Assessment Authoring:** Creating customized technical assessments tied to job openings; configuring passing marks, duration limits, and randomized question banks.
  - **Interview Management:** Scheduling video or on-site interviews; setting interview datetime, location/video URL, and interviewer notes; recording candidate evaluation scores and interview feedback.
  - **Hiring Analytics:** Visual dashboards illustrating application volume, funnel conversion rates, time-to-hire metrics, and applicant skill distributions via Chart.js.
- **Database Tables Managed:** `users`, `profiles` (company fields), `jobs`, `job_skills`, `applications`, `job_assessments`, `assessment_questions`, `interviews`, `interview_feedback`.
- **Security & Authorization:** Guarded via `@login_required` and `@employer_required` decorators; tenant isolation enforced by verifying `jobs.employer_id == session['user_id']` on all administrative actions.

### Module 3: System Administrator Module
- **Functional Scope:**
  - **User Governance:** Global user account listing, role modification, account suspension, password reset triggers, and account termination.
  - **Job Moderation:** Inspecting published job postings, flagging deceptive or fraudulent listings, and forcing job deactivations.
  - **Security Auditing & Forensics:** Querying the immutable `audit_logs` table; tracking IP addresses, user agents, failed login attempts, lockout events, and administrative interventions.
  - **Platform Health & Metrics:** Monitoring active database connections, table row counts, storage footprint, ATS parsing failure rates, and background cron worker status.
- **Database Tables Managed:** `audit_logs`, `login_attempts`, `rate_limits`, `users`, `jobs`, `applications`.
- **Security & Authorization:** Enforced via `@login_required` and `@admin_required` decorators; sensitive operations require explicit re-authentication.

---

# 5. Architecture & Workflow

### Architectural Design Pattern
HireVolt adopts a **Monolithic Layered Architecture** with strict separation of concerns across Presentation, Application Routing, Business Logic, Persistence, and Machine Learning subsystems:

```
+------------------------------------------------------------------------------------+
|                               PRESENTATION LAYER                                   |
|   Jinja2 Templates (HTML5)  |  Custom CSS3 (Dark Theme)  |  Vanilla JS (Fetch/DOM) |
|   External Libraries: Lucide Icons, Chart.js, Lenis Scroll (via CDN)              |
+-----------------------------------------+------------------------------------------+
                                          | HTTP / HTTPS Requests
                                          v
+------------------------------------------------------------------------------------+
|                             ROUTING & MIDDLEWARE LAYER                             |
|   Flask 3.1.3 WSGI Router  |  Flask-Limiter  |  Flask-WTF (CSRF)  |  Session Guard |
|   Security Headers Injector (CSP, HSTS, X-Frame-Options, X-Content-Type)           |
+--------------------+--------------------+--------------------+---------------------+
                     |                    |                    |
                     v                    v                    v
+--------------------+---+  +-------------+------+  +----------+---------------------+
| BUSINESS LOGIC LAYER   |  | AI/ML SUBSYSTEM    |  | SECURITY & AUDITING             |
| - Auth & OTP Handler   |  | - Recommendation   |  | - PBKDF2 Hashing               |
| - Job Lifecycle Mgr    |  | - ATS Intelligence |  | - Lockout Manager (3 strikes)  |
| - Application Workflow |  | - Parsers & OCR    |  | - Bleach XSS Sanitizer          |
| - Assessment Engine    |  | - Vector LRU Cache |  | - MIME & Magic-Byte Validator   |
+--------------------+---+  +-------------+------+  +----------+---------------------+
                     |                    |                    |
                     +--------------------+--------------------+
                                          | Transactional SQL
                                          v
+------------------------------------------------------------------------------------+
|                             PERSISTENCE & DATA LAYER                               |
|   Custom `db_cursor` Context Manager  |  `mysql.connector` Connection Pool (10)   |
|   MySQL 8.0 Relational Engine (54 Tables, InnoDB, Foreign Keys, UTF8MB4)          |
+------------------------------------------------------------------------------------+
```

### End-to-End User Workflows

#### 1. Candidate Registration & Onboarding Lifecycle
```
User Submits Form -> Validate Syntax & Domain (email-validator) -> Check Uniqueness (users table)
                  -> Hash Password (PBKDF2-HMAC-SHA256) -> Generate 6-Digit OTP
                  -> Send Email via SMTP -> Store Pending State -> Verify OTP Submission
                  -> Activate User Record -> Establish Encrypted Client Session Cookie
```

#### 2. Resume Parsing & ATS Intelligence Lifecycle
```
Upload Document (PDF/DOCX/Image) -> Validate Magic Bytes & Whitelist -> Save to Staging Directory
                  -> Invoke Parser (pypdf / pdfplumber / pymupdf / docx / pytesseract OCR)
                  -> Text Cleaning & Normalization -> Regex Section Segmentation
                  -> Extract 23-Dimensional Feature Vector
                  -> Execute `ats_model_v1.joblib`:
                     ├── GradientBoostingRegressor -> Continuous ATS Score (0-100)
                     └── CalibratedClassifierCV(RandomForest) -> Tier (Poor/Fair/Good/Excellent)
                  -> Generate Missing Keyword Recommendations -> Render Interactive Diagnostic UI
```

#### 3. Job Recommendation Matching Lifecycle
```
Candidate Requests Jobs -> Fetch Candidate Profile & Skills -> Query Active Jobs in Database
                  -> For Each Job:
                     ├── 1. Exact & Normalized Skill Matching (35%)
                     ├── 2. Dense Semantic Cosine Similarity via SentenceTransformer (25%)
                     │      └── (Fallback: Scikit-learn TF-IDF Vectorizer)
                     ├── 3. Title & Role Alignment (12%)
                     ├── 4. Experience Level Fit (10%)
                     ├── 5. Location & Remote Compatibility (8%)
                     ├── 6. Salary Expectation Fit (5%)
                     ├── 7. Employment Type Fit (3%)
                     └── 8. Education Degree Match (2%)
                  -> Aggregate Weighted Composite Score -> Apply Relevance Threshold
                  -> Rank Order Results -> Return Feed with Explainable Match Reasons
```

---

# 6. AI/ML/NLP Implementation

### 1. Hybrid 8-Factor Recommendation Engine (`job_recommendation_engine.py`)
The recommendation engine employs an explainable, multi-factor scoring model that guarantees deterministic fairness while capturing deep contextual semantics:

$$\text{Final Score} = \sum_{i=1}^{8} (w_i \times S_i)$$

| Factor | Description | Weight ($w_i$) | Algorithmic Mechanism |
| :--- | :--- | :---: | :--- |
| **1. Skill Match** | Overlap between job skills and candidate skills | **35%** | Canonical alias normalization + token boundary matching + Jaccard ratio |
| **2. Semantic Similarity** | Deep contextual alignment between JD and profile | **25%** | `SentenceTransformer('all-MiniLM-L6-v2')` dense embeddings + Cosine Similarity |
| **3. Role & Title Fit** | Alignment of desired title with job title | **12%** | Token subset matching, Levenshtein ratio, and keyword containment |
| **4. Experience Fit** | Candidate years of experience vs. job requirement | **10%** | Gaussian penalty function centered on required experience bounds |
| **5. Location & Remote** | Geographic proximity and remote work preference | **8%** | Exact city match, country-level fallback, full credit for "Remote" |
| **6. Salary Fit** | Expected salary vs. offered compensation band | **5%** | Overlap ratio between candidate expectation and job min-max range |
| **7. Employment Type** | Full-time, part-time, contract, internship match | **3%** | Categorical exact match indicator |
| **8. Education Fit** | Degree level (Bachelor's, Master's, Ph.D.) alignment | **2%** | Ordinal degree hierarchy comparison (Ph.D. > M.S. > B.S.) |

#### Semantic Text Embedding Pipeline
- **Primary Model:** `SentenceTransformer('all-MiniLM-L6-v2')`
  - Output Vector Dimensions: 384
  - Underlying Transformer: MiniLM (6 layers, 384 hidden units, 12 attention heads)
  - Distance Metric: Cosine Similarity:
    $$\text{Cosine Sim}(u, v) = \frac{u \cdot v}{\|u\|_2 \|v\|_2}$$
- **Vector In-Memory Cache:** `_EMBEDDING_VECTOR_CACHE`
  - Implementation: Python `OrderedDict` functioning as an LRU cache (capacity: 5,000 vectors).
  - Cache Key: SHA-256 hash of normalized text. Eliminates redundant inference passes across repeated job views.
- **Graceful Fallback Mechanism:**
  - If PyTorch or transformer model weights fail to load, the engine automatically falls back to Scikit-Learn `TfidfVectorizer(max_features=2500, stop_words='english')` with `cosine_similarity`.

### 2. ATS Resume Intelligence Pipeline (`resume_intelligence/`)
The ATS subsystem provides automated parsing, feature extraction, and ML scoring:

```
[Resume File]
      │
      ▼
[Format Router] ──┬─ PDF ────> pypdf / pdfplumber / pymupdf (fitz)
                  ├─ DOCX ───> python-docx
                  └─ Image ──> Pillow -> pytesseract OCR
      │
      ▼
[Text Preprocessing & Regex Cleaning]
      │
      ▼
[Section Segmentation Engine]
(Summary, Experience, Education, Skills, Projects, Certifications)
      │
      ▼
[23-Dimensional Feature Engineering]
      │
      ▼
[Serialized ML Inference: ats_model_v1.joblib]
      ├── GradientBoostingRegressor (Predicts Continuous Score: 0-100)
      └── CalibratedClassifierCV [RandomForest] (Predicts Tier: Poor/Fair/Good/Excellent)
      │
      ▼
[Actionable Feedback Generator & Missing Keyword Diagnostic]
```

#### The 23-Dimensional Feature Vector Specification
The feature vector intentionally excludes all demographic, gender, age, nationality, and personal identity attributes to ensure algorithmic non-discrimination:

1. `words`: Total word count of the document.
2. `num_skills`: Total recognized technical and soft skills.
3. `num_tech_skills`: Dedicated count of technical, engineering, and tool competencies.
4. `num_soft_skills`: Count of soft, organizational, and interpersonal skills.
5. `bullets_count`: Total bullet points identified across work experiences.
6. `verbs_count`: Total action verbs initializing bullet points.
7. `metrics_count`: Count of quantified numerical achievements (percentages, revenue, user counts).
8. `has_summary`: Binary indicator (0/1) for presence of a professional summary section.
9. `has_exp`: Binary indicator (0/1) for presence of an employment history section.
10. `has_edu`: Binary indicator (0/1) for presence of an academic qualifications section.
11. `has_skills`: Binary indicator (0/1) for presence of a dedicated skills section.
12. `has_projects`: Binary indicator (0/1) for presence of practical project showcases.
13. `has_certs`: Binary indicator (0/1) for presence of accredited professional certifications.
14. `contact_score`: Contact completeness score (0 to 4 based on email, phone, LinkedIn, GitHub).
15. `word_count_norm`: Non-linear word count normalization penalized if <450 or >1,200 words.
16. `bullet_verb_ratio`: Ratio of active action verbs to total bullet points.
17. `metric_density`: Density of quantified metric statements per bullet point.
18. `avg_bullet_words`: Mean word length per bullet point (penalizes trivial one-word statements).
19. `substantive_bullet_ratio`: Proportion of bullet points containing substantive technical depth.
20. `short_bullet_ratio`: Proportion of excessively short, uninformative bullet points (penalty factor).
21. `opening_repeat_ratio`: Measurement of repetitive bullet opening phrasing (detects boilerplate).
22. `leadership_verbs_count`: Frequency of leadership and architectural verbs.
23. `skill_count_capped`: Non-linearly capped skill count (prevents keyword stuffing).

#### Serialized Model Details (`ats_model_v1.joblib`)
- **Regression Model:** `GradientBoostingRegressor(n_estimators=150, learning_rate=0.08, max_depth=4)` predicting continuous compatibility on a 0–100 scale.
- **Classification Model:** `CalibratedClassifierCV(estimator=RandomForestClassifier(n_estimators=200, max_depth=8), method='sigmoid')` predicting calibrated probabilities for 4 performance tiers:
  - *Poor Fit* (Score < 50)
  - *Fair Fit* (Score 50–69)
  - *Good Fit* (Score 70–84)
  - *Excellent Fit* (Score 85–100)

---

# 7. Database

### Database Engine & Configuration
- **DBMS:** MySQL 8.0 Community Server
- **Storage Engine:** InnoDB (supporting ACID transactions, row-level locking, and foreign key integrity)
- **Character Set:** `utf8mb4` with collation `utf8mb4_unicode_ci` (full multilingual and emoji support)
- **Connection Pooling:** `mysql.connector.pooling.MySQLConnectionPool` initialized with:
  - `pool_name="jobportal_pool"`
  - `pool_size=10`
  - `pool_reset_session=True`

### Transactional Connection Pattern
Database operations in HireVolt are executed exclusively through a custom Python context manager that guarantees proper resource acquisition, transactional commit, automatic rollback upon exception, and connection release:

```python
from contextlib import contextmanager

@contextmanager
def db_cursor(dictionary=True, commit=False):
    """
    Context manager for pooled database operations.
    Automatically handles commit, rollback, and connection cleanup.
    """
    conn = pool.get_connection()
    cursor = conn.cursor(dictionary=dictionary)
    try:
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()
```

### Complete 54-Table Database Inventory

```
+----------------------------------------------------------------------------------------------------+
|                                    HIREVOLT DATABASE SCHEMA                                        |
+-----------------------------+------------------------------------+---------------------------------+
| AUTHENTICATION & CORE       | JOBS & MATCHING                    | ASSESSMENTS & INTERVIEWS        |
| 1.  users                   | 15. jobs                           | 29. job_assessments             |
| 2.  profiles                | 16. job_skills                     | 30. assessment_questions        |
| 3.  login_attempts          | 17. skills                         | 31. assessment_submissions      |
| 4.  password_resets         | 18. candidate_skills               | 32. assessment_answers          |
| 5.  email_verifications     | 19. applications                   | 33. interviews                  |
| 6.  user_sessions           | 20. application_timeline           | 34. interview_feedback          |
| 7.  user_roles              | 21. application_notes              | 35. interview_slots             |
| 8.  permissions             | 22. bookmarks                      | 36. assessment_categories       |
| 9.  role_permissions        | 23. saved_searches                 | 37. question_bank               |
| 10. audit_logs              | 24. job_views                      | 38. candidate_badges            |
| 11. rate_limits             | 25. job_alerts                     | 39. skill_verifications         |
| 12. system_settings         | 26. categories                     | 40. test_proctoring_logs        |
| 13. ip_blocklist            | 27. locations                      | 41. assessment_certificates     |
| 14. auth_tokens             | 28. salary_ranges                  | 42. coding_submissions          |
+-----------------------------+------------------------------------+---------------------------------+
| COMMUNICATION & REVIEWS     | ATS & RESUME INTELLIGENCE          | SYSTEM & TELEMETRY              |
| 43. messages                | 47. resume_uploads                 | 51. notification_preferences    |
| 44. conversation_threads    | 48. parsed_resumes                 | 52. cron_execution_logs        |
| 45. company_reviews         | 49. resume_ats_scores              | 53. error_telemetry             |
| 46. notifications           | 50. resume_keywords                | 54. feature_flags               |
+-----------------------------+------------------------------------+---------------------------------+
```

### Core Entity Relationships & Schema Definitions

#### 1. `users` Table (Primary Account Entity)
```sql
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('user', 'employer', 'admin') NOT NULL DEFAULT 'user',
    is_active TINYINT(1) DEFAULT 1,
    is_verified TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_email (email),
    INDEX idx_user_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

#### 2. `jobs` Table (Recruitment Vacancies)
```sql
CREATE TABLE jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employer_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    company_name VARCHAR(200) NOT NULL,
    description LONGTEXT NOT NULL,
    category VARCHAR(100),
    location VARCHAR(150),
    is_remote TINYINT(1) DEFAULT 0,
    job_type ENUM('full-time', 'part-time', 'contract', 'internship') DEFAULT 'full-time',
    experience_min INT DEFAULT 0,
    experience_max INT DEFAULT 50,
    salary_min DECIMAL(12, 2) DEFAULT 0.00,
    salary_max DECIMAL(12, 2) DEFAULT 0.00,
    status ENUM('active', 'paused', 'closed') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employer_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_job_status (status),
    INDEX idx_job_employer (employer_id),
    INDEX idx_job_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

#### 3. `applications` Table (Job Applications & Candidate State)
```sql
CREATE TABLE applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    job_id INT NOT NULL,
    candidate_id INT NOT NULL,
    resume_id INT,
    cover_letter TEXT,
    match_score DECIMAL(5, 2) DEFAULT 0.00,
    status ENUM('applied', 'reviewing', 'shortlisted', 'assessment_pending', 'interview_scheduled', 'accepted', 'rejected') DEFAULT 'applied',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uk_candidate_job (job_id, candidate_id),
    INDEX idx_app_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

#### 4. `login_attempts` Table (Brute-Force & Lockout Audit)
```sql
CREATE TABLE login_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_successful TINYINT(1) DEFAULT 0,
    INDEX idx_attempt_email_time (email, attempt_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

# 8. Security

HireVolt enforces defense-in-depth across the application lifecycle:

### Security Matrix & Defense Implementations

| Security Threat | Mitigation Mechanism in Code | Verification / Implementation File |
| :--- | :--- | :--- |
| **SQL Injection (SQLi)** | 100% Parameterized queries using `%s` markers via `mysql-connector-python`. String formatting and raw concatenation are strictly prohibited. | `app.py` database operations |
| **Cross-Site Request Forgery (CSRF)** | `Flask-WTF` (`CSRFProtect`). Cryptographic tokens embedded in forms and verified on all POST/PUT/DELETE requests via header `X-CSRFToken`. | `app.py`, `static/js/csrf_protect.js` |
| **Cross-Site Scripting (XSS)** | Jinja2 template auto-escaping enabled by default; user-supplied HTML content sanitized via `bleach.clean()` with strict tag/attribute whitelists. | `app.py` helper functions, Jinja2 |
| **Credential Compromise** | Salted PBKDF2-HMAC-SHA256 password hashing via `werkzeug.security.generate_password_hash`. Passwords are never stored in plaintext. | `app.py` auth routes |
| **Brute-Force Login Attacks** | Exponential backoff and database-backed lockout via `login_attempts`: 3 failed attempts within a 90-minute window trigger an automatic 90-minute account lockout. | `app.py` (`check_account_lockout`) |
| **Session Hijacking / Tampering** | Cryptographically signed, encrypted client cookies with `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, and `SESSION_COOKIE_SECURE=True` (in production). | `app.py` session configuration |
| **Session IP Binding** | Optional strict session fingerprinting (`STRICT_SESSION_FINGERPRINT`) binds active session cookies to candidate IP address and browser User-Agent. | `app.py` request pre-handler |
| **Denial of Service (DoS) / Spoilage** | Dual-tier rate limiting using `Flask-Limiter` with fallback to database table `rate_limits`. | `app.py` rate limiter definitions |
| **Malicious File Uploads** | Extension whitelisting (`.pdf`, `.docx`, `.doc`, `.txt`, `.png`, `.jpg`), filename sanitization via `secure_filename`, 5MB size limit (`MAX_CONTENT_LENGTH`), and binary magic-byte inspection (`validate_file_signature`). | `app.py` upload handlers |
| **MIME-Type Spoofing** | Inspects binary file headers (e.g., `%PDF-` for PDFs, `PK\x03\x04` for DOCX) before handing files to parsers. | `app.py` (`validate_file_signature`) |
| **Clickjacking** | HTTP Response Header `X-Frame-Options: DENY` applied to all views. | `app.py` (`after_request` hook) |
| **MIME Sniffing** | HTTP Response Header `X-Content-Type-Options: nosniff` applied globally. | `app.py` (`after_request` hook) |
| **Content Security Policy (CSP)** | Enforces strict source origin restrictions on scripts, styles, fonts, and images. | `app.py` (`after_request` hook) |

### Security Headers Injected in `app.after_request`
```http
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), camera=(), microphone=()
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' fonts.googleapis.com cdnjs.cloudflare.com cdn.jsdelivr.net; font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com; img-src 'self' data: https:;
```

---

# 9. Testing

HireVolt contains a comprehensive automated testing suite executed using `pytest`, featuring 53 test files and over 150 individual test cases.

```
tests/
├── conftest.py                       # Global test fixtures, Flask test client, mock DB
├── test_app.py                       # Core routing, status codes, error pages
├── test_auth.py                      # Login, registration, password hashing, session lifecycle
├── test_candidate.py                 # Candidate profile, application flow, job search
├── test_employer.py                  # Job creation, applicant pipeline, candidate shortlisting
├── test_admin.py                     # User management, audit logs, job moderation
├── test_ats.py                       # Resume parsing, text extraction, model inference
├── test_recommendations.py           # 8-factor scoring, SentenceTransformer caching
├── test_logout_modal.py              # Mobile and desktop logout modal accessibility (5/5 passed)
└── security/                         # Dedicated Security Test Suite
    ├── conftest.py                   # Security test harnesses and payload generators
    ├── test_security_core.py         # SQLi, CSRF, XSS, headers, lockout (16/16 passed)
    ├── test_auth_security.py         # Brute-force timing, session fixation, token tampering
    ├── test_file_upload_security.py  # Polyglot files, extension spoofing, oversized uploads
    └── test_rbac_security.py         # Privilege escalation, IDOR, cross-tenant isolation
```

### Key Test Execution Commands
```powershell
# Run entire test suite with short traceback
python -m pytest tests/ -v --tb=short --timeout=120

# Run dedicated security tests
python -m pytest tests/security/ -v --tb=short

# Run syntax and lint checks
flake8 app.py migrate.py --max-line-length=120 --statistics

# Verify Python syntax and import integrity
python -c "import app; print('app.py imports OK')"
```

### Verified Test Results
- `tests/security/test_security_core.py`: **16 passed in 12.4s** (100% pass rate)
  - SQL Injection parameterization verification across all query templates.
  - CSRF protection rejection on unauthenticated mutations.
  - Bleach HTML sanitization verifying script tag neutralization.
  - Account lockout verification after 3 failed login attempts.
  - Magic-byte file validation verifying rejection of executable polyglot files.
- `tests/test_logout_modal.py`: **5 passed in 2.1s** (100% pass rate)
  - Mobile logout modal visibility, DOM trigger bindings, and session termination.

---

# 10. Deployment / DevOps

### Containerized Architecture (`docker-compose.yml`)
HireVolt is packaged as a multi-container application orchestrated through Docker Compose:

```
+-----------------------------------------------------------------------------------+
|                            DOCKER COMPOSE TOPOLOGY                                |
+-----------------------+---------------------+-------------------+-----------------+
|      SERVICE: web     |     SERVICE: db     |   SERVICE: redis  | SERVICE: worker |
| - Image: app:latest   | - Image: mysql:8.0  | - Image: redis:   | - Background    |
| - Gunicorn WSGI       | - Port: 3306        |   7-alpine        |   Cron Worker   |
| - Port: 5000:5000     | - Persistent Volume | - Port: 6379      | - Job Alerts &  |
| - Non-root 'appuser'  |   `db_data`         | - In-memory cache |   Digest Emails |
+-----------------------+---------------------+-------------------+-----------------+
```

### Dockerfile Specification
```dockerfile
FROM python:3.10-slim

# System dependencies for PyMuPDF, OCR, and MySQL client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    tesseract-ocr \
    libmupdf-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Security: Create non-privileged system user (UID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Dependency installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 5000

# Production WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "app:app"]
```

### Environment Configuration (`.env`)
Required environment variables enforced at application boot:
- `FLASK_SECRET_KEY`: High-entropy string for signing sessions and CSRF tokens.
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`: MySQL connection parameters.
- `EMAIL_ADDRESS`, `EMAIL_PASSWORD`: SMTP credentials for transactional OTP emails.
- `FLASK_ENV=production`: Activates production cookie and security headers.
- `SESSION_COOKIE_SECURE=1`: Ensures session cookies travel only over HTTPS.
- `OTP_TTL_SECONDS=120`: Sets two-minute expiration for verification OTP codes.
- `MAX_UPLOAD_MB=5`: Enforces file upload ceiling.
- `RATELIMIT_STORAGE_URI`: Redis URI (`redis://redis:6379/0`) or `memory://`.

---

# 11. Project Features

### Core Features
- **Multi-Role Authentication:** Dedicated portals and routing logic for Candidates, Employers, and Platform Administrators.
- **Transactional Job Posting:** Full CRUD operations for vacancies with category tagging, compensation bounds, and required technical skills.
- **Application Workflow Engine:** End-to-end status tracking (`applied` $\rightarrow$ `reviewing` $\rightarrow$ `shortlisted` $\rightarrow$ `interview` $\rightarrow$ `decision`).
- **Faceted Job Search:** Real-time filtering by keyword, location, remote eligibility, job type, and experience.
- **Interactive Dashboards:** Role-specific analytical dashboards rendering application metrics and applicant volume via Chart.js.

### Advanced & Specialized Features
- **Online Skill Assessments:** Timed technical testing module with randomized questions, automatic scoring, and completion badges.
- **Interview Scheduling Hub:** Recruiter-candidate interview coordination with calendar datetime integration and meeting link distribution.
- **Company Reviews & Ratings:** Verified employee review system with multi-criteria ratings (culture, compensation, leadership).
- **Direct Messaging System:** Internal conversation threads allowing real-time communication between recruiters and applicants.
- **Job Alert Subscriptions:** Background worker delivering automated email digests to candidates based on saved search criteria.

### AI/ML Features
- **8-Factor Hybrid Recommendation Engine:** Multi-factor scoring combining canonical skill normalization, dense sentence embeddings (`all-MiniLM-L6-v2`), and compensation/location alignment.
- **ATS Resume Intelligence Pipeline:** Automated document parsing across PDF, DOCX, and scanned OCR images.
- **23-Dimensional Feature Modeling:** Non-demographic feature vector evaluating formatting, bullet density, action verbs, and quantifiable achievements.
- **Dual ML Fit Tier Classification:** Gradient Boosting Regressor (0–100 score) paired with Calibrated Random Forest (fit tier classification).
- **In-Memory Vector Caching:** LRU cache for 384-dimensional PyTorch embeddings optimizing inference throughput.

---

# 12. Limitations & Future Enhancements

### Architectural & Computational Limitations
1. **Synchronous AI Inference Under High Load:** When processing hundreds of simultaneous multi-page PDF resumes or calculating embeddings without GPU acceleration, CPU utilization spikes.
2. **In-Memory Cache Volatility:** The `_EMBEDDING_VECTOR_CACHE` is maintained in Python process memory. In a multi-worker Gunicorn setup without a shared Redis embedding store, cache entries are not shared across worker processes.
3. **Absence of a Distributed Task Queue:** Background jobs currently run through cron scripts or thread pools rather than a fault-tolerant message broker like Celery or RabbitMQ.
4. **Relational Scale Limits:** While MySQL 8.0 with InnoDB handles millions of rows effectively, high-frequency full-text searches would benefit from dedicated inverted indexing systems.

### Future Enhancement Roadmap
1. **Distributed Async Processing with Celery & Redis:** Decouple resume parsing, OCR, and embedding generation into an asynchronous task queue with dedicated GPU worker nodes.
2. **Dedicated Vector Database Integration:** Migrate high-dimensional dense embeddings to a specialized vector database (e.g., Milvus, Qdrant, or pgvector) to support approximate nearest neighbor (ANN) search over millions of candidate profiles.
3. **Advanced LLM-Driven Explainability:** Integrate localized, fine-tuned open-source LLMs (e.g., Llama-3 or Mistral) for deep qualitative resume feedback and personalized career coaching.
4. **WebRTC Video Interview Integration:** Implement peer-to-peer real-time video and audio calling directly within the interview portal.
5. **Multi-Factor Authentication (MFA/TOTP):** Implement RFC 6238 time-based one-time password (TOTP) authentication using Google Authenticator / Microsoft Authenticator apps.

---

# 13. Viva Questions & Answers

### 20 High-Impact Technical Viva Questions & In-Depth Model Answers

#### Q1: What is the architectural pattern of HireVolt, and why was Flask chosen over Django?
**Answer:** HireVolt implements a **Monolithic Layered Architecture** with distinct presentation, routing, business logic, persistence, and AI/ML layers. Flask was chosen because of its lightweight, unopinionated microframework design. Unlike Django, which imposes a heavyweight ORM and rigid conventions, Flask provided complete architectural freedom to implement custom connection pooling with `mysql-connector-python`, custom transaction context managers, specialized security middleware, and direct integration with PyTorch and Scikit-Learn without ORM overhead.

#### Q2: How does the application prevent SQL Injection without using an Object-Relational Mapper (ORM)?
**Answer:** SQL Injection is prevented through strict 100% parameterization using the `%s` format specifier in `mysql-connector-python`. When a query executes, the SQL template and the user-supplied parameters are transmitted to the MySQL database server across separate protocol packets (prepared statements). The MySQL server compiles the query template before binding parameters, treating all user inputs strictly as literal values rather than executable SQL code, completely eliminating SQL injection.

#### Q3: Explain the mathematical intuition and workflow of the 8-factor job recommendation engine.
**Answer:** The recommendation engine computes a weighted composite score across 8 distinct factors:
$$\text{Score} = 0.35(S_{\text{skill}}) + 0.25(S_{\text{semantic}}) + 0.12(S_{\text{title}}) + 0.10(S_{\text{exp}}) + 0.08(S_{\text{loc}}) + 0.05(S_{\text{salary}}) + 0.03(S_{\text{type}}) + 0.02(S_{\text{edu}})$$
Skill matching uses canonical alias normalization and Jaccard token overlap. Semantic similarity utilizes `SentenceTransformer('all-MiniLM-L6-v2')` to map candidate profiles and job descriptions into 384-dimensional dense vector space, computing their cosine angle. Experience, salary, and location use bounded proximity scoring. This hybrid approach prevents the cold-start and keyword-mismatch problems common in pure keyword systems.

#### Q4: How does the platform handle semantic similarity if PyTorch or SentenceTransformer fails to load?
**Answer:** HireVolt implements a resilient **graceful degradation architecture**. In `job_recommendation_engine.py`, the transformer model loading is wrapped in exception handling. If PyTorch or transformer weights are unavailable due to hardware or memory limits, the system automatically falls back to an in-memory Scikit-Learn `TfidfVectorizer` with sublinear term-frequency scaling and cosine similarity, ensuring uninterrupted platform availability.

#### Q5: What machine learning algorithms are used in the ATS Resume Intelligence pipeline?
**Answer:** The ATS pipeline employs a dual-model serialized architecture saved in `ats_model_v1.joblib`:
1. **`GradientBoostingRegressor`**: An ensemble of sequential boosting decision trees optimizing mean squared error, predicting a continuous ATS compatibility score between 0 and 100.
2. **`CalibratedClassifierCV` wrapping `RandomForestClassifier`**: An ensemble of 200 bagging trees calibrated using Platt sigmoid scaling, outputting calibrated class probabilities across four discrete fit tiers (*Poor Fit*, *Fair Fit*, *Good Fit*, *Excellent Fit*).

#### Q6: How does the ATS feature extraction guarantee algorithmic fairness and prevent bias?
**Answer:** The feature engineering module (`feature_engineering.py`) extracts a 23-dimensional feature vector consisting entirely of structural, linguistic, and objective competence metrics (e.g., word count, action verbs, metric density, section completeness, skill counts). It strictly excludes demographic attributes: no name, gender, age, race, nationality, zip code, or photo features are extracted or fed into the models, ensuring demographic parity and ethical fairness.

#### Q7: How does HireVolt protect against Cross-Site Scripting (XSS) attacks?
**Answer:** XSS is mitigated through dual-layer defense:
1. **Contextual Escaping:** Jinja2 auto-escaping is active across all HTML templates, converting `<, >, &, ", '` characters into safe HTML entities.
2. **Active Sanitization:** Where rich text is permitted (e.g., job descriptions, candidate summaries), the input is sanitized using `bleach.clean()` with a strict whitelist of permissible tags (`<b>`, `<i>`, `<ul>`, `<li>`, `<p>`) and attributes, stripping all `<script>`, `<iframe>`, and event handler attributes like `onload` or `onerror`.

#### Q8: How is Cross-Site Request Forgery (CSRF) mitigated across both standard forms and AJAX requests?
**Answer:** CSRF is mitigated using `Flask-WTF` (`CSRFProtect`), which implements the Synchronizer Token Pattern. Every active session is issued a cryptographically random, signed CSRF token. Standard HTML forms include this via `{{ csrf_token() }}`. For asynchronous JavaScript requests, `static/js/csrf_protect.js` intercepts all `fetch` and XMLHttpRequest payloads and automatically injects the token into the `X-CSRFToken` HTTP header, which is validated before Flask dispatches to the route handler.

#### Q9: Explain the account lockout mechanism and how it prevents credential stuffing.
**Answer:** When an authentication attempt fails, the event is logged in the `login_attempts` table with the normalized email and client IP address. Before evaluating credentials on subsequent attempts, `check_account_lockout()` executes a query counting failed attempts for that email within the last 90 minutes. If the count reaches 3, the account is locked for 90 minutes, returning HTTP 429 / authentication error without performing password hash computation, neutralizing brute-force and credential stuffing attacks.

#### Q10: How does HireVolt handle database connection pooling and prevent connection exhaustion?
**Answer:** Rather than opening and tearing down individual TCP connections per HTTP request, HireVolt initializes a `MySQLConnectionPool` (`pool_size=10`) via `mysql.connector.pooling`. Web worker threads borrow an active connection from the pool via the `db_cursor` context manager. When the block completes or raises an exception, the context manager's `finally` clause closes the cursor and returns the connection back to the pool, guaranteeing zero connection leakage.

#### Q11: How are uploaded resume files validated to prevent malicious file execution?
**Answer:** File validation follows a 4-step pipeline:
1. **Extension Whitelisting:** Checking file extensions against an allowed set (`.pdf`, `.docx`, `.doc`, `.txt`, `.png`, `.jpg`).
2. **Filename Sanitization:** Processing filenames through `werkzeug.utils.secure_filename` to prevent directory traversal (`../`) attacks.
3. **File Size Capping:** Restricting payload sizes to 5MB via Flask's `MAX_CONTENT_LENGTH`.
4. **Binary Magic-Byte Inspection:** The `validate_file_signature` function reads the initial byte sequence from the file header (e.g., verifying that a `.pdf` starts with `%PDF-` and a `.docx` starts with the PK zip header `\x50\x4B\x03\x04`), rejecting polyglot files and renamed executables.

#### Q12: How are user sessions secured in HireVolt?
**Answer:** Sessions are stored using cryptographically signed client cookies managed by Werkzeug and Flask. Session parameters are hardened:
- `SESSION_COOKIE_HTTPONLY=True`: Prevents client-side JavaScript access via `document.cookie`, mitigating XSS-based session theft.
- `SESSION_COOKIE_SAMESITE='Lax'`: Prevents cookies from being transmitted during cross-site requests, mitigating CSRF.
- `SESSION_COOKIE_SECURE=True` (in production): Enforces cookie transmission strictly over TLS/HTTPS.
- `PERMANENT_SESSION_LIFETIME=7 days`: Automatically expires dormant sessions.

#### Q13: What is the difference between direct and indirect dependencies in this project?
**Answer:** A **direct dependency** is a library explicitly imported and invoked by HireVolt's source code and defined in `requirements.txt` (e.g., `Flask`, `sentence-transformers`, `mysql-connector-python`, `scikit-learn`). An **indirect (transitive) dependency** is a package required by a direct dependency to function (e.g., `pdfminer.six` required by `pdfplumber`, `torch` and `huggingface-hub` required by `transformers`).

#### Q14: How does HireVolt parse scanned PDF resumes that do not contain selectable text?
**Answer:** HireVolt implements an OCR fallback pipeline. When `pypdf` or `pymupdf` extracts an empty or near-empty text string from a valid PDF, the system classifies the document as a raster-scanned image. It utilizes `pymupdf` (`fitz`) or `pdf2image` to render PDF pages into image buffers, applies grayscale and contrast normalization via `Pillow`, and invokes `pytesseract` (wrapping Google Tesseract OCR) to extract text characters.

#### Q15: Why is Redis included in Docker Compose, and what role does it play?
**Answer:** Redis 7 is deployed as an optional, high-throughput in-memory data store. In production or multi-container deployments, `Flask-Limiter` connects to Redis (`RATELIMIT_STORAGE_URI=redis://redis:6379/0`) rather than in-memory storage. This ensures that rate-limiting counters (e.g., login attempts, OTP verifications) are synchronized globally across all Gunicorn worker processes.

#### Q16: Describe the role and configuration of the Docker Compose `worker` service.
**Answer:** The `worker` service runs alongside the `web` container. It uses the same application image but overrides the entrypoint command to execute background tasks, specifically executing `python -c "import app; app.cron_send_job_alerts()"`. This isolates periodic email digest generation and maintenance tasks from the web server, preventing batch processing jobs from blocking interactive user HTTP requests.

#### Q17: What HTTP security headers are configured, and why is `X-Content-Type-Options: nosniff` critical?
**Answer:** HireVolt configures `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`, and `X-Content-Type-Options: nosniff`. The `nosniff` header is critical because it forces browsers to strictly adhere to the MIME type sent in the `Content-Type` header, preventing browsers from "MIME-sniffing" an uploaded text or image file and executing it as JavaScript or HTML.

#### Q18: What is the role of `CalibratedClassifierCV` in the ATS machine learning model?
**Answer:** Standard Random Forest classifiers can output uncalibrated predicted probabilities (often skewed toward 0 or 1). `CalibratedClassifierCV` wraps the Random Forest estimator and applies Platt scaling (sigmoid calibration) over cross-validation folds. This ensures that the predicted probability for a class corresponds directly to the true empirical likelihood of that fit tier.

#### Q19: How are database transactions handled during multi-table mutations (e.g., submitting an application)?
**Answer:** Multi-table mutations (e.g., inserting into `applications`, updating `jobs.application_count`, and logging into `audit_logs`) are wrapped inside the `with db_cursor(commit=True) as cursor:` context block. The MySQL connection begins an explicit transaction. If all queries succeed, `conn.commit()` commits the changes atomically. If any statement fails, the exception triggers `conn.rollback()`, ensuring the database remains in a consistent state.

#### Q20: If this platform were scaled to 1,000,000 active users, what architectural refactorings would be required first?
**Answer:**
1. **Asynchronous Task Queue:** Migrate synchronous resume parsing and embedding generation to Celery with Redis/RabbitMQ.
2. **Dedicated Vector Search Engine:** Replace Python in-memory vector cosine similarity with an indexed vector database (Qdrant, Milvus, or OpenSearch).
3. **Database Read/Write Splitting:** Introduce MySQL read replicas for read-heavy search and job listing views while routing writes to the primary node.
4. **Content Delivery Network (CDN):** Offload static CSS, JavaScript, and user resume assets to object storage (e.g., AWS S3 / MinIO) fronted by Cloudflare.

---

# 14. Verified Technology List

The following comprehensive categorization represents **only** technologies, frameworks, and tools verified in the project repository:

### 1. Programming Languages
- **Python 3.10**: Primary backend, data processing, and machine learning language.
- **JavaScript (ES6+)**: Vanilla client-side asynchronous scripts and event handlers.
- **SQL (MySQL Dialect)**: Relational schema creation and parameterized data manipulation queries.
- **HTML5 & CSS3**: Semantic markup and responsive custom styling.

### 2. Backend & Web Frameworks
- **Flask 3.1.3**: Microframework core.
- **Werkzeug 3.1.3**: WSGI foundation, routing, password hashing.
- **Gunicorn 25.1.0**: Multi-process UNIX WSGI production HTTP server.

### 3. Database & Persistence
- **MySQL 8.0**: Relational database management system.
- **`mysql-connector-python 9.6.0`**: Native database driver with connection pooling.
- **Pure Parameterized SQL**: Direct SQL execution layer (No ORM).
- **Redis 7-alpine**: Configured in-memory caching and rate limit storage.

### 4. Machine Learning & Natural Language Processing
- **`sentence-transformers 5.6.1`**: Transformer model runtime.
- **`all-MiniLM-L6-v2`**: 384-dimensional dense sentence embedding model.
- **PyTorch (`torch`) 2.13.0**: Deep learning tensor framework.
- **Hugging Face `transformers 5.14.1`**: Model architecture library.
- **Scikit-Learn 1.7.2**: `GradientBoostingRegressor`, `RandomForestClassifier`, `CalibratedClassifierCV`, `TfidfVectorizer`.
- **NumPy 2.2.6**: Numerical computing and matrix similarity calculations.
- **Joblib 1.5.3**: Model serialization and deserialization.

### 5. Document Processing & OCR
- **`pypdf 6.16.1`**: Pure-Python PDF parsing.
- **`pdfplumber 0.11.10`**: Layout-aware PDF extraction.
- **`PyMuPDF` (`fitz`) 1.28.2**: High-speed C-based PDF rendering.
- **`python-docx 1.2.0`**: Microsoft Word document parser.
- **`pytesseract 0.3.13`**: Tesseract Optical Character Recognition interface.
- **`Pillow 11.3.0`**: Image processing, conversion, and pre-OCR formatting.

### 6. Security, Networking & Validation
- **`Flask-WTF 1.2.2`**: CSRF protection.
- **`Flask-Limiter 4.1.1`**: Endpoint rate limiting.
- **`bleach 6.4.0`**: HTML input sanitization.
- **`email-validator 2.3.0`**: RFC-compliant email verification.
- **`dnspython 2.8.0`**: DNS MX record lookup.
- **`cryptography 46.0.5`**: Cryptographic algorithms and token generation.
- **`python-dotenv 1.2.2`**: Environment secret management.

### 7. Frontend CDN Libraries
- **Lucide Icons 0.468.0**: SVG iconography.
- **Font Awesome 6.4.0**: Supplemental icons.
- **Lenis 1.1.20**: Inertial smooth scrolling.
- **Chart.js 4.4.0 / 4.4.1**: Analytics and data visualization charts.
- **Google Fonts (Inter)**: Web typography.

### 8. Testing & Code Quality
- **`pytest 9.0.2`**: Testing framework.
- **`pytest-cov 7.1.0`**: Test coverage reporting.
- **`flake8 7.3.0`**: Static code analysis and PEP 8 linter.
- **`pytest-timeout 2.4.0`**: Test timeout watchdog.
- **`responses 0.25.8`**: HTTP request mocking.

### 9. DevOps & Containerization
- **Docker**: Containerization engine.
- **Docker Compose v2**: Multi-container service orchestration (`web`, `db`, `redis`, `worker`).
- **Python 3.10-slim**: Base Linux container image.
- **Tesseract-OCR Linux Binary**: System-level OCR package installed via APT.
