# ADR-001: Kubernetes Cost Optimization Strategy

## Status
Accepted

## Context

Teams running Kubernetes often experience unexpectedly high cloud bills due to:
- Over-provisioned resource requests (padding for safety)
- Unused reserved capacity in underutilized clusters
- Lack of visibility into per-pod/per-namespace costs
- No automated right-sizing mechanisms

At IBM Cloud Pipeline, we were spending ~$45K/month on Kubernetes infrastructure with only 40% average utilization.

## Decision

We will implement a three-tiered approach to Kubernetes cost optimization:

### Tier 1: Resource Right-Sizing (Immediate - 20-25% savings)
- Implement resource quotas and limits based on actual usage patterns
- Reduce default CPU requests from 500m to 200m for non-critical workloads
- Use HPA (Horizontal Pod Autoscaling) based on actual metrics, not static over-provisioning
- Implement VPA (Vertical Pod Autoscaler) in recommendation-only mode

### Tier 2: Node Optimization (Medium-term - 25-30% savings)
- Switch from on-demand EC2 nodes to spot instances for non-critical workloads
- Implement cluster autoscaler with node consolidation
- Use Reserved Instances for baseline capacity (60% of average usage)
- Implement pod disruption budgets to safely migrate pods on spot termination

### Tier 3: Observability & Governance (Ongoing - 15-20% savings)
- Deploy Kubecost for per-pod/per-namespace cost visibility
- Set chargeback model: teams see their resource costs
- Implement admission controllers to prevent over-provisioning
- Monthly cost reviews with threshold-based alerts

## Consequences

### Benefits
- Estimated 50-60% total cost reduction (~$22K/month savings at IBM scale)
- Improved cluster utilization from 40% to 70%+
- Better visibility into where money is being spent
- Cost becomes a visible metric driving engineering behavior
- Fewer underutilized nodes to manage

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Spot instance interruptions | Application downtime | Pod disruption budgets, multi-zone spread |
| Aggressive right-sizing | Out-of-memory errors | Conservative first phase, gradual tuning |
| Team resistance | Slow adoption | Training, per-team dashboards, incentives |
| Complexity increase | Operational burden | Automation first, simple alerting |

## Technical Details

### Resource Request Tuning Formula

```
Request = (Observed P99 usage * 1.2) + buffer
where buffer = 10% for stable services, 25% for variable services
```

### Example: Right-Sizing a Node Pool

Before:
- 10 nodes × 4 CPUs × $0.10/hr = $40/hr (underutilized)
- Average usage: 40%

After:
- 6 nodes × 4 CPUs × $0.04/hr (spot) = $9.60/hr
- 2 reserved instances × 4 CPUs × $0.06/hr = $0.48/hr
- Total: $10.08/hr (75% cost reduction)

### Monitoring & Alerting

Key metrics to track:
- Pod/namespace costs: `cost_per_pod_usd`
- Node utilization: `node_cpu_utilization`, `node_memory_utilization`
- Cluster efficiency: `useful_cost / total_cost`
- Spot savings: `savings_from_spot_instances_usd`

Alert on:
- Namespace cost spike > 20% month-over-month
- Single pod requesting >2 CPUs (unusual)
- Node utilization < 30% (candidate for consolidation)
- Spot termination rate > 5% (check availability zone distribution)

## Related Decisions

- ADR-002: Incident Response Automation (uses similar resource tagging)
- ADR-003: Multi-tenancy Model (enforces quotas per team)

## Implementation Timeline

- **Week 1-2:** Deploy Kubecost, baseline measurements, team training
- **Week 3-4:** Implement resource quotas and HPA tuning (Tier 1)
- **Week 5-8:** Spot instance strategy, node consolidation (Tier 2)
- **Week 9+:** Admission controllers, continuous optimization (Tier 3)

## References

- Kubecost: https://www.kubecost.com/kubernetes-cost-monitoring/
- VPA: https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler
- Karpenter: https://karpenter.sh/ (alternative to Cluster Autoscaler)
- AWS Spot Best Practices: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-best-practices.html
