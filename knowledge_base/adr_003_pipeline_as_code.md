# ADR-003: CI/CD Pipeline as Code Migration from Travis to Tekton

## Status
Accepted

## Context

Our CI/CD infrastructure had evolved into a fragmented mess:
- Build automation split between Travis CI (GitHub) and manual Tekton (Kubernetes)
- Pipeline definitions scattered across multiple repos and configuration formats
- Difficult to maintain consistency across dev, staging, and production deployments
- Limited visibility into multi-cluster deployments
- Onboarding new teams required understanding multiple CI/CD systems

Pain points with Travis:
- Limited native Kubernetes integration
- Pipelines defined in `.travis.yml` files (not version controlled properly)
- Difficult to test pipeline changes before deploying
- Limited multi-cluster support
- Separate system to manage and maintain

At IBM Cloud Pipeline, we were managing infrastructure across multiple Kubernetes clusters with different deployment requirements per environment. We needed a unified, Kubernetes-native CI/CD solution.

## Decision

We migrated all CI/CD pipelines from Travis to Tekton with a "Pipeline as Code" strategy:

### 1. Consolidate on Tekton
- Single CI/CD system running natively on Kubernetes
- All pipelines execute as Kubernetes resources
- Eliminates need for Travis CI
- Reduces operational complexity

### 2. Pipeline as Code Architecture
- All pipeline definitions stored in Git as YAML/code
- Pipelines are version-controlled and reviewable via Git
- Changes to pipelines go through pull request process
- Pipeline configuration lives with application code
- Teams can test pipeline changes before deploying

### 3. Standardized Location for Automation
**Before (fragmented):**
- Travis configs: `.travis.yml` in repo root
- Tekton tasks: scattered across different repos
- Custom scripts: `/scripts/ci_*.sh` in repo
- Environment-specific configs: not centralized

**After (unified):**
- All pipeline definitions: `/tekton/` directory in repo
- Task definitions: `/tekton/tasks/`
- Pipeline definitions: `/tekton/pipelines/`
- Environment-specific overlays: `/tekton/overlays/dev|staging|prod/`
- Shared scripts: `/tekton/scripts/`

### 4. Multi-Cluster Pipeline Support
- Single pipeline definition can target multiple clusters
- Tekton Triggers handle webhook events from multiple repos
- Pipeline parameters specify target environment (dev/staging/prod)
- Same pipeline runs on different clusters with environment-specific configuration

### 5. Standardized Pipeline Workflow
```
1. Code commit to Git
2. Webhook triggers Tekton EventListener
3. EventListener creates PipelineRun resource
4. Tekton executes pipeline:
   - Build: Compile code, run tests, build container
   - Push: Push container image to registry
   - Deploy: Run environment-specific deployment
5. Results stored in Tekton, accessible via dashboard or API
```

## Consequences

### Benefits
- **Single system to manage:** Reduced operational overhead
- **Version-controlled pipelines:** Pipeline changes auditable via Git history
- **Kubernetes-native:** Runs on cluster, no external CI/CD service needed
- **Multi-cluster support:** Same pipeline definition deploys to multiple clusters
- **Pipeline as Code:** Teams can modify pipelines without ops involvement
- **Testable pipelines:** Developers can test pipeline changes locally before deploying
- **Better visibility:** All pipeline execution logs accessible via Kubernetes API
- **Easier onboarding:** New teams follow standardized pattern in `/tekton/` directory

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Learning curve | Teams unfamiliar with Tekton syntax | Documentation, templates, examples |
| Tekton complexity | YAML can get verbose | Use Tekton Helm charts, pre-built task library |
| Pipeline failures affect cluster | Runaway pipelines consume cluster resources | Resource quotas, PipelineRun limits |
| Coordination required | Tekton runs on cluster, requires cluster access | CI/CD cluster separate from prod clusters |

## Implementation Details

### Directory Structure

