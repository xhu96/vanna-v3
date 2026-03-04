#!/usr/bin/env python3
"""
Upgrade Impact Analyzer

This script analyses recent git changes to determine what collateral files
(documentation, tests, requirements, schemas, changelog, diagrams)
might need to be updated.

Usage:
    python scripts/check_upgrade_impact.py [commit|branch]
    
    # Check changes against main
    python scripts/check_upgrade_impact.py main
    
    # Check uncommitted workspace changes
    python scripts/check_upgrade_impact.py HEAD
"""

import subprocess
import sys
from typing import List, Set

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def get_changed_files(target: str = "HEAD") -> Set[str]:
    """Get list of changed files compared to target."""
    try:
        if target == "HEAD":
            # Uncommitted and staged changes
            cmd = ["git", "diff", "--name-only", "HEAD"]
        else:
            # Changes against a branch/commit
            cmd = ["git", "diff", "--name-only", f"{target}...HEAD"]
            
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = set(filter(None, result.stdout.split('\n')))
        
        # Also get untracked files
        if target == "HEAD":
            untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                     capture_output=True, text=True, check=True)
            files.update(filter(None, untracked.stdout.split('\n')))
            
        return files
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}Error running git command. Are you in a git repository?{Colors.ENDC}")
        sys.exit(1)

def analyze_impact(changed_files: Set[str]) -> List[str]:
    """Analyze changed files and generate warnings/reminders."""
    warnings = []
    
    # Categories of changes
    src_changed = any(f.startswith('src/') for f in changed_files)
    core_changed = any(f.startswith('src/vanna/core/') for f in changed_files)
    models_changed = any('models.py' in f for f in changed_files)
    api_changed = any(f.startswith('app/') for f in changed_files)
    ui_changed = any(f.startswith('static/') for f in changed_files)
    deps_changed = 'pyproject.toml' in changed_files
    
    # Categories of collateral
    tests_changed = any(f.startswith('tests/') for f in changed_files)
    docs_changed = any(f.startswith('docs/') or f == 'README.md' for f in changed_files)
    changelog_changed = 'CHANGELOG.md' in changed_files
    version_changed = 'VERSION.txt' in changed_files or 'pyproject.toml' in changed_files
    diagrams_changed = any(f.startswith('img/') for f in changed_files)
    reqs_changed = 'requirements.txt' in changed_files
    
    # --- Rules ---
    
    if src_changed and not changelog_changed:
        warnings.append("⚠️  Source code changed, but CHANGELOG.md was not updated.")
        
    if src_changed and not tests_changed:
        warnings.append("⚠️  Source code changed, but no files in tests/ were updated.")
        
    if src_changed and not version_changed:
        warnings.append("ℹ️  Source code changed. Did you forget to bump VERSION.txt?")
        
    if deps_changed and not reqs_changed:
        warnings.append("⚠️  pyproject.toml changed. Did you forget to sync requirements.txt?")
        
    if api_changed and not docs_changed:
        warnings.append("⚠️  API routes changed (app/). Please update docs/v3/ API tables.")
        
    if core_changed and not diagrams_changed:
        warnings.append("ℹ️  Core architecture changed. Check if img/data_eng_architecture.svg needs updating.")
        
    if models_changed:
        warnings.append("ℹ️  Data models/schemas changed. Ensure schema definitions in docs or notebooks reflect this.")
        
    if ui_changed and not docs_changed:
        warnings.append("ℹ️  Static UI assets changed. Consider updating README.md usage examples.")
        
    return warnings

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    print(f"\n{Colors.BOLD}{Colors.OKBLUE}🔍 Analyzing upgrade impact against: {target}{Colors.ENDC}\n")
    
    changed_files = get_changed_files(target)
    
    if not changed_files:
        print(f"{Colors.OKGREEN}No files changed.{Colors.ENDC}")
        return
        
    print(f"Found {len(changed_files)} changed files.")
    
    warnings = analyze_impact(changed_files)
    
    print("\n" + "="*50)
    if not warnings:
        print(f"{Colors.OKGREEN}✅ All good! No missing updates detected.{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}ACTION REQUIRED: Missed Updates Detected{Colors.ENDC}\n")
        for warning in warnings:
            if warning.startswith("⚠️"):
                print(f"{Colors.FAIL}{warning}{Colors.ENDC}")
            else:
                print(f"{Colors.OKCYAN}{warning}{Colors.ENDC}")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
