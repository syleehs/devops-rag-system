# ADR-010: On-Call Incident Response for SaaS CI/CD Platform

## Status
Accepted

## Context

IBM Cloud Pipeline operated as a SaaS CI/CD platform with enterprise and public users running production workloads 24/7. Platform degradation directly impacted customer pipeline executions - builds failing, deployments stalled, and CI/CD workflows blocked.

On-call rotation covered production incidents including:
- Failed deployments (daemonset updates, node upgrades, service rollouts)
- Resource limit breaches (CPU throttling, memory pressure, storage exhaustion)
- Regional outages (AZ failures, network degradation, IBM Cloud incidents)
- Performance degradation (pipeline slowdowns, queue backlogs, timeout spikes)

An on-call engineer was responsible every 5 weeks, rotating weekly through the team. The on-call engineer needed to diagnose, respond to, and resolve incidents - or escalate appropriately - at any hour.

## Decision

We established structured incident response practices with documented runbooks, escalation paths, and postmortem processes.

### 1. Incident Severity Classification

```
SEV-1: Platform-wide outage. No pipelines executing. Immediate response required.
SEV-2: Significant degradation. Subset of customers affected. Response within 15 minutes.
SEV-3: Minor degradation. Single region or feature affected. Response within 1 hour.
SEV-4: Informational. No customer impact. Address during business hours.
```

### 2. On-Call Rotation Structure

- Weekly rotation, every 5 weeks per engineer
- Handoff documentation updated at rotation change
- Runbooks maintained in shared repository
- Escalation path documented for each incident type

### 3. Common Incident Types and Response

#### Failed Deployment

**Symptoms:**
- Deployment pod stuck in CrashLoopBackOff or Pending
- Health checks failing after deployment
- Error rate spike correlated with deployment event

**Response:**
```
1. Identify which component failed (kubectl get pods -A | grep -v Running)
2. Check pod logs for error (kubectl logs <pod> --previous)
3. Determine if rollback needed or config fix sufficient
4. If rollback: revert deployment to previous version
5. If config: apply fix and redeploy
6. Validate service health after resolution
7. Document timeline and root cause
```

#### Resource Limit Breach

**Symptoms:**
- OOMKilled events in node logs
- CPU throttling alerts from Prometheus
- Storage capacity alerts (>85% usage)
- Pipeline tasks failing with resource errors

**Response:**
```
1. Identify affected nodes (kubectl describe nodes | grep -A5 "Conditions")
2. Check resource consumption (kubectl top nodes / kubectl top pods)
3. For memory: identify memory-hungry pods, evict if necessary
4. For CPU: check for runaway processes, throttle or terminate
5. For storage: identify large consumers, clean up if safe
6. If autoscaler not responding: manually trigger node addition
7. Monitor until resource levels normalize
```

#### Regional Outage

**Symptoms:**
- All pipelines in a region failing simultaneously
- Network connectivity errors in logs
- IBM Cloud status page showing regional issues

**Response:**
```
1. Check IBM Cloud status page (cloud.ibm.com/status)
2. Confirm scope: single AZ vs full region
3. If IBM Cloud incident: monitor status, inform stakeholders, wait
4. If isolated to our infrastructure:
   a. Check cluster health (kubectl get nodes)
   b. Check network connectivity between services
   c. Verify DNS resolution (CoreDNS health)
   d. Check load balancer health
5. If unable to restore: trigger failover to alternate region
6. Communicate status to customers via status page
7. Document timeline for postmortem
```

#### Performance Degradation / Slowdown

**Symptoms:**
- Pipeline execution times increasing
- Queue depth growing without corresponding throughput
- Timeout errors increasing
- P95/P99 latency spikes in Prometheus

**Response:**
```
1. Check queue depth and worker capacity
2. Identify if specific pipeline types are slow or all pipelines
3. Check worker agent health (private-worker-agent pod status)
4. Check database response times (if applicable)
5. Check for noisy neighbor issues (one customer consuming excessive resources)
6. Scale worker capacity if demand spike
7. If database: check connection pool, query performance
8. Monitor until metrics normalize
```