```
repository/
├── tekton/
│   ├── tasks/
│   │   ├── build.yaml          # Build container image
│   │   ├── run-tests.yaml      # Run unit/integration tests
│   │   ├── push-image.yaml     # Push image to registry
│   │   └── deploy.yaml         # Deploy to Kubernetes
│   ├── pipelines/
│   │   ├── build-and-test.yaml # Main pipeline definition
│   │   └── deploy-prod.yaml    # Production deployment pipeline
│   ├── triggers/
│   │   └── github-webhook.yaml # EventListener for GitHub webhooks
│   ├── overlays/
│   │   ├── dev/
│   │   │   └── kustomization.yaml
│   │   ├── staging/
│   │   │   └── kustomization.yaml
│   │   └── prod/
│   │       └── kustomization.yaml
│   └── scripts/
│       ├── build.sh
│       ├── test.sh
│       └── deploy.sh
└── .gitignore
```

### Example Pipeline Definition

```yaml
apiVersion: tekton.dev/v1beta1
kind: Pipeline
metadata:
  name: build-and-deploy
spec:
  params:
    - name: git-url
      type: string
    - name: environment
      type: string
      default: staging
  tasks:
    - name: clone-repo
      taskRef:
        name: git-clone
      params:
        - name: url
          value: $(params.git-url)
    
    - name: run-tests
      runAfter: [clone-repo]
      taskRef:
        name: run-tests
    
    - name: build-image
      runAfter: [run-tests]
      taskRef:
        name: build
      params:
        - name: image
          value: myregistry.azurecr.io/myapp:$(tasks.clone-repo.results.commit-sha)
    
    - name: deploy
      runAfter: [build-image]
      taskRef:
        name: deploy
      params:
        - name: environment
          value: $(params.environment)
```

### Multi-Cluster Deployment Strategy

```yaml
# Deployment task detects target cluster from parameter
- name: deploy
  taskRef:
    name: deploy
  params:
    - name: environment
      value: prod
    - name: cluster
      value: us-east-1  # Parameters specify cluster
    - name: kubeconfig-secret
      value: kubeconfig-$(params.cluster)  # Use cluster-specific kubeconfig
```

## Metrics and Monitoring

Key metrics to track:
- `tekton_pipeline_runs_total` - Total pipeline executions
- `tekton_pipeline_duration_seconds` - Time to complete pipeline
- `tekton_pipeline_success_rate` - Percentage of successful runs
- `tekton_task_duration_seconds` - Time per task (identify bottlenecks)
- `tekton_resource_usage` - CPU/memory consumed by pipelines

## Testing Pipeline Changes

**Local testing:**
```bash
# Test pipeline definition syntax
kubectl apply --dry-run=client -f tekton/pipelines/build-and-deploy.yaml

# Run pipeline in dev environment
tkn pipeline start build-and-deploy \
  --param git-url=https://github.com/myorg/myrepo \
  --param environment=dev
```

## Related Decisions

- ADR-001: Kubernetes Cost Optimization (pipelines auto-scale based on workload)
- ADR-004: Infrastructure Provisioning Self-Service (teams provision via Git + Tekton)

## References

- Tekton Documentation: https://tekton.dev/docs/
- Tekton Best Practices: https://tekton.dev/docs/pipelines/tekton-opt-in-api-fields/
- Pipeline as Code: https://cloud.google.com/architecture/devops/devops-tech-ci-cd-pipeline-as-code

## Lessons Learned

1. **Standardized directory structure is critical** - Without it, teams create different structures
2. **Parameter-driven pipelines are essential** - Allows reuse across environments
3. **Task reusability matters** - Build once, deploy many reduces duplication
4. **Version control is non-negotiable** - All changes must be auditable
5. **Cluster resource quotas are necessary** - Runaway pipelines can starve cluster
6. **Documentation must include examples** - Teams learn faster with working examples
7. **Gradual migration works better** - Migrating all services at once created chaos
