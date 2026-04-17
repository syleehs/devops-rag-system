#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/venv"
BACKEND="$REPO_ROOT/backend"
INFRA="$REPO_ROOT/infrastructure"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0

run_check() {
    local name="$1"
    shift
    printf "${YELLOW}[CHECK]${NC} %s... " "$name"
    if output=$("$@" 2>&1); then
        printf "${GREEN}PASS${NC}\n"
    else
        printf "${RED}FAIL${NC}\n"
        echo "$output" | head -30
        FAILED=$((FAILED + 1))
    fi
}

# Activate venv
source "$VENV/bin/activate"

echo "========================================="
echo "  Pre-commit Validation"
echo "========================================="
echo ""

# 1. Python syntax check
run_check "Python syntax (compile)" python3 -m py_compile "$BACKEND/main.py"
run_check "Python syntax (compile)" python3 -m py_compile "$BACKEND/rag_pipeline.py"
run_check "Python syntax (compile)" python3 -m py_compile "$BACKEND/config.py"
run_check "Python syntax (compile)" python3 -m py_compile "$BACKEND/metrics.py"

# 2. Ruff linting
run_check "Ruff lint" ruff check "$BACKEND" --config "$REPO_ROOT/pyproject.toml"

# 3. Ruff formatting
run_check "Ruff format" ruff format --check "$BACKEND" --config "$REPO_ROOT/pyproject.toml"

# 4. Pytest
run_check "Pytest" python3 -m pytest "$REPO_ROOT/tests" -v --tb=short

# 5. Terraform validate
if command -v terraform &>/dev/null; then
    run_check "Terraform fmt" terraform fmt -check -recursive "$INFRA"
    run_check "Terraform validate" bash -c "cd $INFRA && terraform validate"
else
    printf "${YELLOW}[SKIP]${NC} Terraform (not installed)\n"
fi

# 6. Check for secrets in staged files
run_check "No hardcoded secrets" bash -c '
    ! grep -rn --include="*.py" -E "(api_key|password|secret)\s*=\s*[\"'"'"'][^\"'"'"']{8,}" '"$BACKEND"' \
    | grep -v "os\.getenv" | grep -v "os\.environ" | grep -v "\.example" | grep -v "# " | head -5
'

echo ""
echo "========================================="
if [ "$FAILED" -eq 0 ]; then
    printf "  ${GREEN}All checks passed!${NC}\n"
else
    printf "  ${RED}%d check(s) failed${NC}\n" "$FAILED"
fi
echo "========================================="

exit "$FAILED"
