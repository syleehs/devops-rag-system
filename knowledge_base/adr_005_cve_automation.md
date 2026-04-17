# ADR-005: Automated CVE Vulnerability Response Workflow

## Status
Accepted

## Context

Security vulnerability management was a manual, time-consuming process:

**Before automation, the workflow was:**
1. Security team (security focals) receives CVE notification
2. Security focal manually assigns CVE ticket to ops team
3. Ops team must:
   - Manually query deployed Docker images in production clusters
   - Compare image versions against CVE database (cve.org, IBM XForce, etc.)
   - Manually research which versions contain the patch
   - Manually write ticket comment with status (Fixed/Vulnerable/N/A)
   - Repeat for each cluster, each region, each image
4. Typical response time: **1-2 days per CVE**
5. Error-prone: Easy to miss affected services, use wrong versions

**Scale of the problem:**
- IBM Cloud Pipeline managed 100+ deployed microservices
- Multiple versions running across dev/staging/prod
- 10-20 CVEs published per month
- Each required full investigation and manual status update

## Decision

We automated the entire CVE response workflow to reduce manual work and response time:

### 1. Automated Docker Image Extraction

Build automation to extract deployed Docker image versions from all Kubernetes clusters:
```
For each cluster:
  - Query all running pods
  - Extract container image names and versions
  - Store in database with cluster/namespace/pod information
  - Update hourly to catch new deployments
```

### 2. CVE Database Integration

Integrate with multiple CVE sources for comprehensive coverage:
- **cve.org:** Official CVE database, patch information
- **IBM XForce:** IBM-specific threat intelligence
- **Docker Hub:** Image vulnerability scanning
- **Internal database:** Map deployed images to vulnerability status

### 3. Automated Correlation and Analysis

For each new CVE:
```
1. Extract affected component (e.g., "OpenSSL 1.0.x")
2. Query deployed images for matching versions
3. For each matching image:
   - Check CVE database for fixed version
   - Determine patch status (fixed/not fixed/N/A for our deployment)
   - Calculate impact (is this image actually vulnerable in our usage?)
```

### 4. Automated Status Update

Generate Git-based status updates for security team:
- Create pull request or push commit with CVE status
- Document findings in structured format
- List affected services/versions
- Specify remediation (update image / not affected / waiting for patch)
- Provide evidence (links to CVE, patch info, version comparisons)

### 5. Integration with Ticket System

Automated updates pushed to issue tracker:
- Comment on CVE ticket with complete analysis
- Status: `VULNERABLE`, `FIXED`, or `N/A`
- Timeline to patch (immediate/within X days/planned release)
- Affected services list

## Consequences

### Benefits
- **Automation reduces response time:** From 1-2 days to **minutes**
- **Comprehensive coverage:** No missed services or versions
- **Reduced manual error:** No typos, version mismatches, or missed clusters
- **Repeatable process:** Same methodology for every CVE
- **Audit trail:** Complete documentation of findings
- **Faster remediation:** Security team can act immediately with accurate info
- **Reduced ops overhead:** No manual investigation required
- **Compliance:** Complete audit trail for compliance audits

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| False positives | Mark service vulnerable when it's not | Manual review of edge cases, version pinning verification |
| False negatives | Miss actually vulnerable service | Regular spot checks, test with known CVEs |
| API rate limits | CVE database queries throttled | Implement caching, batch requests |
| Complex vulnerabilities | Multi-component vulnerabilities | Additional logic for dependency analysis |
| Outdated deployed image info | Analysis based on stale data | Update image inventory hourly |

## Implementation Details

### Workflow Architecture

```
┌─────────────────────────────────────────────┐
│ CVE Published (cve.org, IBM XForce, etc.)   │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ Extract CVE details                         │
│ - Affected component (e.g., OpenSSL)        │
│ - Affected versions                         │
│ - Fixed version                             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ Query deployed images in all clusters       │
│ - Search for affected component             │
│ - Identify matching image versions          │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ Determine status for each match             │
│ - Version < fixed_version? → VULNERABLE     │
│ - Version >= fixed_version? → FIXED         │
│ - Component not in image? → N/A             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ Generate report with Git commit/PR          │
│ - List affected services                    │
│ - Specify status for each                   │
│ - Link to CVE details                       │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ Post comment to CVE ticket                  │
│ - Status: VULNERABLE / FIXED / N/A          │
│ - Evidence and findings                     │
│ - Timeline to remediate                     │
└─────────────────────────────────────────────┘
```

### Example CVE Analysis Report

