# -*- coding: utf-8 -*-
"""
Test suite for Git Security Hygiene and .gitignore Protection (Bug #8).
Verifies:
1. .gitignore exists at the project root.
2. .env is explicitly ignored.
3. Sensitive directories (cache, uploads, instance) are ignored.
"""

from pathlib import Path
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent


def test_gitignore_exists_and_protects_env():
    """Verify that .gitignore exists and includes .env, __pycache__, and upload directories."""
    gitignore_path = BASE_DIR / '.gitignore'
    assert gitignore_path.exists(), ".gitignore file missing at project root"

    content = gitignore_path.read_text(encoding='utf-8')
    assert '.env' in content, ".env not listed in .gitignore"
    assert '__pycache__/' in content or '__pycache__' in content, "__pycache__ not listed in .gitignore"
    assert '*.pyc' in content or '*.py[cod]' in content, "python bytecode not listed in .gitignore"
    assert 'static/uploads/' in content or 'uploads/' in content, "uploads directory not ignored"
    assert 'instance/' in content, "instance/ directory not ignored"
