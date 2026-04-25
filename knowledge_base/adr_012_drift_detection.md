# ADR-012: CoreDNS and Infrastructure Configuration Drift Detection

## Status
Accepted

## Context

Operating Kubernetes clusters across multiple regions and environments created a configuration consistency challenge. The desired state of cluster configuration was defined in code, but actual cluster state could drift from that desired state through:

- Manual kubectl commands applied during incident response
- Partial pipeline failures leaving config in intermediate state
- Node replacements with slightly different configurations
- CoreDNS configuration changes not propagated consistently across clusters

**CoreDNS specific concerns:**
- CoreDNS is the DNS resolver for all service discovery within Kubernetes
- Misconfigured CoreDNS caused service-to-service communication failures
- Configuration inconsistencies between clusters caused hard-to-diagnose issues
- Pipeline tasks relied on DNS resolution for pulling images and communicating between services

**General configuration drift concerns:**
- Clusters that should be identical often developed subtle differences over time
- Differences caused "works in staging, fails in production" type issues
- No systematic way to detect drift before it caused customer impact
- Compliance required infrastructure to match documented configuration

## Decision

We implemented configuration drift detection that continuously compared actual cluster state against desired state, alerting on discrepancies before they caused incidents.

### 1. CoreDNS Drift Detection

Monitored CoreDNS configuration specifically:
- Compared running CoreDNS ConfigMap against source-of-truth in Git
- Detected unexpected changes to DNS resolution rules
- Alerted immediately on any CoreDNS configuration mismatch
- Validated CoreDNS pod health and query response times

### 2. General Configuration Drift Detection

Broader drift detection across cluster components:
- Identified version mismatches between clusters that should be identical
- Flagged unexpected resource additions or deletions

### 3. Automated Remediation vs. Alerting

Decision criteria for response:
- **Auto-remediate:** Known safe configurations (CoreDNS revert to Git version)
- **Alert for human review:** Unknown or potentially intentional changes
- **Never auto-remediate:** Production changes that could cause outage if wrong

### 4. Drift Detection Schedule

- CoreDNS: Continuous monitoring + periodic config comparison
- General cluster config: Hourly comparison against Terraform state
- Cross-cluster consistency: Daily comparison between clusters that should match

## Consequences

### Benefits
- ✅ Detected configuration problems before they caused customer impact
- ✅ Reduced "mystery failures" caused by undocumented config changes
- ✅ Compliance evidence that infrastructure matched documented state
- ✅ CoreDNS issues detected in minutes rather than hours
- ✅ Discouraged manual kubectl changes by making them visible
- ✅ Cross-cluster consistency improved reliability

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| False positive alerts | Alert fatigue | Careful baseline establishment, tuned thresholds |
| Auto-remediation of intentional change | Reverts desired change | Human review for ambiguous cases |
| Drift detection misses some config | False sense of security | Document scope of detection coverage |
| Terraform state lag | Drift missed between applies | Supplement with direct cluster comparison |

## Implementation Details

### CoreDNS Monitoring

```bash
#!/bin/bash
# CoreDNS drift detection

EXPECTED_CONFIGMAP=$(git show HEAD:k8s/coredns/configmap.yaml)
ACTUAL_CONFIGMAP=$(kubectl get configmap coredns -n kube-system -o yaml)

if [ "$EXPECTED_CONFIGMAP" != "$ACTUAL_CONFIGMAP" ]; then
  echo "DRIFT DETECTED: CoreDNS configuration mismatch"
  diff <(echo "$EXPECTED_CONFIGMAP") <(echo "$ACTUAL_CONFIGMAP")
  
  # Alert on-call
  send_alert "CoreDNS configuration drift detected in cluster $CLUSTER"
  
  # Log for audit
  log_drift_event "coredns" "$CLUSTER" "$(date -u)"
fi
```

### CoreDNS Health Validation

```bash
# Test DNS resolution within cluster
test_dns_resolution() {
  CLUSTER=$1
  
  # Test service discovery
  kubectl run dns-test --image=busybox --restart=Never --rm -it \
    -- nslookup kubernetes.default.svc.cluster.local
  
  # Test external resolution
  kubectl run dns-test --image=busybox --restart=Never --rm -it \
    -- nslookup google.com
  
  # Check CoreDNS pod health
  COREDNS_PODS=$(kubectl get pods -n kube-system -l k8s-app=kube-dns)
  echo "CoreDNS pods: $COREDNS_PODS"
}
```

### General Configuration Drift

