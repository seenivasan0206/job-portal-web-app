# -*- coding: utf-8 -*-
"""
Tests for email diagnostic tool and startup SMTP checks:
- Verifies check_smtp_at_startup() behavior (testing bypass, failure warning logging, success logging)
- Verifies scripts/test_email.py module structure and diagnostic logic
"""
import os
import smtplib
import logging
from unittest.mock import patch, MagicMock
import pytest
from app import app, check_smtp_at_startup
import scripts.test_email as test_email_module


def test_check_smtp_at_startup_skips_when_testing():
    """Verify check_smtp_at_startup skips network I/O when app is in testing mode."""
    with patch.dict(os.environ, {'SKIP_EMAIL_STARTUP_CHECK': '1'}):
        assert check_smtp_at_startup() is True


def test_check_smtp_at_startup_logs_warning_on_failure(caplog):
    """Verify check_smtp_at_startup logs clear one-line warning on SMTP failure."""
    with caplog.at_level(logging.WARNING):
        with patch.dict(os.environ, {'SKIP_EMAIL_STARTUP_CHECK': '0'}):
            with patch.dict(app.config, {'TESTING': False}):
                with patch('smtplib.SMTP') as mock_smtp, patch('smtplib.SMTP_SSL') as mock_ssl:
                    mock_smtp.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
                    mock_ssl.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
                    result = check_smtp_at_startup()
                    assert result is False
                    assert any("OTP EMAIL SENDING IS NOT WORKING" in record.message for record in caplog.records)


def test_check_smtp_at_startup_logs_success_when_working(caplog):
    """Verify check_smtp_at_startup logs info on success."""
    with caplog.at_level(logging.INFO):
        with patch.dict(os.environ, {'SKIP_EMAIL_STARTUP_CHECK': '0'}):
            with patch.dict(app.config, {'TESTING': False}):
                with patch('smtplib.SMTP') as mock_smtp:
                    mock_server = MagicMock()
                    mock_smtp.return_value.__enter__.return_value = mock_server
                    result = check_smtp_at_startup()
                    assert result is True
                    assert any("SMTP service verified OK" in record.message for record in caplog.records)


def test_email_diagnostic_script_functions():
    """Verify scripts/test_email.py module functions."""
    assert hasattr(test_email_module, 'check_port_connectivity')
    assert hasattr(test_email_module, 'test_smtp_send')

    # Mock success run of test_smtp_send
    with patch('smtplib.SMTP') as mock_smtp, patch('socket.socket') as mock_sock:
        mock_sock_instance = MagicMock()
        mock_sock.return_value = mock_sock_instance
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        res = test_email_module.test_smtp_send()
        assert res is True
