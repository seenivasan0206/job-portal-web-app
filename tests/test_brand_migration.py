# -*- coding: utf-8 -*-
import re
from pathlib import Path
import pytest

from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

BASE_DIR = Path(__file__).resolve().parent.parent

def test_hirevolt_logo_exists():
    large_logo = BASE_DIR / 'static' / 'images' / 'HireVolt_logo.png'
    assert large_logo.exists(), f"Logo file missing at {large_logo}"
    assert large_logo.stat().st_size > 0, "Logo file is empty"

def test_base_template_branding():
    base_html = (BASE_DIR / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert "HireVolt" in base_html
    assert "HireVolt_logo.png" in base_html
    assert "2026 HireVolt Inc. All rights reserved." in base_html
    assert "NexRole" not in base_html
    assert "DreamJobs" not in base_html
    assert "Dream Jobs" not in base_html

def test_index_template_branding(client):
    index_html = (BASE_DIR / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert "HireVolt — Career Platform Built for Job Seekers" in index_html
    assert "HireVolt uses AI to surface low-competition" in index_html
    assert "NexRole" not in index_html
    assert "DreamJobs" not in index_html
    assert "Dream Jobs" not in index_html

    # Rendered index includes header and footer branding inherited from base.html
    res = client.get('/')
    assert res.status_code == 200
    rendered = res.get_data(as_text=True)
    assert "HireVolt_logo.png" in rendered
    assert "2026 HireVolt Inc. All rights reserved." in rendered
    assert "NexRole" not in rendered
    assert "DreamJobs" not in rendered
    assert "Dream Jobs" not in rendered

def test_all_templates_free_of_old_branding():
    templates_dir = BASE_DIR / 'templates'
    old_brand_re = re.compile(r'dream[\s_-]?job', re.IGNORECASE)
    violations = []
    for t in templates_dir.glob('*.html'):
        content = t.read_text(encoding='utf-8')
        for i, line in enumerate(content.splitlines()):
            if old_brand_re.search(line):
                violations.append(f"{t.name}:L{i+1}: {line.strip()}")
    assert not violations, "Found old brand references in templates:\n" + "\n".join(violations)

def test_app_email_and_system_notifications():
    app_py = (BASE_DIR / 'app.py').read_text(encoding='utf-8')
    assert "Your Verification Code - HireVolt" in app_py
    assert "HireVolt Team" in app_py
    assert "HireVolt Talent Operations" in app_py
    assert "HireVolt Verified Partner" in app_py
    assert "HireVolt Interview Dashboard" in app_py
    assert "PRODID:-//HireVolt//Interview Coordination System//EN" in app_py
    assert "@hirevolt.internal" in app_py
    assert "Approved by HireVolt trust team." in app_py
