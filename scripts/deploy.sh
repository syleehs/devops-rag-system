#!/usr/bin/env bash
#
# deploy.sh — Production deployment for the DevOps RAG FastAPI service on AWS ECS Fargate.
#
# This script is idempotent and safe to re-run. Every destructive/expensive AWS call is
# guarded by a precondition check, and every step reports ✓ / ✗ / SKIP / CREATED / UPDATED.
#
# NOTE: ECR is managed by this script (not Terraform) because the existing Terraform
# configuration does not include an aws_ecr_repository resource. This should eventually
# be migrated into infrastructure/*.tf so all state lives in Terraform.
#
# Usage: see --help below.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths / configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROJECT_NAME="${PROJECT_NAME:-devops-rag}"
TF_DIR_NAME="${TF_DIR:-infrastructure}"
TF_DIR="${PROJECT_ROOT}/${TF_DIR_NAME}"
BACKEND_DIR="${PROJECT_ROOT}/backend"
KB_DIR="${PROJECT_ROOT}/knowledge_base"
LOG_FILE="${PROJECT_ROOT}/deploy.log"

# Flags
DRY_RUN=0
SKIP_TF=0
INGEST_KB=0

# Runtime state (populated by steps)
AWS_ACCOUNT_ID=""
REGION=""
REPO_URI=""
IMAGE_TAG=""
ALB_DNS=""
ECS_CLUSTER=""
ECS_SERVICE=""
NEW_TASK_DEF_ARN=""
CURRENT_STEP="init"

# Summary counters
SUMMARY=()

# ---------------------------------------------------------------------------
# Colors / logging
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
    C_RESET='\033[0m'
    C_BOLD='\033[1m'
    C_DIM='\033[2m'
    C_RED='\033[31m'
    C_GREEN='\033[32m'
    C_YELLOW='\033[33m'
    C_BLUE='\033[34m'
    C_CYAN='\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_CYAN=''
fi

# Redirect stdout+stderr to both terminal and deploy.log.
# Uses process substitution with tee; preserves colors on terminal (tee strips nothing).
mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

log()        { printf '%b\n' "$*"; }
log_info()   { log "${C_BLUE}[INFO]${C_RESET} $*"; }
log_ok()     { log "${C_GREEN}  ✓${C_RESET} $*"; }
log_skip()   { log "${C_DIM}  SKIP${C_RESET} $*"; }
log_create() { log "${C_GREEN}  CREATED${C_RESET} $*"; }
log_update() { log "${C_GREEN}  UPDATED${C_RESET} $*"; }
log_warn()   { log "${C_YELLOW}  WARNING${C_RESET} $*"; }
log_fail()   { log "${C_RED}  ✗${C_RESET} $*"; }
log_step()   { log ""; log "${C_BOLD}${C_CYAN}==> $*${C_RESET}"; }

die() {
    log_fail "$*"
    exit 1
}

record() { SUMMARY+=("$*"); }

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
${C_BOLD}deploy.sh${C_RESET} — Deploy the DevOps RAG service to AWS ECS Fargate.

${C_BOLD}Usage:${C_RESET}
    scripts/deploy.sh [options]

