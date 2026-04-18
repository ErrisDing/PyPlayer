#!/usr/bin/env python3
"""
Check for Chinese comments in Python files
"""
import os
import re
import sys

def contains_chinese(text):
    """Check if text contains Chinese characters"""
    # Unicode range for Chinese characters
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
    return bool(chinese_pattern.search(text))

def check_file(filepath):
    """Check for Chinese comments in a single file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    issues = []
    in_multiline_comment = False
    multiline_start = 0

    for i, line in enumerate(lines, 1):
        line = line.rstrip('\n')

        # Check single-line comments
        if '#' in line:
            comment_start = line.find('#')
            comment = line[comment_start:]
            if contains_chinese(comment):
                issues.append((i, 'Single-line comment', comment))

        # Check multi-line strings (docstrings)
        if '"""' in line or "'''" in line:
            # Simplified handling: if line contains triple quotes and Chinese, report
            if contains_chinese(line):
                # Check if it's a docstring (usually at line start or after def/class)
                issues.append((i, 'Docstring', line.strip()))

    return issues

def main():
    python_files = []
    for root, dirs, files in os.walk('.'):
        # Skip some directories
        if '.git' in root or '__pycache__' in root:
            continue

        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))

    total_issues = 0
    for filepath in python_files:
        issues = check_file(filepath)
        if issues:
            print(f"\n{filepath}:")
            for line_num, comment_type, content in issues:
                print(f"  Line {line_num} [{comment_type}]: {content[:80]}...")
                total_issues += 1

    print(f"\nTotal: {total_issues} Chinese comments/docstrings")
    return total_issues

if __name__ == '__main__':
    sys.exit(main())