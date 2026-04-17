# ADR-004: Self-Service Infrastructure Provisioning via Terraform and Cloud Schematics

## Status
Accepted

## Context

Infrastructure provisioning was a bottleneck:
- Teams needed to request databases, monitoring stacks, or resource groups
- Requests went through ops team (backlog, delays)
- Manual provisioning error-prone (typos, inconsistent configuration)
- No standardized way to describe infrastructure
- Difficult to track infrastructure ownership and lineage
- Environment parity issues (dev/staging/prod had drift)

Common requests from teams:
- New Redis instances for caching
- New Cloudant databases for persistent storage
- Monitoring dashboards and alert configurations
- VPC resources for network isolation
- Storage buckets with specific access policies

At IBM Cloud Pipeline, we had multiple teams requesting similar resources repeatedly. Manual provisioning took 1-2 days per request.

## Decision

We implemented self-service infrastructure provisioning using Terraform modules with IBM Cloud Schematics:

### 1. Reusable Terraform Modules
Created standardized, parameterized Terraform modules for common resources:
- **Redis module:** Automatically configure size, region, backup retention
- **Cloudant module:** Set up databases, indexes, backup policies
- **Monitoring module:** Deploy monitoring agents, configure alerting
- **VPC module:** Create VPCs with configurable subnets and security groups

### 2. IBM Cloud Schematics Integration
- Schematics provides UI for non-technical teams
- Handles tfstate management (centralized, no manual management)
- Provides version control for infrastructure definitions
- Enables team collaboration on infrastructure changes
- Tracks infrastructure change history

### 3. Tfstate Management Solution
**Problem:** Sharing Terraform state files across teams was difficult
- Local state: Single person could modify, others blocked
- Shared S3/blob storage: Race conditions, state corruption risk
- No audit trail of who changed what

**Solution:** IBM Cloud Schematics manages tfstate
- Centralized state storage (Schematics backend)
- Multiple teams can request resources without state conflicts
- Built-in locking prevents concurrent modifications
- Audit trail of all infrastructure changes
- No manual state file management

### 4. Self-Service Workflow
```
1. Team defines resource requirements (CPU, memory, backup retention, etc.)
2. Team creates Schematic workspace with Terraform modules
3. Schematics previews changes (terraform plan)
4. Team reviews and approves
5. Schematics applies configuration (terraform apply)
6. Infrastructure provisioned automatically
7. Team has immediate access to resource
```

### 5. Infrastructure Standardization
All resources provisioned through modules ensure:
- Consistent naming conventions
- Standard backup policies
- Required tagging for cost tracking
- Appropriate security groups and access controls
- Monitoring and alerting configured by default

## Consequences

### Benefits
- **Self-service provisioning:** Teams don't wait for ops team
- **Reduced manual errors:** Terraform enforces consistency
- **Audit trail:** All infrastructure changes tracked
- **Scalability:** Multiple teams can provision simultaneously
- **Cost visibility:** Resources tagged automatically for cost tracking
- **Environment parity:** Staging and prod use identical module configurations
- **Reduced ops overhead:** No manual provisioning tasks
- **Faster onboarding:** New teams self-provision required resources

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Teams over-provision | Wasted resources, higher costs | Quotas, cost alerts, right-sizing reviews |
| Incorrect parameters | Misconfigured resources | Module validation, sensible defaults |
| Accidental deletion | Data loss | Snapshots, backups, require approval for deletion |
| Security misconfiguration | Exposed databases | Module enforces minimum security standards |
| State file corruption | Infrastructure drift | Schematics manages state, prevents corruption |

## Implementation Details

### Module Directory Structure

```
terraform/
├── modules/
│   ├── redis/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── README.md
│   ├── cloudant/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── README.md
│   ├── monitoring/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── vpc/
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
└── examples/
    ├── dev-environment/
    ├── staging-environment/
    └── prod-environment/
```

### Example: Redis Module

```hcl
# modules/redis/main.tf

variable "instance_name" {
  type = string
}

variable "memory_gb" {
  type    = number
  default = 1
}

variable "region" {
  type    = string
  default = "us-south"
}

variable "backup_enabled" {
  type    = bool
  default = true
}

resource "ibm_database" "redis" {
  name             = var.instance_name
  plan             = "enterprise"
  location         = var.region
  service          = "databases-for-redis"
  
  users {
    name = "admin"
  }
  
  backup {
    enabled = var.backup_enabled
  }
  
  tags = [
    "terraform",
    "team:${var.team_name}",
    "cost-center:${var.cost_center}"
  ]
}

output "connection_string" {
  value = ibm_database.redis.connection_strings[0].composed.username
}
```

### Schematics Workspace Example

Teams create a workspace in Schematics UI:
```yaml
name: my-team-redis-cache
description: Redis cache for application
repository_url: https://github.com/myorg/terraform-modules
branch: main
terraform_version: 1.5

variables:
  - key: instance_name
    value: my-app-redis
  - key: memory_gb
    value: 2
  - key: region
    value: us-south
  - key: team_name
    value: platform-engineering
  - key: cost_center
    value: CC-12345
```

### Approval Workflow

1. **Plan:** Schematics generates terraform plan
2. **Review:** Team reviews proposed changes
3. **Approve:** Team or ops approves via Schematics UI
4. **Apply:** Schematics applies configuration

### Cost Tracking Integration

All resources tagged automatically:
```hcl
tags = [
  "managed-by:terraform",
  "team:${var.team_name}",
  "cost-center:${var.cost_center}",
  "environment:${var.environment}",
  "created-via:schematics"
]
```

This enables cost allocation per team/cost-center.

## Metrics and Monitoring

Key metrics:
- `infrastructure_requests_total` - Count of self-service provisioning requests
- `infrastructure_approval_latency_seconds` - Time from request to approval
- `provisioning_success_rate` - Percentage of successful Schematics applies
- `resource_creation_latency_seconds` - Time from approval to resource ready
- `schematics_state_conflicts` - Concurrent modification conflicts (should be zero)

## Governance and Safeguards

**Built-in safeguards:**
- Resource quotas per team (prevent over-provisioning)
- Require approval for production resources
- Enforce tagging standards
- Automatic backup policies
- Default security groups restrict access

**Audit trail:**
- All changes logged to Schematics
- Git commit history of Terraform modules
- Resource change tracking in Schematics UI

## Related Decisions

- ADR-001: Kubernetes Cost Optimization (teams rightsize their infrastructure)
- ADR-003: Pipeline as Code (pipelines deploy infrastructure changes)

## References

- IBM Cloud Schematics: https://cloud.ibm.com/docs/schematics
- Terraform Modules: https://www.terraform.io/language/modules
- Best Practices for Modules: https://developer.hashicorp.com/terraform/language/modules/develop

## Lessons Learned

1. **Schematics state management is critical** - Prevents most infrastructure disaster scenarios
2. **Module standardization enables scale** - Without it, teams create incompatible configs
3. **Sensible defaults reduce errors** - Users should rarely need to override parameters
4. **Team ownership model works** - Teams feel ownership of resources they provision
5. **Cost tagging must be automatic** - Manual tagging doesn't work (incomplete/inconsistent)
6. **Approval process prevents mistakes** - Even for non-prod, review catches errors
7. **Documentation matters** - Teams need clear examples of module usage
8. **Git as source of truth** - All infrastructure defined in repos with full history