${C_BOLD}Options:${C_RESET}
    --dry-run         Run all preconditions and print planned actions, but do not
                      apply Terraform, push Docker images, or update the ECS service.
    --skip-tf         Skip Terraform init/plan/apply (image-only update path).
    --ingest-kb       After a successful smoke test, POST every knowledge_base/*.md
                      file to the ALB /ingest endpoint.
    -h, --help        Show this help and exit.

${C_BOLD}Environment variables:${C_RESET}
    PROJECT_NAME      ECR repo + Terraform project_name (default: devops-rag)
    AWS_REGION        AWS region (falls back to AWS_DEFAULT_REGION / aws configure)
    TF_DIR            Terraform directory name under project root (default: infrastructure)

${C_BOLD}Examples:${C_RESET}
    # First production deploy (full path: TF + image + service + smoke test)
    scripts/deploy.sh

    # Image-only update after backend code change
    scripts/deploy.sh --skip-tf

    # Preview every action without applying anything
    scripts/deploy.sh --dry-run

    # Deploy and ingest knowledge base documents
    scripts/deploy.sh --ingest-kb
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)   DRY_RUN=1; shift ;;
            --skip-tf)   SKIP_TF=1; shift ;;
            --ingest-kb) INGEST_KB=1; shift ;;
            -h|--help)   usage; exit 0 ;;
            *) die "Unknown argument: $1 (use --help)" ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Trap
# ---------------------------------------------------------------------------
on_exit() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log ""
        log "${C_RED}${C_BOLD}DEPLOY FAILED at step: ${CURRENT_STEP}${C_RESET}"
        log "${C_DIM}See ${LOG_FILE} for the full log.${C_RESET}"
    fi
    exit $rc
}
trap on_exit EXIT

# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------
check_tool() {
    local tool="$1"
    if ! command -v "${tool}" >/dev/null 2>&1; then
        die "Missing required tool: ${tool}. Install it and re-run."
    fi
    local version
    case "${tool}" in
        aws)       version="$(aws --version 2>&1 | head -n1)" ;;
        terraform) version="$(terraform version 2>&1 | head -n1)" ;;
        docker)    version="$(docker --version 2>&1 | head -n1)" ;;
        jq)        version="$(jq --version 2>&1 | head -n1)" ;;
        curl)      version="$(curl --version 2>&1 | head -n1)" ;;
        git)       version="$(git --version 2>&1 | head -n1)" ;;
        *)         version="$(${tool} --version 2>&1 | head -n1 || echo unknown)" ;;
    esac
    log_ok "${tool}: ${version}"
}

check_preconditions() {
    CURRENT_STEP="preconditions"
    log_step "Preconditions"

    # 1. Tools
    log_info "Checking required tools..."
    for tool in aws terraform docker jq curl git; do
        check_tool "${tool}"
    done

    # 2. AWS credentials
    log_info "Checking AWS credentials..."
    local caller
    if ! caller="$(aws sts get-caller-identity --output json 2>&1)"; then
        log_fail "${caller}"
        die "AWS credentials not configured. Run 'aws configure' or export AWS_PROFILE."
    fi
    AWS_ACCOUNT_ID="$(printf '%s' "${caller}" | jq -r '.Account')"
    local caller_arn
    caller_arn="$(printf '%s' "${caller}" | jq -r '.Arn')"
    log_ok "AWS account: ${AWS_ACCOUNT_ID} (${caller_arn})"

    # 3. Region
    log_info "Resolving AWS region..."
    if [[ -n "${AWS_REGION:-}" ]]; then
        REGION="${AWS_REGION}"
    elif [[ -n "${AWS_DEFAULT_REGION:-}" ]]; then
        REGION="${AWS_DEFAULT_REGION}"
    else
        REGION="$(aws configure get region 2>/dev/null || true)"
    fi
    if [[ -z "${REGION}" ]]; then
        die "AWS region not set. Export AWS_REGION or run 'aws configure set region <region>'."
    fi
    export AWS_REGION="${REGION}"
    export AWS_DEFAULT_REGION="${REGION}"
    log_ok "AWS region: ${REGION}"

    # 4. Docker daemon
    log_info "Checking Docker daemon..."
    if ! docker info >/dev/null 2>&1; then
        die "Docker daemon is not running. Start Docker Desktop (macOS/Windows) or 'sudo systemctl start docker' (Linux)."
    fi
    log_ok "Docker daemon is running"

    # 5. Required files
    log_info "Checking required files..."
    [[ -f "${BACKEND_DIR}/Dockerfile" ]] \
        || die "Missing ${BACKEND_DIR}/Dockerfile"
    log_ok "backend/Dockerfile present"

    [[ -f "${TF_DIR}/main.tf" ]] \
        || die "Missing ${TF_DIR}/main.tf"
    log_ok "infrastructure/main.tf present"

    if [[ ! -f "${TF_DIR}/terraform.tfvars" ]]; then
        die "Missing ${TF_DIR}/terraform.tfvars. Copy ${TF_DIR}/terraform.tfvars.template to terraform.tfvars and fill in 'anthropic_api_key'."
    fi
    log_ok "infrastructure/terraform.tfvars present"

    # 6. Knowledge base count
    local kb_count=0
    if [[ -d "${KB_DIR}" ]]; then
        kb_count="$(find "${KB_DIR}" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
    fi
    if [[ "${kb_count}" -eq 0 ]]; then
        log_warn "knowledge_base/ is empty or missing — no documents to ingest"
    else
        log_ok "knowledge_base/: ${kb_count} markdown file(s)"
    fi

    # Flag recap
    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "DRY-RUN mode: no changes will be applied"
    fi
    if [[ $SKIP_TF -eq 1 ]]; then
        log_info "SKIP_TF enabled: Terraform steps will be skipped"
    fi
    record "Preconditions: OK"
}

# ---------------------------------------------------------------------------
# Step 1 — ECR repository
# ---------------------------------------------------------------------------
step_ecr() {
    CURRENT_STEP="ecr"
    log_step "Step 1 — ECR repository (${PROJECT_NAME})"

    if aws ecr describe-repositories \
            --repository-names "${PROJECT_NAME}" \
            --region "${REGION}" >/dev/null 2>&1; then
        REPO_URI="$(aws ecr describe-repositories \
            --repository-names "${PROJECT_NAME}" \
            --region "${REGION}" \
            --query 'repositories[0].repositoryUri' \
            --output text)"
        log_skip "ECR repository '${PROJECT_NAME}' already exists"
        log_info "Repo URI: ${REPO_URI}"
        record "ECR: SKIP (already exists)"
        return
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would create ECR repository '${PROJECT_NAME}'"
        REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${PROJECT_NAME}"
        record "ECR: DRY-RUN (would create)"
        return
    fi

    REPO_URI="$(aws ecr create-repository \
        --repository-name "${PROJECT_NAME}" \
        --region "${REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability IMMUTABLE \
        --query 'repository.repositoryUri' \
        --output text)"
    log_create "ECR repository created: ${REPO_URI}"
    record "ECR: CREATED"
}

# ---------------------------------------------------------------------------
# Step 2 — Terraform
# ---------------------------------------------------------------------------
step_terraform() {
    CURRENT_STEP="terraform"
    log_step "Step 2 — Terraform (${TF_DIR_NAME}/)"

    if [[ $SKIP_TF -eq 1 ]]; then
        log_skip "Terraform skipped (--skip-tf). Reading existing outputs..."
        read_terraform_outputs
        record "Terraform: SKIP (--skip-tf)"
        return
    fi

    # terraform init if needed
    if [[ ! -d "${TF_DIR}/.terraform" ]]; then
        log_info "Running terraform init..."
        (cd "${TF_DIR}" && terraform init -input=false)
        log_create ".terraform/ initialized"
    else
        log_skip ".terraform/ already present — skipping init"
    fi

    # terraform plan -detailed-exitcode
    log_info "Running terraform plan..."
    local plan_rc=0
    (cd "${TF_DIR}" && terraform plan -input=false -out=tfplan -detailed-exitcode) || plan_rc=$?

    case "${plan_rc}" in
        0)
            log_ok "Terraform: no changes"
            record "Terraform: SKIP (no changes)"
            ;;
        2)
            log_info "Terraform plan has pending changes:"
            (cd "${TF_DIR}" && terraform show -no-color tfplan | head -n 80) || true
            if [[ $DRY_RUN -eq 1 ]]; then
                log_warn "[dry-run] Would apply Terraform plan"
                record "Terraform: DRY-RUN (plan has changes)"
            else
                local ans=""
                printf "${C_YELLOW}Apply these changes? [y/N]: ${C_RESET}"
                read -r ans || ans=""
                if [[ "${ans}" =~ ^[Yy]$ ]]; then
                    (cd "${TF_DIR}" && terraform apply -input=false -auto-approve tfplan)
                    log_update "Terraform applied"
                    record "Terraform: UPDATED"
                else
                    die "User declined to apply Terraform changes."
                fi
            fi
            ;;
        *)
            die "terraform plan failed with exit code ${plan_rc}"
            ;;
    esac

    read_terraform_outputs
}

read_terraform_outputs() {
    log_info "Reading Terraform outputs..."
    local outputs
    if ! outputs="$(cd "${TF_DIR}" && terraform output -json 2>/dev/null)"; then
        log_warn "Unable to read terraform outputs — did you run terraform apply yet?"
        return
    fi

    ALB_DNS="$(printf '%s' "${outputs}" | jq -r '.alb_dns_name.value // empty')"
    ECS_CLUSTER="$(printf '%s' "${outputs}" | jq -r '.ecs_cluster_name.value // empty')"
    ECS_SERVICE="$(printf '%s' "${outputs}" | jq -r '.ecs_service_name.value // empty')"
    local rds_endpoint
    rds_endpoint="$(printf '%s' "${outputs}" | jq -r '.rds_endpoint.value // empty')"

    log_ok "ALB DNS:        ${ALB_DNS:-<unset>}"
    log_ok "ECS cluster:    ${ECS_CLUSTER:-<unset>}"
    log_ok "ECS service:    ${ECS_SERVICE:-<unset>}"
    log_ok "RDS endpoint:   ${rds_endpoint:-<unset>}"
}

# ---------------------------------------------------------------------------
# Step 3 — Build and push Docker image
# ---------------------------------------------------------------------------
compute_image_tag() {
    if ! (cd "${PROJECT_ROOT}" && git rev-parse --git-dir >/dev/null 2>&1); then
        die "Project root is not a git repository — cannot compute an immutable tag."
    fi
    local sha
    sha="$(cd "${PROJECT_ROOT}" && git rev-parse --short HEAD)"

    local dirty=""
    if ! (cd "${PROJECT_ROOT}" && git diff-index --quiet HEAD -- 2>/dev/null); then
        log_warn "Uncommitted changes detected — tag will be suffixed with -dirty"
        dirty="-dirty"
    fi
    IMAGE_TAG="${sha}${dirty}"
}

step_image() {
    CURRENT_STEP="image"
    log_step "Step 3 — Docker image build & push"

    compute_image_tag
    log_info "Image tag: ${IMAGE_TAG}"

    if [[ -z "${REPO_URI}" ]]; then
        REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${PROJECT_NAME}"
    fi
    log_info "Repo URI: ${REPO_URI}"

    # Check if tag already exists in ECR
    if aws ecr describe-images \
            --repository-name "${PROJECT_NAME}" \
            --image-ids "imageTag=${IMAGE_TAG}" \
            --region "${REGION}" >/dev/null 2>&1; then
        log_skip "Image ${REPO_URI}:${IMAGE_TAG} already exists in ECR — skipping build/push"
        record "Image: SKIP (tag already in ECR)"
        return
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would docker build --platform linux/amd64 -t ${REPO_URI}:${IMAGE_TAG}"
        log_warn "[dry-run] Would docker push ${REPO_URI}:${IMAGE_TAG}"
        record "Image: DRY-RUN (would build+push ${IMAGE_TAG})"
        return
    fi

    # ECR login
    log_info "Logging in to ECR..."
    aws ecr get-login-password --region "${REGION}" \
        | docker login \
            --username AWS \
            --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
    log_ok "Docker authenticated to ECR"

    # Build (force amd64 — Fargate x86 targets will fail silently on Apple Silicon arm64 builds)
    log_info "Building image (platform linux/amd64)..."
    docker build \
        --platform linux/amd64 \
        -t "${REPO_URI}:${IMAGE_TAG}" \
        -f "${BACKEND_DIR}/Dockerfile" \
        "${PROJECT_ROOT}"
    log_create "Image built: ${REPO_URI}:${IMAGE_TAG}"

    # Push
    log_info "Pushing image..."
    docker push "${REPO_URI}:${IMAGE_TAG}"
    log_create "Image pushed: ${REPO_URI}:${IMAGE_TAG}"
    record "Image: CREATED (${IMAGE_TAG})"
}

# ---------------------------------------------------------------------------
# Step 4 — Update ECS task definition and service
# ---------------------------------------------------------------------------
step_ecs_update() {
    CURRENT_STEP="ecs_update"
    log_step "Step 4 — ECS task definition & service"

    if [[ -z "${ECS_CLUSTER}" || -z "${ECS_SERVICE}" ]]; then
        if [[ $DRY_RUN -eq 1 ]]; then
            log_warn "[dry-run] ECS cluster/service not yet created (Terraform outputs empty) — skipping ECS update checks"
            log_warn "[dry-run] On real run, Terraform apply would create them first, then this step would register task def and update service"
            record "ECS: DRY-RUN (cluster/service would be created by Terraform first)"
            return
        fi
        die "ECS cluster/service names not available — Terraform outputs missing. Did Terraform apply succeed?"
    fi

    local desired_image="${REPO_URI}:${IMAGE_TAG}"

    log_info "Fetching active task definition..."
    local current_td
    current_td="$(aws ecs describe-task-definition \
        --task-definition "${PROJECT_NAME}" \
        --region "${REGION}")"

    local current_image
    current_image="$(printf '%s' "${current_td}" \
        | jq -r '.taskDefinition.containerDefinitions[0].image')"
    log_info "Current image: ${current_image}"
    log_info "Desired image: ${desired_image}"

    if [[ "${current_image}" == "${desired_image}" ]]; then
        log_skip "Task definition already references ${desired_image}"
        record "ECS: SKIP (task def up-to-date)"
        return
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would register new task def with image ${desired_image}"
        log_warn "[dry-run] Would update service ${ECS_SERVICE} with --force-new-deployment"
        record "ECS: DRY-RUN (would update task def + service)"
        return
    fi

    # Build new task-def JSON: mutate image, strip non-registerable fields
    local new_td_json
    new_td_json="$(printf '%s' "${current_td}" | jq \
        --arg img "${desired_image}" '
            .taskDefinition
            | .containerDefinitions[0].image = $img
            | del(
                .taskDefinitionArn,
                .revision,
                .status,
                .requiresAttributes,
                .compatibilities,
                .registeredAt,
                .registeredBy
            )
        ')"

    log_info "Registering new task definition revision..."
    NEW_TASK_DEF_ARN="$(aws ecs register-task-definition \
        --region "${REGION}" \
        --cli-input-json "${new_td_json}" \
        --query 'taskDefinition.taskDefinitionArn' \
        --output text)"
    log_create "Task definition registered: ${NEW_TASK_DEF_ARN}"

    log_info "Updating ECS service..."
    aws ecs update-service \
        --region "${REGION}" \
        --cluster "${ECS_CLUSTER}" \
        --service "${ECS_SERVICE}" \
        --task-definition "${NEW_TASK_DEF_ARN}" \
        --force-new-deployment >/dev/null
    log_update "ECS service update triggered"
    record "ECS: UPDATED (${NEW_TASK_DEF_ARN##*/})"
}

