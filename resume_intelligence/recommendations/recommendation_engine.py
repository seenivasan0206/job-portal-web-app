# -*- coding: utf-8 -*-

def detect_issues_and_recommendations(resume_text, sections, contacts, skills, entities, date_info, extraction_report, jd_match=None):
    """
    Evidence-based issue detection: Problem -> Evidence -> Impact -> Solution.
    """
    issues = []
    
    # 1. Missing Required JD Skills
    if jd_match and jd_match.get('missing_required'):
        missing_req = jd_match['missing_required']
        sample_req = ', '.join(missing_req[:3])
        issues.append({
            'category': 'Required Skill Verification',
            'severity': 'Critical',
            'problem': f"Missing {len(missing_req)} required job skills: {sample_req}.",
            'evidence': f"Target job description explicitly requires {sample_req}, which were not detected in your resume.",
            'why_it_matters': "ATS filters prioritize candidate ranking by required skill match. Missing required skills lowers ATS ranking regardless of formatting.",
            'recommendation': f"If you have experience with {sample_req}, add them into your Technical Skills and describe relevant projects in your experience section.",
            'before_example': "Worked on backend development and databases.",
            'after_example': f"Engineered scalable data services leveraging {sample_req} in production environments."
        })

    # 2. Few Quantified Achievements (Evidence Check)
    metrics_cnt = entities.get('metrics_count', 0)
    total_bullets = entities.get('total_bullets', 0)
    if metrics_cnt < 3:
        issues.append({
            'category': 'Impact & Metrics',
            'severity': 'Critical' if metrics_cnt == 0 else 'Important',
            'problem': "Experience bullet points lack quantifiable proof of impact.",
            'evidence': f"Only {metrics_cnt} measurable outcome metrics were identified across {total_bullets} experience bullet points.",
            'why_it_matters': "Top tier recruiters and hiring managers look for numbers, percentages, latency improvements, and revenue saved to substantiate claims.",
            'recommendation': "Quantify achievements with percentages, latency reductions, users served, or hours saved.",
            'before_example': "Created a Power BI sales dashboard for the marketing team.",
            'after_example': "Developed an interactive Power BI sales dashboard analyzing [50,000+] records, reducing monthly reporting turnaround by [35%]."
        })

    # 3. Action Verbs vs. Passive Descriptions
    verbs_cnt = len(entities.get('action_verbs', []))
    if verbs_cnt < 5:
        issues.append({
            'category': 'Action Verbs & Ownership',
            'severity': 'Important',
            'problem': "Bullet points rely on passive phrases like 'Responsible for' or 'Assisted with'.",
            'evidence': f"Only {verbs_cnt} dynamic action verbs were found in your experience descriptions.",
            'why_it_matters': "Starting bullets with strong verbs demonstrates technical leadership and active ownership.",
            'recommendation': "Start each bullet point with high-impact verbs such as 'Architected', 'Spearheaded', 'Optimized', or 'Automated'.",
            'before_example': "Responsible for handling authentication bugs and user sessions.",
            'after_example': "Engineered a secure JWT session authentication protocol, cutting login latency by [40%]."
        })

    # 4. Extraction Quality & Formatting Risk
    if extraction_report.get('quality_score', 100) < 75:
        issues.append({
            'category': 'ATS Machine Readability',
            'severity': 'Critical',
            'problem': "Document text layer contains formatting or reading-order artifacts.",
            'evidence': f"Extraction Quality Score is {extraction_report['quality_score']}% ({', '.join(extraction_report.get('issues', ['Low density']))}).",
            'why_it_matters': "Older ATS parsers may misread multi-column text, drop text boxes, or fail on non-standard font encoding.",
            'recommendation': "Export your resume directly from Word or Google Docs using a clean, single-column or standard two-column layout.",
            'before_example': "[Complex multi-layered nested tables and text boxes]",
            'after_example': "[Clean single-column standard PDF layout with distinct semantic headings]"
        })

    # 5. Missing Core Sections
    if not sections.get('summary'):
        issues.append({
            'category': 'Section Completeness',
            'severity': 'Important',
            'problem': "No Professional Summary section detected at the top of the resume.",
            'evidence': "Standard 'Professional Summary' or 'Profile' section heading was not detected.",
            'why_it_matters': "A concise summary provides recruiters with an immediate 5-second snapshot of your seniority and primary tech stack.",
            'recommendation': "Add a 2-3 line summary highlighting your total experience, core technologies, and domain focus.",
            'before_example': "[No summary present at top of page]",
            'after_example': "Results-driven Software Engineer with [4+] years of experience building scalable distributed systems using Python and React."
        })

    if not sections.get('education'):
        issues.append({
            'category': 'Section Completeness',
            'severity': 'Critical',
            'problem': "Education section not detected in resume structure.",
            'evidence': "Standard 'Education' or 'Academic Qualifications' heading was not identified.",
            'why_it_matters': "Many enterprise ATS systems require an explicit Education section to verify degree credentials.",
            'recommendation': "Add a dedicated 'Education' section listing your degree, major, university, and graduation year.",
            'before_example': "[Missing Education section]",
            'after_example': "B.Tech in Computer Science | [University Name] (2018 - 2022)"
        })

    if not sections.get('projects') and not sections.get('certifications'):
        issues.append({
            'category': 'Section Completeness',
            'severity': 'Optional',
            'problem': "No Projects or Certifications sections found to validate practical skill application.",
            'evidence': "Neither 'Projects' nor 'Certifications' headings were detected.",
            'why_it_matters': "Side projects and professional certifications provide concrete evidence of hands-on skills.",
            'recommendation': "Add 1-2 notable technical projects or industry certifications (e.g. AWS Certified Developer).",
            'before_example': "[No projects or certifications listed]",
            'after_example': "Projects: High-Concurrency E-Commerce API (Python, FastAPI, Redis, Docker) — github.com/[username]/project"
        })

    # 6. Date Consistency Issue
    if date_info and not date_info.get('consistent_format', True):
        issues.append({
            'category': 'Timeline Consistency',
            'severity': 'Important',
            'problem': "Inconsistent date formatting detected across employment history.",
            'evidence': "Mixed date styles detected (e.g. '06/2021' mixed with 'June 2021').",
            'why_it_matters': "ATS parsers may miscalculate total years of experience when dates use inconsistent formatting styles.",
            'recommendation': "Standardize all dates to a single consistent format such as 'Jan 2021 – Present' or 'MM/YYYY – MM/YYYY'.",
            'before_example': "Company A: 05/2019 - 2021 | Company B: June 2021 - Present",
            'after_example': "Company A: May 2019 – Jun 2021 | Company B: Jun 2021 – Present"
        })

    # 7. Contact Completeness
    if not contacts.get('linkedin'):
        issues.append({
            'category': 'Contact Verification',
            'severity': 'Optional',
            'problem': "No customized LinkedIn profile link detected in contact header.",
            'evidence': "LinkedIn URL not found in header contact block.",
            'why_it_matters': "Recruiters frequently cross-reference resumes with verified professional LinkedIn profiles.",
            'recommendation': "Add your customized LinkedIn URL (e.g. linkedin.com/in/yourname) in the top contact section.",
            'before_example': "Email: alex@example.com | Phone: +1 555-0199",
            'after_example': "Email: alex@example.com | Phone: +1 555-0199 | LinkedIn: linkedin.com/in/alex"
        })

    return issues

