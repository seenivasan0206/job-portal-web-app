"""
Template Asset Verification Utility

Scans all Jinja2 HTML templates in the templates/ directory to verify
that all referenced static assets (CSS, JS, images) exist on disk.
"""

import os
import re
import sys


def verify_template_assets(template_dir='templates', static_dir='static'):
    """Check static references in templates and report missing files."""
    if not os.path.exists(template_dir):
        print(f"Template directory '{template_dir}' not found.")
        return False

    missing_count = 0
    total_refs = 0

    print(f"Scanning templates in '{template_dir}' for static references in '{static_dir}'...\n")

    for filename in sorted(os.listdir(template_dir)):
        if not filename.endswith('.html'):
            continue
        path = os.path.join(template_dir, filename)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        pattern = r'url_for\([\'\"](?:static)[\'\"]\s*,\s*filename=[\'\"]([^\'\"]+)[\'\"]'
        matches = re.findall(pattern, content)
        if matches:
            print(f"=== {filename} ===")
            for m in matches:
                total_refs += 1
                full_path = os.path.join(static_dir, m)
                exists = os.path.exists(full_path)
                if not exists:
                    missing_count += 1
                    status = "MISSING"
                else:
                    status = "OK"
                print(f"  [{status}] {m} -> {full_path}")
        else:
            print(f"=== {filename} === (no static refs)")

    print(f"\nVerification complete: {total_refs} static references checked, {missing_count} missing.")
    return missing_count == 0


if __name__ == '__main__':
    success = verify_template_assets()
    sys.exit(0 if success else 1)