```bash
#!/bin/bash
# Compare actual cluster state to Terraform state

# Get Terraform desired state
terraform show -json > /tmp/desired_state.json

# Get actual cluster state
kubectl get all -A -o json > /tmp/actual_state.json

# Compare key resources
compare_resources() {
  RESOURCE_TYPE=$1
  
  DESIRED=$(jq ".resources[] | select(.type == \"$RESOURCE_TYPE\")" /tmp/desired_state.json)
  ACTUAL=$(kubectl get $RESOURCE_TYPE -A -o json)
  
  # Find differences
  diff <(echo "$DESIRED" | jq -S .) <(echo "$ACTUAL" | jq -S .) > /tmp/drift_report.txt
  
  if [ -s /tmp/drift_report.txt ]; then
    echo "Drift detected in $RESOURCE_TYPE:"
    cat /tmp/drift_report.txt
    send_alert "Configuration drift in $RESOURCE_TYPE on cluster $CLUSTER"
  fi
}

compare_resources "kubernetes_config_map"
compare_resources "kubernetes_deployment"
compare_resources "kubernetes_daemonset"
```

### Prometheus Metrics for CoreDNS

```yaml
# Prometheus alerts for CoreDNS health
groups:
  - name: coredns
    rules:
      - alert: CoreDNSDown
        expr: absent(up{job="coredns"} == 1)
        for: 5m
        severity: critical
        
      - alert: CoreDNSLatencyHigh
        expr: histogram_quantile(0.99, rate(coredns_dns_request_duration_seconds_bucket[5m])) > 0.1
        for: 10m
        severity: warning
        
      - alert: CoreDNSErrorsHigh
        expr: rate(coredns_dns_responses_total{rcode="SERVFAIL"}[5m]) > 0.01
        for: 5m
        severity: critical
        
      - alert: CoreDNSConfigDrift
        expr: coredns_config_hash != on(cluster) group_left() expected_coredns_config_hash
        for: 1m
        severity: critical
```

### Cross-Cluster Consistency Check

```bash
#!/bin/bash
# Compare configuration across clusters that should be identical

CLUSTERS=("us-south-prod" "eu-gb-prod" "ap-north-prod")
REFERENCE_CLUSTER=${CLUSTERS[0]}

# Get reference configuration
REFERENCE_CONFIG=$(kubectl --context=$REFERENCE_CLUSTER get configmap -A -o json)

for CLUSTER in "${CLUSTERS[@]:1}"; do
  CLUSTER_CONFIG=$(kubectl --context=$CLUSTER get configmap -A -o json)
  
  DIFF=$(diff <(echo "$REFERENCE_CONFIG" | jq -S .) <(echo "$CLUSTER_CONFIG" | jq -S .))
  
  if [ -n "$DIFF" ]; then
    echo "Inconsistency between $REFERENCE_CLUSTER and $CLUSTER:"
    echo "$DIFF"
    send_alert "Cross-cluster configuration inconsistency: $REFERENCE_CLUSTER vs $CLUSTER"
  fi
done
```

## Alert Response Runbook

### CoreDNS Drift Alert

```
1. Identify what changed: kubectl get configmap coredns -n kube-system -o yaml
2. Compare to expected: git show HEAD:k8s/coredns/configmap.yaml
3. Determine if change was intentional (check recent PRs and deployments)
4. If unintentional: revert to expected configuration
   kubectl apply -f k8s/coredns/configmap.yaml
   kubectl rollout restart deployment/coredns -n kube-system
5. If intentional but not in Git: create PR to document the change
6. Validate DNS resolution after remediation
7. Document in incident log
```

### General Drift Alert

```
1. Review drift report to understand what changed
2. Check recent deployments and manual changes
3. If unintentional: apply Terraform to restore desired state
   terraform apply -target=<drifted_resource>
4. If intentional: update Terraform to codify the change
5. Document root cause and prevent recurrence
```

## Monitoring Dashboard

Key metrics to display:
- Configuration drift events per cluster per day
- CoreDNS query success rate
- CoreDNS response latency (P50, P95, P99)
- Time to detect and resolve drift events
- Cross-cluster consistency score

## Related Decisions

- ADR-002: Node Health Monitoring (related monitoring approach)
- ADR-004: Self-Service Infrastructure (IaC prevents drift)
- ADR-009: SOC2 Compliance (drift detection supports compliance)
- ADR-003: Pipeline as Code (pipeline changes tracked in Git)

## Lessons Learned

1. **Drift happens even with good IaC discipline** - Incident response pressure leads to manual changes
2. **CoreDNS is blast radius amplifier** - DNS failures affect everything; detect early
3. **Make drift visible, not just alertable** - Dashboard showing drift trends changes team behavior
4. **Document scope of detection** - Teams need to know what drift detection does and doesn't cover
5. **Auto-remediation requires high confidence** - Wrong auto-remediation is worse than no remediation
6. **Cross-cluster consistency check finds subtle bugs** - Clusters that should be identical rarely are
7. **Drift detection discourages manual changes** - Knowing changes will be detected encourages proper process