def generate_ai_section_enhancements(skills, entities, name):
    """Generate tailored AI section improvements with explicit placeholders."""
    skill_names = [s['skill'] for s in skills]
    sample_skills = ', '.join(skill_names[:5]) if skill_names else 'Python, SQL, React, AWS'
    primary_role = skill_names[0] + ' Engineer' if skill_names else 'Software Engineer'

    improved_summary = (
        f"Results-oriented {primary_role} with expertise across {sample_skills}. "
        f"Proven track record of architecting, deploying, and maintaining high-performance software systems and scalable architectures. "
        f"Adept at agile delivery, cross-functional technical leadership, and driving measurable business efficiency."
    )

    sample_bullets = entities.get('sample_bullets', [])
    improved_bullets = []
    if sample_bullets:
        for b in sample_bullets[:3]:
            improved_bullets.append({
                'original': b,
                'improved': f"Spearheaded {b.lower().rstrip('.')} by developing automated workflows, achieving a [30%+] improvement in pipeline throughput."
            })
    else:
        improved_bullets.append({
            'original': 'Worked on backend APIs and application features.',
            'improved': 'Engineered scalable RESTful APIs using Python and Docker, boosting server response times by [45%] for [50,000+] daily users.'
        })

    return {
        'improved_summary': improved_summary,
        'improved_bullets': improved_bullets
    }

def generate_action_plan(issues, jd_match=None):
    """Generate a numbered step-by-step improvement checklist."""
    plan_steps = []
    if jd_match and jd_match.get('missing_required'):
        sample = ', '.join(jd_match['missing_required'][:3])
        plan_steps.append(f"Incorporate verified experience in required skills ({sample}) into your skills and project bullets.")

    for issue in issues[:5]:
        rec = issue.get('recommendation')
        if rec and rec not in plan_steps:
            plan_steps.append(rec)

    if len(plan_steps) < 4:
        plan_steps.append("Ensure all employment dates follow consistent 'MMM YYYY – MMM YYYY' format.")
        plan_steps.append("Review experience descriptions to ensure every bullet starts with an action verb.")
        plan_steps.append("Export directly to standard PDF to ensure 100% machine readability.")

    return plan_steps[:6]