```markdown
# CVE-2024-1234: OpenSSL Information Disclosure

**Overall Status:** PARTIALLY VULNERABLE

## Affected Services

| Service | Image | Version | CVE Status | Action |
|---------|-------|---------|-----------|--------|
| auth-service | openssl:1.1.1 | 1.1.1v | VULNERABLE | Update to 1.1.1w |
| api-gateway | nginx:1.24 | Contains OpenSSL 1.1.1u | VULNERABLE | Update nginx |
| static-cdn | nginx:1.25 | Contains OpenSSL 3.0.8 | FIXED | No action |
| worker-service | python:3.11 | Contains OpenSSL 1.1.1t | VULNERABLE | Update Python image |

## Timeline to Fix
- **Critical (1 day):** auth-service, api-gateway
- **Standard (3 days):** worker-service  
- **Not needed:** static-cdn (already patched)

## Evidence
- [CVE-2024-1234 Details](https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2024-1234)
- [OpenSSL Advisory](https://www.openssl.org/news/secadv/)
- Fixed in OpenSSL versions: 1.1.1w, 3.0.8, 3.1.0
```

### Image Inventory Database Schema

```sql
CREATE TABLE deployed_images (
  id SERIAL PRIMARY KEY,
  cluster VARCHAR(100),           -- Cluster name
  namespace VARCHAR(100),         -- K8s namespace
  pod_name VARCHAR(255),          -- Pod name
  container_name VARCHAR(255),    -- Container name
  image_registry VARCHAR(255),    -- Registry (docker.io, etc)
  image_name VARCHAR(255),        -- Image name
  image_tag VARCHAR(100),         -- Image tag/version
  digest VARCHAR(255),            -- Image digest
  last_seen TIMESTAMP,            -- Last time image was running
  updated_at TIMESTAMP            -- Last database update
);

CREATE TABLE cve_tracking (
  id SERIAL PRIMARY KEY,
  cve_id VARCHAR(50) UNIQUE,      -- CVE-2024-1234
  component VARCHAR(255),         -- openssl, nginx, etc
  affected_versions TEXT,         -- Version range
  fixed_version VARCHAR(100),     -- First patched version
  severity VARCHAR(20),           -- CRITICAL, HIGH, MEDIUM, LOW
  published_date DATE,
  status VARCHAR(50),             -- VULNERABILITY, FIXED, REVOKED
  updated_at TIMESTAMP
);

CREATE TABLE cve_service_status (
  id SERIAL PRIMARY KEY,
  cve_id VARCHAR(50),
  service_name VARCHAR(255),
  image_version VARCHAR(100),
  status VARCHAR(50),             -- VULNERABLE, FIXED, N/A
  analyzed_at TIMESTAMP,
  UNIQUE(cve_id, service_name)
);
```

### Automation Implementation

```python
# Pseudocode for CVE automation workflow

def handle_new_cve(cve_id):
    # 1. Get CVE details
    cve_details = fetch_from_cve_database(cve_id)
    affected_component = cve_details['component']
    fixed_version = cve_details['fixed_version']
    
    # 2. Query deployed images
    deployed_images = query_all_clusters_for_image(affected_component)
    
    # 3. Determine status for each
    results = []
    for image in deployed_images:
        if image.version < fixed_version:
            status = 'VULNERABLE'
        elif image.version >= fixed_version:
            status = 'FIXED'
        else:
            status = 'N/A'
        results.append({
            'service': image.service,
            'version': image.version,
            'status': status
        })
    
    # 4. Generate report
    report = generate_markdown_report(cve_id, results)
    
    # 5. Push to Git
    commit_to_git(f'CVE/{cve_id}.md', report)
    
    # 6. Post to ticket
    post_to_ticket_system(cve_id, report)
```

## Manual Review Process

Some CVEs require manual review:
- **Complex vulnerabilities** affecting multiple dependencies
- **Edge cases** where version detection is ambiguous
- **Custom patches** applied by our team
- **Usage-specific** vulnerabilities (not applicable to our deployment)

Manual review happens after automation identifies potential vulnerability.

## Metrics and Monitoring

Key metrics:
- `cve_detection_latency_seconds` - Time from CVE publication to detection
- `cve_analysis_latency_seconds` - Time from detection to status report
- `vulnerable_services_count` - Count of services needing patching
- `false_positive_rate` - Manual review rate
- `patch_deployment_latency_days` - Time from status report to patch

## Related Decisions

- ADR-003: Pipeline as Code (image updates deployed via automated pipelines)
- ADR-001: Kubernetes Cost Optimization (secure systems are reliable systems)

## References

- NIST CVE Database: https://cve.mitre.org/
- IBM XForce: https://exchange.xforce.ibmcloud.com/
- Container Image Scanning: https://docs.docker.com/scout/

## Lessons Learned

1. **Automation is non-negotiable for security at scale** - Manual processes don't scale
2. **Multiple CVE sources needed** - No single source has all information
3. **Image version tracking is prerequisite** - Can't analyze without knowing what's deployed
4. **False positives are acceptable if rare** - Manual review catches them
5. **Git-based documentation creates audit trail** - Essential for compliance
6. **Security team feedback loop is critical** - They know edge cases ops misses
7. **Regular testing with known CVEs validates process** - Test automation quarterly
8. **Response time is competitive advantage** - Faster patching = lower risk exposure
