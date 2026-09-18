import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def test_faq_accordion_markup_and_semantics():
    """Verify FAQ questions are accessible semantic buttons with accordion collapse wrappers."""
    index_html = (BASE_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    expected_questions = [
        "How is HireVoltz different from other platforms like Naukri or LinkedIn?",
        "Is HireVoltz free for job seekers?",
        "Where do HireVoltz job postings come from?",
        "How does CV match scoring help me get shortlisted?"
    ]

    for q in expected_questions:
        assert q in index_html, f"FAQ question missing: {q}"

    # Verify button markup with aria-expanded and toggleFaq(this)
    button_matches = re.findall(
        r'<button\s+type="button"\s+class="faq-question"\s+onclick="toggleFaq\(this\)"\s+aria-expanded="false">',
        index_html
    )
    assert len(button_matches) >= 4, f"Expected at least 4 FAQ question buttons, found {len(button_matches)}"

    # Verify collapse container wrapper
    assert '<div class="faq-answer-collapse">' in index_html
    assert '<div class="faq-answer">' in index_html
    assert 'faq-chevron' in index_html


def test_faq_css_grid_animation():
    """Verify modern CSS Grid row transition is implemented for smooth accordion expansion."""
    index_html = (BASE_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    assert '.faq-answer-collapse' in index_html
    assert 'grid-template-rows: 0fr;' in index_html
    assert '.faq-item.active .faq-answer-collapse' in index_html
    assert 'grid-template-rows: 1fr;' in index_html
    assert 'min-height: 0;' in index_html
    assert 'overflow: hidden;' in index_html
    assert 'transform: rotate(180deg);' in index_html


def test_faq_toggle_js_logic():
    """Verify toggleFaq handles accordion closing, active state toggle, and aria-expanded."""
    index_html = (BASE_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    assert 'function toggleFaq(' in index_html
    assert 'window.toggleFaq = toggleFaq;' in index_html
    assert "document.querySelectorAll('.faq-item.active').forEach" in index_html
    assert "otherBtn.setAttribute('aria-expanded', 'false')" in index_html
    assert "btn.setAttribute('aria-expanded', 'true')" in index_html
    assert "item.classList.add('active')" in index_html
    assert "item.classList.remove('active')" in index_html


def test_category_dropdown_accessibility_and_keyboard():
    """Verify category dropdown button, menu, options, and keyboard event handling."""
    index_html = (BASE_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')

    assert 'id="category-dropdown-btn"' in index_html
    assert 'aria-haspopup="listbox"' in index_html
    assert 'aria-expanded=' in index_html
    assert 'id="category-dropdown-menu"' in index_html
    assert 'role="listbox"' in index_html
    assert 'tabindex="0"' in index_html

    # Keyboard navigation logic
    assert "document.addEventListener('keydown'" in index_html
    assert "'ArrowDown'" in index_html
    assert "'ArrowUp'" in index_html
    assert "'Escape'" in index_html


def test_jobs_filter_dropdowns_instant_reactivity():
    """Verify jobs.html has onchange=applyFilters() on all filter dropdowns and complete categories."""
    jobs_html = (BASE_DIR / 'templates' / 'jobs.html').read_text(encoding='utf-8')

    assert '<select id="filter-category" class="form-select" onchange="applyFilters()">' in jobs_html
    assert '<select id="filter-exp" class="form-select" onchange="applyFilters()">' in jobs_html
    assert '<select id="filter-job-type" class="form-select" onchange="applyFilters()">' in jobs_html
    assert '<select id="filter-work-mode" class="form-select" onchange="applyFilters()">' in jobs_html
    assert '<select id="sort-order" class="form-select"' in jobs_html
    assert 'onchange="applyFilters()"' in jobs_html

    # Verify canonical categories are present
    canonical_categories = [
        "IT & Software", "Banking & Finance", "Healthcare", "Engineering",
        "Manufacturing", "Marketing", "Education", "Design Engineer", "Retail"
    ]
    for cat in canonical_categories:
        assert f'value="{cat}"' in jobs_html, f"Missing category {cat} in jobs.html"


def test_companies_filter_dropdowns_and_size_filtering():
    """Verify companies.html filters on change and active size filtering logic."""
    companies_html = (BASE_DIR / 'templates' / 'companies.html').read_text(encoding='utf-8')

    assert '<select id="filter-industry" class="form-select" onchange="applyCompanyFilters()">' in companies_html
    assert '<select id="filter-size" class="form-select" onchange="applyCompanyFilters()">' in companies_html
    assert '<select id="filter-location" class="form-select" onchange="applyCompanyFilters()">' in companies_html

    # Size filtering in applyCompanyFilters JS
    assert "document.getElementById('filter-size').value" in companies_html
    assert "matchSize" in companies_html


def test_recruiter_candidate_filter_reactivity():
    """Verify recruiter_candidates.html filters update dynamically on selection."""
    rec_html = (BASE_DIR / 'templates' / 'recruiter_candidates.html').read_text(encoding='utf-8')

    assert '<select id="filter-skills" class="form-select" onchange="searchCandidates()">' in rec_html
    assert '<select id="filter-exp" class="form-select" onchange="searchCandidates()">' in rec_html
    assert '<select id="filter-location" class="form-select" onchange="searchCandidates()">' in rec_html


def test_assessment_filters_and_sort_reset():
    """Verify candidate_assessments.html filters and resetAllFilters restores sorting."""
    ass_html = (BASE_DIR / 'templates' / 'candidate_assessments.html').read_text(encoding='utf-8')

    assert 'id="filter-difficulty"' in ass_html
    assert 'onchange="filterAssessments()"' in ass_html
    assert 'id="filter-status"' in ass_html
    assert 'id="filter-sort"' in ass_html
    assert 'onchange="sortAssessments()"' in ass_html

    # resetAllFilters must invoke sortAssessments()
    reset_fn_match = re.search(r'function resetAllFilters\(\)\s*\{([^}]+)\}', ass_html)
    assert reset_fn_match, "resetAllFilters function missing"
    assert "sortAssessments()" in reset_fn_match.group(1)


def test_mobile_drawer_class_consistency():
    """Verify mobile navigation drawer classes are synced between CSS and JS."""
    app_css = (BASE_DIR / 'static' / 'css' / 'app.css').read_text(encoding='utf-8')
    main_js = (BASE_DIR / 'static' / 'js' / 'main.js').read_text(encoding='utf-8')

    assert '.mobile-drawer.active' in app_css
    assert '.mobile-drawer.open' in app_css
    assert '.mobile-drawer-backdrop.active' in app_css
    assert '.mobile-drawer-backdrop.open' in app_css

    assert "drawer.classList.remove('active')" in main_js
    assert "drawer.classList.remove('open')" in main_js
    assert "drawer.classList.add('active')" in main_js
    assert "drawer.classList.add('open')" in main_js


def test_employer_dashboard_job_category_options():
    """Verify employer dashboard post job modal contains canonical database categories."""
    emp_html = (BASE_DIR / 'templates' / 'employer_dashboard.html').read_text(encoding='utf-8')

    canonical_categories = [
        "IT & Software", "Banking & Finance", "Healthcare", "Engineering",
        "Manufacturing", "Marketing", "Education", "Design Engineer", "Retail"
    ]
    for cat in canonical_categories:
        assert f'value="{cat}"' in emp_html, f"Missing category {cat} in employer_dashboard.html"