# ---------------------------------------------------------------------------
# Step 5 — Wait for service stability
# ---------------------------------------------------------------------------
step_wait_stable() {
    CURRENT_STEP="wait_stable"
    log_step "Step 5 — Wait for service stability"

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would wait on services-stable for ${ECS_SERVICE}"
        record "Stability: DRY-RUN"
        return
    fi

    if [[ -z "${ECS_CLUSTER}" || -z "${ECS_SERVICE}" ]]; then
        log_warn "No ECS cluster/service — skipping stability wait"
        return
    fi

    log_info "Waiting for services-stable (up to ~10 min)..."
    local rc=0
    aws ecs wait services-stable \
        --region "${REGION}" \
        --cluster "${ECS_CLUSTER}" \
        --services "${ECS_SERVICE}" || rc=$?

    if [[ $rc -eq 0 ]]; then
        log_ok "ECS service is stable"
        record "Stability: OK"
        return
    fi

    log_fail "ECS service did not reach stable state. Fetching last stopped tasks..."
    local stopped_arns
    stopped_arns="$(aws ecs list-tasks \
        --region "${REGION}" \
        --cluster "${ECS_CLUSTER}" \
        --service-name "${ECS_SERVICE}" \
        --desired-status STOPPED \
        --query 'taskArns' \
        --output json 2>/dev/null || echo '[]')"

    local arns
    arns="$(printf '%s' "${stopped_arns}" | jq -r '.[0:5] | .[]')"
    if [[ -n "${arns}" ]]; then
        # shellcheck disable=SC2086
        aws ecs describe-tasks \
            --region "${REGION}" \
            --cluster "${ECS_CLUSTER}" \
            --tasks ${arns} \
            --query 'tasks[].{taskArn:taskArn,lastStatus:lastStatus,stoppedReason:stoppedReason,containers:containers[].{name:name,reason:reason,exitCode:exitCode}}' \
            --output json
    else
        log_warn "No stopped tasks found — check CloudWatch logs for the ECS service."
    fi
    die "ECS service is unhealthy — see stopped task reasons above."
}