### 4. Diagnostic Tools

Quick commands for incident diagnosis:

```bash
# Get all non-running pods
kubectl get pods -A | grep -v "Running\|Completed"

# Check node resource usage
kubectl top nodes

# Check pod resource usage sorted by CPU
kubectl top pods -A --sort-by=cpu

# Get recent events (last 30 minutes)
kubectl get events -A --sort-by='.lastTimestamp' | tail -50

# Check logs for a crashing pod
kubectl logs <pod-name> -n <namespace> --previous

# Check node conditions
kubectl describe nodes | grep -A10 "Conditions:"

# Check daemonset status
kubectl get ds -A

# Check deployment rollout status
kubectl rollout status deployment/<name> -n <namespace>

# Check HPA status
kubectl get hpa -A
```

### 5. Escalation Path

```
On-call engineer → Team lead (if unresolved after 30 minutes)
Team lead → Engineering manager (if SEV-1 unresolved after 15 minutes)
Engineering manager → IBM Cloud support (if platform-level issue)
```

### 6. Postmortem Process

After SEV-1 and SEV-2 incidents:

1. **Timeline:** Document exact sequence of events with timestamps
2. **Root cause:** Identify the underlying cause, not just the symptom
3. **Contributing factors:** What made this worse or harder to detect
4. **Customer impact:** How many customers affected, for how long
5. **Resolution:** What fixed the immediate issue
6. **Action items:** Preventive measures with owners and deadlines
7. **Participated in by:** On-call engineer diagnosed and explained incident; team reviewed and validated

## Consequences

### Benefits
- ✅ Consistent response regardless of which engineer is on-call
- ✅ Faster resolution through documented runbooks
- ✅ Institutional knowledge captured in runbooks
- ✅ Postmortems drive systemic improvements
- ✅ SOC2 incident response documentation requirements met
- ✅ Clear escalation path reduces decision paralysis during incidents

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Runbooks become stale | Engineer follows outdated procedure | Quarterly runbook review, update after incidents |
| Novel incidents not covered | No runbook to follow | Escalation path, general diagnostic approach |
| Alert fatigue | On-call ignores alerts | Regular alert tuning, remove noisy alerts |
| Single point of failure | On-call engineer unavailable | Backup on-call designated each week |

## Monitoring and Alerting

Key alerts that triggered on-call response:

```yaml
alerts:
  - name: PlatformPipelineFailureSpike
    condition: pipeline_failure_rate > 10% over 5 minutes
    severity: SEV-2
    
  - name: NodeNotReady
    condition: node_ready == false for 5 minutes
    severity: SEV-2
    
  - name: PodCrashLooping
    condition: pod_restart_count > 5 in 10 minutes
    severity: SEV-3
    
  - name: ResourcePressureCritical
    condition: node_memory_pressure == true OR node_disk_pressure == true
    severity: SEV-2
    
  - name: RegionalLatencySpike
    condition: p95_latency > 3x baseline for 10 minutes
    severity: SEV-2
```

## Related Decisions

- ADR-002: Node Health Monitoring (proactive detection reduces incidents)
- ADR-006: Canary Deployments (reduces deployment-caused incidents)
- ADR-009: SOC2 Compliance (incident documentation requirements)

## Lessons Learned

1. **Runbooks save time under pressure** - Thinking clearly at 3am is hard; runbooks make it easier
2. **First stabilize, then investigate** - Get customers back online before finding root cause
3. **Communicate early** - Stakeholders need to know, even before you have answers
4. **Alert tuning is ongoing** - Too many alerts = ignored alerts = missed incidents
5. **Postmortems must be blameless** - Blame prevents honest root cause analysis
6. **Action items need owners** - Postmortem action items without owners never get done
7. **Novel incidents reveal runbook gaps** - Use each incident to improve documentation
