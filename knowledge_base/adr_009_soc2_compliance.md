# ADR-009: SOC2 Compliance Operations for Production SaaS Infrastructure

## Status
Accepted

## Context

IBM Cloud Pipeline operated as a SaaS CI/CD platform serving enterprise customers including banks and financial institutions. These customers required SOC2 compliance assurance as a condition of using the platform.

SOC2 compliance requires demonstrating that systems meet Trust Services Criteria across:
- **Security:** Protection against unauthorized access
- **Availability:** System is available as committed
- **Confidentiality:** Information designated as confidential is protected
- **Processing Integrity:** System processing is complete and accurate

Compliance was not a one-time certification - it required continuous operational discipline:
- Regular vulnerability remediation (CVEs)
- Timely security patching
- Access control enforcement
- Audit trail maintenance
- Incident response documentation
- Change management records

The challenge was maintaining compliance without it becoming purely manual overhead that slowed the team down.

## Decision

We embedded SOC2 compliance requirements directly into operational automation rather than treating compliance as a separate manual process.

### 1. CVE Remediation Automation

Security vulnerabilities (CVEs) represented a significant compliance requirement. We automated the entire identification and tracking workflow:
- Automated Docker image version extraction from production clusters
- Automated CVE database correlation
- Git-based status tracking with timestamps
- Reduced identification time from days to minutes

See ADR-005 for full CVE automation details.

### 2. Automated Security Patching

Node-level security patches deployed through automated daemonset update strategy:
- Patch deployment triggered on new Kubernetes version availability
- OnDelete update strategy ensured controlled, validated rollout
- Deployment time reduced from 3 days to under 3 hours
- Full audit trail of which nodes received which patches and when

### 3. Secret Rotation Policy

Credentials rotated on compliance-driven schedule:
- Automated rotation scripts eliminated manual rotation risk
- Multi-region rotation ensured no region left with expired credentials
- Automatic audit trail written to Git on every rotation
- Service restarts triggered automatically to pick up new credentials

See ADR-008 for full secret rotation details.

### 4. Access Control Enforcement

Infrastructure access controlled through:
- Hashicorp Vault for secrets management and access policies
- IBM Secrets Manager for cloud resource credentials
- IAM policies enforcing least-privilege access
- Terraform-managed access control (changes auditable via Git)

### 5. Change Management via Git

All infrastructure changes made through version-controlled code:
- Terraform changes required pull request review before apply
- Pipeline changes reviewed via Tekton pipeline-as-code PRs
- Automatic Git history provided complete change audit trail
- No manual infrastructure changes outside of IaC

### 6. Incident Response Documentation

On-call rotation participated in postmortems:
- Incident timeline documented after each significant event
- Root cause analysis recorded
- Remediation actions tracked to completion
- Recurring issues identified and addressed systematically

### 7. Monitoring and Alerting Standards

Prometheus-based monitoring provided continuous visibility:
- Alerting on security-relevant events (auth failures, unusual access patterns)
- Configuration drift detection to identify unauthorized changes
- Capacity monitoring to maintain availability commitments
- All monitoring infrastructure defined in Terraform (auditable)

## Consequences

### Benefits
- ✅ Compliance maintained continuously, not just at audit time
- ✅ Automation reduces human error in compliance-critical processes
- ✅ Git history provides automatic audit trail for most changes
- ✅ Reduced compliance overhead on engineering team
- ✅ Faster CVE remediation improves security posture
- ✅ Consistent process execution regardless of which engineer is on duty

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Automation gaps | Manual processes fall through cracks | Regular compliance review checklist |
| Audit trail gaps | Missing evidence for auditors | Automated record-keeping in Git |
| Access creep | Permissions expand over time | Regular access review, IaC-enforced policies |
| Patch delays | CVEs unaddressed past SLA | Automated tracking, escalation alerts |

## Compliance Controls by Category

### Security Controls
- ✅ CVE identification and tracking automated
- ✅ Security patching automated with audit trail
- ✅ Secrets management via Vault and IBM SM
- ✅ Least-privilege access via IAM and Vault policies
- ✅ All access changes via reviewed Terraform PRs

### Availability Controls
- ✅ Multi-region deployment with cross-region failover
- ✅ Canary deployments minimize deployment-related downtime
- ✅ Automated node health monitoring detects issues proactively
- ✅ On-call rotation ensures 24/7 incident response coverage
- ✅ Disaster recovery procedures documented and tested

### Confidentiality Controls
- ✅ Secrets never stored in code (Vault and SM only)
- ✅ Credential rotation on regular schedule
- ✅ Access to production credentials restricted by Vault policies
- ✅ Audit log of all secret access events

### Processing Integrity Controls
- ✅ Pipeline execution logs retained
- ✅ Deployment verification checks before traffic routing
- ✅ Health checks validate service integrity post-deployment
- ✅ Change management via pull request review process

## Audit Evidence Sources

For each compliance control, evidence was available from:

| Control | Evidence Source |
|---------|----------------|
| CVE remediation | Git commit history of CVE status updates |
| Security patching | Deployment logs, Git history of node updates |
| Secret rotation | Automated Git commits per rotation event |
| Access control | Terraform state, Vault audit logs |
| Change management | Git pull request history |
| Incident response | Postmortem documents, on-call logs |
| Monitoring | Prometheus metrics, alert history |

## Related Decisions

- ADR-005: CVE Automation (security control implementation)
- ADR-008: Secret Rotation (confidentiality control implementation)
- ADR-007: Daemonset OnDelete Updates (availability and security patching)
- ADR-004: Self-Service Infrastructure (change management via IaC)
- ADR-003: Pipeline as Code (change management audit trail)

## Lessons Learned

1. **Compliance through automation scales; compliance through process doesn't** - Manual compliance processes break down under operational pressure
2. **Git is your audit trail** - When everything is code, history is automatic
3. **Embed compliance in normal workflow** - Compliance as a separate activity creates overhead and gaps
4. **Automate the evidence collection** - Auditors need evidence; automation produces it consistently
5. **CVE SLAs must be tracked** - Without automated tracking, CVEs slip past deadlines
6. **Access reviews must be scheduled** - Permissions creep without regular review cycles
7. **Postmortems are compliance artifacts** - Incident documentation serves both operational and compliance purposes