# ---------------------------------------------------------------------------
# Step 6 — Smoke test ALB
# ---------------------------------------------------------------------------
step_smoke_test() {
    CURRENT_STEP="smoke_test"
    log_step "Step 6 — ALB smoke test"

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would curl http://${ALB_DNS:-<alb>}/health"
        record "Smoke test: DRY-RUN"
        return
    fi

    if [[ -z "${ALB_DNS}" ]]; then
        die "ALB DNS name is empty — cannot run smoke test."
    fi

    local url="http://${ALB_DNS}/health"
    log_info "Polling ${url} (up to 30 attempts, 10s interval)..."

    local attempt=0
    local max_attempts=30
    local status=""
    while (( attempt < max_attempts )); do
        attempt=$((attempt + 1))
        status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${url}" || echo '000')"
        if [[ "${status}" == "200" ]]; then
            log_ok "Health check returned 200 on attempt ${attempt}"
            record "Smoke test: OK (attempt ${attempt})"
            return
        fi
        log_info "  attempt ${attempt}/${max_attempts}: status=${status} — retrying in 10s"
        sleep 10
    done

    die "Smoke test failed: last status=${status} after ${max_attempts} attempts at ${url}"
}

# ---------------------------------------------------------------------------
# Step 7 — Optional: ingest knowledge base
# ---------------------------------------------------------------------------
step_ingest_kb() {
    CURRENT_STEP="ingest_kb"
    log_step "Step 7 — Ingest knowledge base"

    if [[ $INGEST_KB -ne 1 ]]; then
        log_skip "--ingest-kb not set"
        return
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        log_warn "[dry-run] Would POST knowledge_base/*.md to http://${ALB_DNS:-<alb>}/ingest"
        record "Ingest: DRY-RUN"
        return
    fi

    if [[ -z "${ALB_DNS}" ]]; then
        die "ALB DNS name is empty — cannot ingest."
    fi

    if [[ ! -d "${KB_DIR}" ]]; then
        log_warn "knowledge_base/ directory missing — nothing to ingest"
        return
    fi

    local url="http://${ALB_DNS}/ingest"
    local success=0
    local failure=0
    local file title payload status

    shopt -s nullglob
    local md_files=("${KB_DIR}"/*.md)
    shopt -u nullglob

    if [[ ${#md_files[@]} -eq 0 ]]; then
        log_warn "No .md files in knowledge_base/ — skipping"
        record "Ingest: 0 files"
        return
    fi

    for file in "${md_files[@]}"; do
        title="$(basename "${file}" .md)"
        # Safe JSON encoding of title + content via jq -Rs
        payload="$(jq -n \
            --arg title "${title}" \
            --rawfile content "${file}" \
            '{title: $title, content: $content, category: "knowledge_base", tags: ["auto-ingested"]}')"

        status="$(curl -sS -o /tmp/deploy_ingest_body.$$ -w '%{http_code}' \
            --max-time 60 \
            -X POST \
            -H 'Content-Type: application/json' \
            --data-binary "${payload}" \
            "${url}" || echo '000')"

        if [[ "${status}" == "200" ]]; then
            log_ok "ingested ${title}"
            success=$((success + 1))
        else
            local body
            body="$(head -c 400 /tmp/deploy_ingest_body.$$ 2>/dev/null || true)"
            log_fail "ingest failed for ${title} (status=${status}): ${body}"
            failure=$((failure + 1))
        fi
        rm -f /tmp/deploy_ingest_body.$$
    done

    log_info "Ingest summary: ${success} succeeded, ${failure} failed"
    record "Ingest: ${success} OK / ${failure} failed"
}

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
print_summary() {
    CURRENT_STEP="summary"
    log ""
    log "${C_BOLD}${C_CYAN}==> Deployment summary${C_RESET}"
    for line in "${SUMMARY[@]}"; do
        log "  • ${line}"
    done
    if [[ -n "${ALB_DNS}" ]]; then
        log ""
        log "${C_BOLD}API endpoint:${C_RESET} http://${ALB_DNS}"
    fi
    log "${C_DIM}Full log: ${LOG_FILE}${C_RESET}"
    log "${C_GREEN}${C_BOLD}Deploy OK${C_RESET}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    log "${C_BOLD}DevOps RAG — AWS ECS Fargate deploy${C_RESET}"
    log "${C_DIM}Project: ${PROJECT_NAME} | TF dir: ${TF_DIR_NAME} | Log: ${LOG_FILE}${C_RESET}"
    log "${C_DIM}Flags: dry-run=${DRY_RUN} skip-tf=${SKIP_TF} ingest-kb=${INGEST_KB}${C_RESET}"

    check_preconditions
    step_ecr
    step_terraform
    step_image
    step_ecs_update
    step_wait_stable
    step_smoke_test
    step_ingest_kb
    print_summary
}

main "$@"
