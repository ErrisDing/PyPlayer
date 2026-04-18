#!/usr/bin/env python3
"""Check for common variable initialization and scope issues in Python files."""
import json
import sys
import re

def check_variable_issues(file_path):
    """Check for potential variable initialization/scope issues."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            
        issues = []
        
        # Check 1: Variable declared without initialization (standalone assignment)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            
            # Pattern: bare variable name at start of statement
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*$', stripped):
                issues.append(f"Line {i}: Variable '{stripped}' declared without initialization")
            
            # Pattern: variable in for loop (may not be defined)
            elif re.match(r'for\s+\w+.*in\s+', stripped, re.IGNORECASE):
                match = re.search(r'for\s+(\w+)\s+in', stripped, re.IGNORECASE)
                if match:
                    issues.append(f"Line {i}: Check variable '{match.group(1)}' defined in loop")
        
        # Check 2: Variables used before definition (basic check)
        seen_vars = set()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            
            # Find variable names (simple pattern)
            vars_in_line = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', stripped)
            
            for var in vars_in_line:
                # Skip keywords and common patterns
                if var in ['if', 'else', 'for', 'in', 'while', 'def', 'return']:
                    continue
                
                if var not in seen_vars:
                    # Only flag if it's being used (not assigned)
                    if '=' not in stripped or stripped.index(var) < stripped.index('='):
                        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=', stripped):
                            # This is an assignment, skip
                            pass
        
        for issue in issues[:10]:  # Limit output
            print(issue)
            
    except Exception as e:
        print(f"Error checking {file_path}: {e}", file=sys.stderr)

if __name__ == '__main__':
    input_data = sys.stdin.read()
    try:
        data = json.loads(input_data)
        file_path = data.get('tool_input', {}).get('file_path') or \
                    data.get('tool_response', {}).get('filePath')
        
        if file_path:
            check_variable_issues(file_path)
    except Exception as e:
        print(f"Error processing input: {e}", file=sys.stderr)
