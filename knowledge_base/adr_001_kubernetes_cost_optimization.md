# ADR-001: Kubernetes Cost Optimization through VPC Gen2 Migration and Auto-Scaling

## Status
Accepted

## Context

Running Kubernetes on bare-metal infrastructure resulted in:
- Static resource allocation with no elasticity
- Inability to scale clusters based on demand
- Unused capacity during off-peak hours
- Manual intervention required for peak usage periods
- Difficult to rightsize resources across multiple regions

At IBM Cloud Pipeline, we managed 3 environments (dev, staging, production) across multiple regions with highly variable workload patterns. Peak usage periods (e.g., release cycles, customer demos) required manual cluster scaling, while off-peak hours left infrastructure underutilized.

## Decision

We migrated from bare-metal Kubernetes infrastructure to VPC Gen2 with the following cost optimization strategy:

### 1. VPC Gen2 Migration
- Transitioned all 3 environments to IBM Cloud VPC Gen2
- Enabled native Kubernetes cluster autoscaling
- Leveraged cloud-native networking and storage

### 2. Usage-Based Auto-Scaling
- Implemented Kubernetes Cluster Autoscaler for dynamic node provisioning
- Configured Horizontal Pod Autoscaler (HPA) based on CPU and memory metrics
- Nodes scale down automatically during low-demand periods

### 3. Timed Pre-Scaling for Peak Usage
- Analyzed historical usage patterns to identify peak periods
- Implemented Kubernetes CronJobs to pre-scale clusters during known high-demand windows
- Reduced cold-start latency during critical periods (customer demos, release cycles)

### 4. Regional Resource Rightsizing
- Analyzed per-region resource utilization
- Identified over-provisioned regions and right-sized instance types
- Reduced instance type in less-utilized regions without impacting performance
- Matched instance sizing to actual workload requirements per region

## Consequences

### Benefits
- Estimated 40-50% reduction in infrastructure costs through elasticity and rightsizing
- Zero manual scaling intervention required (fully automated)
- Improved reliability during peak usage (no more capacity constraints)
- Better resource utilization across all regions (70%+ vs. previous 40%)
- Faster time-to-scale during unexpected traffic spikes

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Cold start latency on new nodes | Brief delay during scale-up | Pre-scaling during known peak times |
| Aggressive scale-down | Sudden termination of underutilized nodes | Pod Disruption Budgets, graceful shutdown periods |
| Per-region complexity | Harder to manage different configs | Infrastructure-as-code (Terraform) templates per region |
| Autoscaling thrashing | Rapid scale up/down cycles | Conservative scaling thresholds, scale-down delay |

## Implementation Details

### Auto-Scaling Configuration

```yaml
# Example: Cluster Autoscaler settings
- min_nodes_per_zone: 2
- max_nodes_per_zone: 10
- scale_down_enabled: true
- scale_down_delay_after_add: 10m
- scale_down_unneeded_time: 10m
```

### Timed Pre-Scaling Example

```yaml
# CronJob for pre-scaling during peak hours (9 AM - 6 PM weekdays)
schedule: "0 9 * * 1-5"  # Every weekday at 9 AM
desired_nodes: 8
---
schedule: "0 18 * * 1-5"  # Every weekday at 6 PM (scale down)
desired_nodes: 3
```

### Regional Rightsizing Decisions

- **High-traffic region (US-EAST):** 4-CPU instances → maintained
- **Medium-traffic region (EU-WEST):** 4-CPU instances → downsized to 2-CPU
- **Low-traffic region (AP-SOUTH):** 4-CPU instances → downsized to 1-CPU
- **Development environments:** All downsized to 1-CPU with manual scaling

## Monitoring and Alerting

Key metrics to track cost optimization:
- `cluster_nodes_total` - Track actual node count over time
- `node_utilization_percentage` - Ensure scaling thresholds are appropriate
- `infrastructure_cost_hourly` - Monitor cost trends
- `scale_up_latency_seconds` - Ensure scale-up performance is acceptable
- `scale_down_events_total` - Monitor for thrashing behavior

Alert on:
- Node utilization consistently > 90% (indicate under-provisioning)
- Frequent scale-up/down cycles in short time windows (thrashing)
- Cost spike > 20% month-over-month without usage increase

## Related Decisions

- ADR-002: Node Health Monitoring (detects nodes that can't accept workloads)
- ADR-003: Infrastructure Provisioning Self-Service (enables teams to create VPC resources)

## References

- Kubernetes Cluster Autoscaler: https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler
- HPA Best Practices: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- IBM VPC Documentation: https://cloud.ibm.com/docs/vpc

## Lessons Learned

1. **Pre-scaling is critical** - Reactive scaling alone caused latency issues during peak periods
2. **Per-region optimization matters** - One-size-fits-all doesn't work across regions
3. **Conservative thresholds prevent thrashing** - Aggressive scaling configs caused rapid scale up/down
4. **Graceful shutdown is essential** - Without Pod Disruption Budgets, scale-down caused connection resets
5. **Cost visibility drives decisions** - Once teams could see per-region costs, they became advocates for rightsizing
