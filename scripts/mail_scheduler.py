#!/usr/bin/env python3
"""Casos daily deadline notifications for active Issues (local calendar date)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.database import init_db
from dashboard.mail_service import notify_due_issues


def main():
    init_db()
    counts = notify_due_issues()
    print(f"Issue-Mails: {counts['deadline_reached']} Fälligkeiten, {counts['deadline_warning']} Vorwarnungen.")


if __name__ == '__main__':
    main()
