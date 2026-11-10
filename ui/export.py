"""Download helpers that keep exported CSV safe to open in a spreadsheet."""

from __future__ import annotations

import csv
import io

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_cell(value: str) -> str:
    """Prefix a quote when a cell could be run as a spreadsheet formula."""
    return "'" + value if value.lstrip().startswith(DANGEROUS_PREFIXES) else value


def safe_csv(text: str) -> str:
    """Return CSV text with formula-like cells neutralised (header kept)."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for number, row in enumerate(csv.reader(io.StringIO(text))):
        writer.writerow(row if number == 0 else [neutralize_cell(c) for c in row])
    return output.getvalue()
