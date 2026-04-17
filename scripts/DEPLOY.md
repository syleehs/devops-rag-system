# DEPLOY.md — `scripts/deploy.sh`

Idempotent production deployment of the DevOps RAG FastAPI service to AWS ECS Fargate.

## Prerequisites

Before your first run, make sure you have:

1. **An AWS account** with permissions for: ECR, ECS, IAM, VPC, RDS, Secrets Manager,
   CloudWatch, ELB, Auto Scaling. An administrator role is easiest; least-privilege is
   left to the reader.
2. **`aws configure`** completed (or `AWS_PROFILE` / `AWS_REGION` exported). The
   script calls `aws sts get-caller-identity` and fails fast if credentials are
   missing.
3. **Docker Desktop / daemon running.** The script verifies `docker info`.
4. **`infrastructure/terraform.tfvars`** created and filled in. Copy the template
   and edit at minimum the `anthropic_api_key` value:
   ```sh
   cp infrastructure/terraform.tfvars.template infrastructure/terraform.tfvars
   # edit infrastructure/terraform.tfvars and set anthropic_api_key = "sk-ant-..."
   ```
5. **CLI tools on PATH:** `aws`, `terraform`, `docker`, `jq`, `curl`, `git`. The
   script prints each tool's version at startup; install any missing ones and
   re-run.
6. **Project is a git repo** with at least one commit. The image tag is derived
   from `git rev-parse --short HEAD`.

> **ECR note:** the existing Terraform doesn't manage the ECR repository. `deploy.sh`
> creates it on the first run and then treats it as existing thereafter. When the
> Terraform catches up with an `aws_ecr_repository` resource, the script's Step 1
> will still work (it detects existing repos and SKIPs).

## One-line deploys

```sh
# First production deploy — end-to-end (ECR, Terraform, image, ECS, smoke test)
./scripts/deploy.sh

# Image-only update (backend code changed, infra unchanged)
./scripts/deploy.sh --skip-tf

# Preview everything without changing anything (dry run)
./scripts/deploy.sh --dry-run

# Full deploy + POST knowledge_base/*.md to the ALB /ingest endpoint
./scripts/deploy.sh --ingest-kb

# Combined: image-only update + knowledge base ingestion
./scripts/deploy.sh --skip-tf --ingest-kb

# Help
./scripts/deploy.sh --help
```

Environment overrides:

```sh
PROJECT_NAME=devops-rag AWS_REGION=us-east-1 ./scripts/deploy.sh
```

## Interpreting the output

Each step prints a header like `==> Step 3 — Docker image build & push` followed
by one or more result lines:

| Marker    | Meaning                                                         |
|-----------|-----------------------------------------------------------------|
| `✓`       | Check or sub-step passed                                        |
| `SKIP`    | Resource already in the desired state — no change made          |
| `CREATED` | A new resource was created                                      |
| `UPDATED` | An existing resource was updated in place                       |
| `WARNING` | Non-fatal issue (e.g. uncommitted changes, empty knowledge base)|
| `✗`       | Failure — script exits non-zero                                 |

The end of every run prints a bulleted **Deployment summary** listing each step's
outcome, and a `Deploy OK` footer on success. The full log is appended to
`deploy.log` at the project root.

A failure prints `DEPLOY FAILED at step: <name>` identifying which step broke, so
you know where to pick up on re-run. Every step is idempotent, so you can safely
re-run the script after fixing the root cause.

## Rollback

ECS retains previous task-definition revisions. To revert, point the service at
an older revision:

```sh
# List recent revisions (newest first)
aws ecs list-task-definitions \
    --family-prefix devops-rag \
    --sort DESC \
    --max-items 10

# Roll back to a specific revision
aws ecs update-service \
    --cluster devops-rag-cluster \
    --service devops-rag-service \
    --task-definition devops-rag:<REVISION_NUMBER> \
    --force-new-deployment

# Wait for it to become stable
aws ecs wait services-stable \
    --cluster devops-rag-cluster \
    --services devops-rag-service
```

No Docker rebuild is needed — the old task definition still references the old
ECR image tag (ECR is configured as `IMMUTABLE`, so tags can't be overwritten).

If the old image was deleted from ECR (e.g. via a lifecycle policy), you must
rebuild from that git SHA first:

```sh
git checkout <old-sha>
./scripts/deploy.sh --skip-tf
git checkout -
```

## Troubleshooting

### 1. `AWS credentials not configured`
Run `aws configure` or `export AWS_PROFILE=<profile>`. Verify with
`aws sts get-caller-identity`. If you're using SSO, run `aws sso login` first.

### 2. Region mismatch (`ResourceNotFoundException` on ECR / ECS)
Terraform was probably applied in a different region than the one `deploy.sh`
resolved. Check both:
```sh
grep aws_region infrastructure/terraform.tfvars
aws configure get region
echo "${AWS_REGION:-unset}"
```
Fix by exporting `AWS_REGION` to match `terraform.tfvars`, or by updating
`terraform.tfvars` and re-running `terraform apply` (script will handle that via
its normal plan/apply loop).

### 3. `docker push` denied / `no basic auth credentials`
The ECR login token expires after ~12 h. The script runs
`aws ecr get-login-password | docker login` fresh on every invocation, so just
re-run `./scripts/deploy.sh --skip-tf`. If it persists, verify your IAM
principal has `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`,
`ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`,
and `ecr:PutImage`.

### 4. ECS tasks keep stopping (Step 5 fails)
The script prints the `stoppedReason` for up to five recent stopped tasks.
Common causes:
- **`ResourceInitializationError` on secrets** — the task execution role can't
  read Secrets Manager. Verify `anthropic_api_key` secret actually exists and
  is non-empty.
- **`exec format error`** — the image was built for the wrong architecture.
  The script forces `--platform linux/amd64`; make sure you didn't remove that.
- **`CannotPullContainerError`** — the task execution role lacks ECR pull
  permissions, or the image tag no longer exists.
- **Health check failing** — tail CloudWatch logs:
  ```sh
  aws logs tail /ecs/devops-rag --follow --since 10m
  ```

### 5. ALB returns `503 Service Temporarily Unavailable` (Step 6 fails)
The ALB has no healthy targets. Check:
- Task definition is running (`aws ecs describe-services --cluster ... --services ...`).
- Target group health:
  ```sh
  aws elbv2 describe-target-health \
      --target-group-arn "$(aws elbv2 describe-target-groups \
        --names devops-rag-tg --query 'TargetGroups[0].TargetGroupArn' --output text)"
  ```
- Security groups allow ALB → ECS on 8000 (Terraform sets this up correctly by
  default; verify nothing has been manually altered).
- Container `/health` endpoint is returning 200 (tail CloudWatch logs as above).
