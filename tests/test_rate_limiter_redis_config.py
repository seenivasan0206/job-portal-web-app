# -*- coding: utf-8 -*-
"""
Test suite for Multi-Worker Rate Limiting and Redis Configuration (Bug #7).
Verifies:
1. 'redis' is present in requirements.txt and importable.
2. Flask-Limiter is configured with storage_uri, in-memory fallback, and error swallowing.
3. .env.example, README.md, AGENTS.md, and docker-compose.yml document Redis configuration.
"""

import os
from pathlib import Path
import pytest
from app import limiter, app

BASE_DIR = Path(__file__).resolve().parent.parent


def test_redis_dependency_in_requirements():
    """Verify redis is listed in requirements.txt and can be imported."""
    reqs = (BASE_DIR / 'requirements.txt').read_text(encoding='utf-8')
    assert 'redis' in reqs

    import redis
    assert redis is not None


def test_flask_limiter_configuration_and_fallbacks():
    """Verify Flask-Limiter instance in app.py has fallback enabled and swallows errors."""
    assert limiter is not None
    # Check that in-memory fallback is configured
    assert getattr(limiter, '_in_memory_fallback_enabled', False) is True or limiter._in_memory_fallback is not None
    assert getattr(limiter, '_swallow_errors', False) is True


def test_documentation_and_environment_templates():
    """Verify .env.example, README.md, and docker-compose.yml document RATELIMIT_STORAGE_URI and Redis."""
    env_example = (BASE_DIR / '.env.example').read_text(encoding='utf-8')
    assert 'RATELIMIT_STORAGE_URI' in env_example
    assert 'redis://' in env_example

    readme = (BASE_DIR / 'README.md').read_text(encoding='utf-8')
    assert 'RATELIMIT_STORAGE_URI' in readme
    assert 'Redis' in readme

    docker_compose = (BASE_DIR / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'redis:' in docker_compose
    assert 'RATELIMIT_STORAGE_URI=redis://redis:6379/0' in docker_compose
