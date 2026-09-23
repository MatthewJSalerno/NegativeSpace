#!/usr/bin/env python3
"""Verify spec cross-references resolve, code fences balance, and no blank line
splits a markdown table.

Kept in the repo rather than /tmp, which has been cleared twice mid-task.
Exits non-zero on any failure, so it can gate a commit rather than merely inform.

A naive checker that looks backwards N characters for a filename produces false
positives on local range references such as "9.1-9.6" when a different spec is
named in the preceding sentence. That mistake was made and nearly filed as a
defect; the sentence-break reset below is what prevents it.
"""
from pathlib import Path
import re
import sys

files = sorted(Path("docs").glob("*-spec.md"))
heads = {p.name: set(re.findall(r"^#{1,6}\s+(\d+(?:\.\d+)*)(?=[.\s])", p.read_text(), re.M))
         for p in files}
errors, checked = [], 0

for p in files:
    text = p.read_text()
    lines = text.splitlines()
    if sum(l.lstrip().startswith("```") for l in lines) % 2:
        errors.append(f"{p}: unbalanced code fences")
    for i in range(1, len(lines) - 1):
        if (not lines[i].strip()
                and lines[i - 1].lstrip().startswith("|")
                and lines[i + 1].lstrip().startswith("|")):
            errors.append(f"{p}:{i + 1}: blank line splits a table")

    for m in re.finditer(r"`?([\w-]+-spec\.md)`?\s+(?:§)?(\d+(?:\.\d+)*)(?:[./–—-]§?(\d+(?:\.\d+)*))?", text):
        for n in m.groups()[1:]:
            if n:
                checked += 1
                if n not in heads.get(m[1], set()):
                    errors.append(f"{p}: {m[1]} section {n} absent")

    for line in lines:
        for m in re.finditer(r"§(\d+(?:\.\d+)*)", line):
            prefix = line[:m.start()]
            names = list(re.finditer(r"([\w-]+-spec\.md)", prefix))
            tail = prefix[names[-1].end():] if names else ""
            target = (names[-1][1] if names and len(tail) < 100
                      and not re.search(r"\.\s", tail) else p.name)
            checked += 1
            if m[1] not in heads.get(target, set()):
                errors.append(f"{p}: section {m[1]} unresolved in {target}")

print(f"Checked {checked} section references, fences and tables across {len(files)} specs.")
for e in errors:
    print(" ", e)
sys.exit(1 if errors else 0)
