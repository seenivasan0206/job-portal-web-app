# -*- coding: utf-8 -*-
"""
Diagnostic script to test SMTP email delivery configuration.
Loads EMAIL_ADDRESS and EMAIL_PASSWORD from .env and attempts to send a test email.

Usage:
    python scripts/test_email.py [recipient@example.com]
"""
import os
import sys
import socket
import smtplib
import traceback
from email.message import EmailMessage
from dotenv import load_dotenv

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Load .env
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
if EMAIL_PASSWORD:
    EMAIL_PASSWORD = EMAIL_PASSWORD.replace(' ', '')

SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT_STARTTLS = int(os.getenv('SMTP_PORT_STARTTLS', '587'))
SMTP_PORT_SSL = int(os.getenv('SMTP_PORT_SSL', '465'))
SMTP_TIMEOUT = int(os.getenv('SMTP_TIMEOUT', '10'))

recipient = sys.argv[1] if len(sys.argv) > 1 else EMAIL_ADDRESS


def check_port_connectivity(host, port, timeout=5):
    """Test raw TCP socket connection to the SMTP server."""
    print(f"  [+] Testing raw TCP socket to {host}:{port} (timeout={timeout}s)...", end=" ", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.close()
        print("CONNECTED (Port is open and reachable)")
        return True, None
    except Exception as e:
        print(f"FAILED ({e.__class__.__name__}: {e})")
        return False, e


def test_smtp_send():
    print("=" * 70)
    print("HireVoltz SMTP Diagnostic Tool")
    print("=" * 70)
    print(f"SMTP Host:         {SMTP_HOST}")
    print(f"STARTTLS Port:     {SMTP_PORT_STARTTLS}")
    print(f"SSL Port:          {SMTP_PORT_SSL}")
    print(f"Timeout:           {SMTP_TIMEOUT}s")
    print(f"Sender Email:      {EMAIL_ADDRESS or '[NOT SET]'}")
    masked_pw = (EMAIL_PASSWORD[:3] + '***' + EMAIL_PASSWORD[-2:]) if len(EMAIL_PASSWORD) >= 5 else '[NOT SET]'
    print(f"Password:          {masked_pw} ({len(EMAIL_PASSWORD)} chars)")
    print(f"Recipient:         {recipient}")
    print("=" * 70)

    if not EMAIL_ADDRESS:
        print("\n[ERROR] EMAIL_ADDRESS is not set in .env!")
        return False
    if not EMAIL_PASSWORD:
        print("\n[ERROR] EMAIL_PASSWORD is not set in .env!")
        return False

    msg = EmailMessage()
    msg.set_content(
        f"This is a diagnostic test email from HireVoltz Job Portal.\n\n"
        f"Timestamp: {os.times()}\n"
        f"Sender: {EMAIL_ADDRESS}\n\n"
        f"If you received this, your email configuration is working correctly."
    )
    msg['Subject'] = "HireVoltz SMTP Diagnostic Test"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = recipient

    ports_to_test = [
        (SMTP_PORT_STARTTLS, False, "STARTTLS"),
        (SMTP_PORT_SSL, True, "SSL"),
    ]

    success = False
    results = {}

    for port, use_ssl, mode in ports_to_test:
        print(f"\n---> Testing Port {port} ({mode}) <---")
        tcp_ok, tcp_err = check_port_connectivity(SMTP_HOST, port, timeout=SMTP_TIMEOUT)
        if not tcp_ok:
            print(f"  [-] Socket connection to {SMTP_HOST}:{port} failed.")
            print(f"      Root Cause: Outbound port {port} may be blocked by your network/firewall/ISP.")
            results[port] = ("CONNECTION_FAILED", tcp_err)
            continue

        try:
            if use_ssl:
                print(f"  [+] Connecting via SMTP_SSL({SMTP_HOST}, {port})...", flush=True)
                with smtplib.SMTP_SSL(SMTP_HOST, port, timeout=SMTP_TIMEOUT) as smtp:
                    print(f"  [+] Authenticating as '{EMAIL_ADDRESS}'...", flush=True)
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    print(f"  [+] Sending test email to '{recipient}'...", flush=True)
                    smtp.send_message(msg)
            else:
                print(f"  [+] Connecting via SMTP({SMTP_HOST}, {port})...", flush=True)
                with smtplib.SMTP(SMTP_HOST, port, timeout=SMTP_TIMEOUT) as smtp:
                    print(f"  [+] Sending EHLO...", flush=True)
                    smtp.ehlo()
                    print(f"  [+] Starting TLS...", flush=True)
                    smtp.starttls()
                    print(f"  [+] Sending EHLO after STARTTLS...", flush=True)
                    smtp.ehlo()
                    print(f"  [+] Authenticating as '{EMAIL_ADDRESS}'...", flush=True)
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    print(f"  [+] Sending test email to '{recipient}'...", flush=True)
                    smtp.send_message(msg)

            print(f"  [SUCCESS] Test email successfully delivered on port {port} ({mode})!")
            results[port] = ("SUCCESS", None)
            success = True
            break
        except smtplib.SMTPAuthenticationError as e:
            print(f"  [FAILED] SMTP Authentication Error: {e}")
            print(f"  SMTP Code: {e.smtp_code}")
            print(f"  SMTP Error: {e.smtp_error}")
            traceback.print_exc()
            results[port] = ("AUTH_ERROR", e)
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, socket.timeout) as e:
            print(f"  [FAILED] SMTP Connection/Timeout Error: {e}")
            traceback.print_exc()
            results[port] = ("CONNECTION_ERROR", e)
        except Exception as e:
            print(f"  [FAILED] Unexpected Error ({e.__class__.__name__}): {e}")
            traceback.print_exc()
            results[port] = ("UNEXPECTED_ERROR", e)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
    print("=" * 70)

    if success:
        print("[STATUS: OK] SMTP email sending is working properly!")
        return True
    else:
        print("[STATUS: FAILED] All SMTP ports failed to send.")
        has_auth_err = any(status == "AUTH_ERROR" for status, _ in results.values())
        has_conn_err = any(status in ("CONNECTION_FAILED", "CONNECTION_ERROR") for status, _ in results.values())

        if has_auth_err:
            print("\n* DIAGNOSIS: Authentication Failure (Gmail App Password Rejected)")
            print("  Reason: The password in .env is not recognized by Google.")
            print("  How to Fix:")
            print("  1. Go to https://myaccount.google.com/security")
            print("  2. Ensure 2-Step Verification is ON.")
            print("  3. Search for 'App passwords'.")
            print("  4. Generate a new App Password named 'HireVoltz'.")
            print("  5. Copy the 16-character code into EMAIL_PASSWORD in .env (without spaces).")
        elif has_conn_err:
            print("\n* DIAGNOSIS: Outbound SMTP Ports Blocked / Network Timeout")
            print("  Reason: Your hosting provider or local network blocks outbound ports 587/465.")
            print("  How to Fix:")
            print("  1. Check firewall / cloud security group rules for outbound ports 587 and 465.")
            print("  2. Or switch to an HTTP-based transactional email service (e.g., SendGrid, Resend,")
            print("     Mailgun, AWS SES) which operates over standard HTTPS (port 443).")

        return False


if __name__ == '__main__':
    ok = test_smtp_send()
    sys.exit(0 if ok else 1)
