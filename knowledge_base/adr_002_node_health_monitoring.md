# ADR-002: Proactive Node Health Monitoring via Log-Based Anomaly Detection

## Status
Accepted

## Context

Kubernetes cluster reliability depends on healthy nodes. However, node failures were often discovered reactively:
- Applications would fail before the node problem was detected
- Manual investigation required accessing node logs
- Time-to-detection measured in hours (when users reported issues)
- Common node issues went unnoticed until they caused production incidents

Kubernetes node status (Ready/NotReady) doesn't capture all unhealthy states:
- Nodes marked "Ready" but experiencing high memory pressure
- Nodes with disk space issues but still accepting pods
- Nodes with frequent OOMKilled events (out of memory)
- Nodes with daemonset failures indicating systemic problems
- Nodes with network connectivity issues

At IBM Cloud Pipeline, we needed visibility into node health beyond the native Kubernetes status checks.

## Decision

We implemented a proactive node health monitoring system using log-based anomaly detection:

### 1. Log Pattern Analysis Strategy
- Continuously parse node logs (`/var/log/messages`, container runtime logs)
- Identify error patterns that deviate from healthy baseline
- Detect common failure modes before they impact workloads

### 2. Unhealthy Pattern Detection
Patterns indicating node problems:
- **OOMKilled events:** Indicates insufficient memory, pods being evicted
- **Disk space errors:** "No space left on device" or similar messages
- **Daemonset failures:** kubelet failures, container runtime errors, network plugin failures
- **Connection errors:** Network connectivity issues, DNS resolution failures
- **Security errors:** SELinux violations, AppArmor denials
- **Timeout patterns:** Hung processes, slow I/O, resource contention

### 3. Baseline Comparison
- Established baseline of healthy node logs
- Captured typical kernel messages, normal daemonset operations
- Created allowlist of expected errors that don't indicate node problems

### 4. Anomaly Detection Logic
```
If error_pattern NOT IN expected_patterns AND error_count > threshold:
    Mark node as potentially unhealthy
    Trigger alert
    Create metrics for investigation
```

### 5. Automated Response
- Alert sent to ops team immediately
- Node cordoned (no new pods scheduled)
- Existing pods evicted gracefully
- Node drained and replaced by autoscaler

## Consequences

### Benefits
- **Proactive detection:** Node problems detected within minutes of occurrence
- **Reduced MTTR (Mean Time To Recovery):** Automated response replaces failed nodes
- **Improved reliability:** Problems fixed before affecting applications
- **Operational visibility:** Clear understanding of node health across cluster
- **Self-healing:** Unhealthy nodes automatically replaced

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| False positives | Healthy nodes marked unhealthy | Conservative thresholds, allowlist of expected errors |
| Log parsing overhead | CPU usage for log analysis | Implement on separate monitoring nodes, use efficient parsers |
| Missing novel failures | New error types go undetected | Regular review of logs, customer feedback loop |
| Cordon cascades | Cordoning multiple nodes affects workload | Pod Disruption Budgets, cluster size sufficient for failures |

## Implementation Details

### Log Sources Monitored
```
Node logs:
- /var/log/messages (system logs)
- /var/log/kubelet.log (kubelet logs)
- Container runtime logs (/var/log/containers/*)
- Kernel logs (dmesg)

Key search patterns:
- "OOMKilled"
- "No space left on device"
- "Error.*daemonset"
- "Connection refused" / "Connection timeout"
- "Disk pressure" / "Memory pressure"
- Failed restart patterns (kubelet crashed, runtime crashed)
```

### Example Detection Rules

```yaml
# Rule 1: OOMKilled detection
pattern: "OOMKilled"
threshold: 3 occurrences in 5 minutes
action: Mark node unhealthy, trigger alert

# Rule 2: Disk space detection
pattern: "No space left on device"
threshold: 1 occurrence
action: Immediately mark node unhealthy

# Rule 3: Daemonset failure detection
pattern: "Error.*daemonset|Failed to.*daemonset"
threshold: 5 occurrences in 10 minutes
action: Mark node unhealthy

# Rule 4: Kubelet restart detection
pattern: "kubelet.*started|kubelet.*exited"
threshold: 3 restarts in 30 minutes
action: Mark node unhealthy
```

### Healthy Baseline Examples
```
Expected patterns (should NOT trigger alerts):
- "kube-proxy: Successfully created iptables rules"
- "containerd: Cleanup completed"
- "kubelet: Pod added to desired state machine"
- "systemd: Starting Kubernetes Kubelet..."
- Normal kernel messages (no errors)
```

## Metrics and Monitoring

Key metrics to expose:
- `node_health_check_latency_seconds` - Time from problem occurrence to detection
- `unhealthy_nodes_detected_total` - Count of nodes marked unhealthy
- `false_positive_rate` - Percentage of alerts that were false positives
- `node_recovery_time_seconds` - Time from unhealthy detection to node replacement
- `error_pattern_frequency` - Track which error patterns are most common

## Alerting Strategy

Alert severities:
- **CRITICAL:** Disk full, OOMKilled events, kubelet crashes
- **WARNING:** Memory pressure, disk pressure, daemonset failures
- **INFO:** Monitoring detected anomaly, investigating

Alert destinations:
- Ops team Slack channel
- PagerDuty (for critical)
- Dashboard for historical analysis

## Related Decisions

- ADR-001: Kubernetes Cost Optimization (auto-scaling replaces unhealthy nodes)
- ADR-004: Infrastructure Provisioning Self-Service (teams need to understand node health)

## References

- Kubernetes Node Conditions: https://kubernetes.io/docs/concepts/nodes/node/#condition
- Kubelet Logging: https://kubernetes.io/docs/tasks/debug/debug-cluster/useful-kubelet-commands/
- Node Troubleshooting: https://kubernetes.io/docs/tasks/debug/debug-cluster/

## Lessons Learned

1. **Baseline is critical** - Without understanding healthy logs, false positives are unavoidable
2. **Multiple error sources matter** - Only checking Kubernetes status misses many node problems
3. **Response automation is essential** - Manual investigation takes too long; auto-cordon + auto-drain saves MTTR
4. **Threshold tuning is iterative** - Initially too sensitive, had to gradually refine based on real-world patterns
5. **Daemonset health is a leading indicator** - Daemonset failures often predict node-level issues
6. **Not all errors are equal** - Disk full is critical; expected benign messages need allowlisting
