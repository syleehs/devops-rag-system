# ADR-006: Canary Deployment Strategy Across Global Availability Zones

## Status
Accepted

## Context

Deploying critical infrastructure components across a global SaaS CI/CD platform serving enterprise and public users required a strategy that minimized risk while maintaining deployment velocity.

Key components requiring careful deployment:
- **Private Worker Agent:** Manages pipeline task execution
- **Kata-Deploy:** Creates lightweight VM isolation for pipeline tasks
- **IKS Nodes (IBM Kubernetes Service):** Core cluster nodes running workloads

Before canary deployments were mature, updates were applied broadly across all regions simultaneously. This created risk of widespread outages if a deployment introduced a regression. A single bad deployment could affect all customers globally at once.

Additional challenges:
- Multiple AZs across different geographic regions with varying traffic patterns
- Different usage peaks per region (business hours differ globally)
- No automated rollback mechanism for failed deployments
- Manual progression between deployment stages

## Decision

We adopted and matured a canary deployment strategy that rolled changes iteratively through availability zones, starting with lower-traffic regions and progressing toward highest-usage AZs.

### 1. AZ-by-AZ Deployment Progression

Deployments rolled out one AZ at a time:
- Begin with lowest-traffic AZ
- Validate stability before progressing
- Hold a nearby subregion on the old version as a fallback reference
- Progress through AZs until reaching the highest-usage region last

### 2. One Deployment at a Time

Only one component deployment proceeded at a time:
- Prevents compounding failures from multiple simultaneous changes
- Isolates the cause of any regression to a single change
- Provides clear rollback target if issues emerge

### 3. Automated Fallbacks

Added automated fallback mechanisms:
- If a deployment failed health checks in an AZ, it automatically rolled back to the previous version
- Fallback triggered on failed pod readiness, increased error rates, or timeout thresholds
- Nearby subregion kept on old version served as live fallback during progression

### 4. Deployment Speed Optimization

As confidence in the strategy grew:
- Reduced wait time between AZ progressions after establishing stable health check windows
- Parallelized independent deployments where safe to do so
- Optimized health check duration to minimum reliable window

### 5. Progression Criteria

Before advancing to the next AZ:
- All pods in current AZ passing readiness probes
- No spike in error rates from affected services
- Pipeline task execution rates stable
- No customer-facing degradation signals

## Consequences

### Benefits
- ✅ Reduced blast radius of bad deployments from global to single AZ
- ✅ Automated rollback eliminated manual intervention for most failures
- ✅ Deployment confidence increased - teams willing to ship more frequently
- ✅ Clear audit trail of which AZ received which version at what time
- ✅ Faster identification of environment-specific issues
- ✅ Maintained live fallback subregion reduced customer impact during issues

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Slower full deployment | Changes take longer to reach all regions | Acceptable tradeoff for safety |
| Version skew between AZs | Temporary incompatibility during rollout | Short rollout windows, backward compatible changes |
| Health check false positives | Premature rollback of good deployments | Tuned thresholds based on historical baselines |
| Automation complexity | More complex deployment orchestration | Well-documented runbooks, tested fallback paths |

## Implementation Details

### Deployment Order (Example)

```
1. ap-south (lowest traffic)    → validate → proceed
2. eu-west (medium traffic)     → validate → proceed
3. us-east (highest traffic)    → validate → complete
   [us-central held on old version as fallback during progression]
```

### Health Check Window Per AZ

```yaml
health_check:
  readiness_timeout: 5m
  error_rate_threshold: 0.1%   # above baseline triggers rollback
  observation_window: 10m       # stable window before progression
  rollback_on_failure: true
```

### Rollback Trigger Conditions

```
- Pod readiness probe failures > 10% of replicas
- Error rate increase > 0.1% above baseline
- Pipeline task execution rate drop > 5%
- Manual trigger from on-call engineer
```

## Monitoring During Canary

Key metrics to watch during rollout:
- Pod readiness percentage per AZ
- Pipeline task success rate
- Error rate per service per AZ
- Customer-facing latency percentiles (P50, P95, P99)
- Rollback event count

## Related Decisions

- ADR-002: Node Health Monitoring (detects node-level issues during deployment)
- ADR-007: Daemonset OnDelete Autoscaling (deployment mechanism for daemonset components)
- ADR-008: Secret Rotation Automation (secrets rotated after deployment)

## Lessons Learned

1. **Start with lowest traffic AZ** - Minimizes customer impact for initial validation
2. **Keep a fallback subregion** - Having a live reference on old version is invaluable
3. **One change at a time** - Compounding deployments make root cause analysis impossible
4. **Automate rollback first** - Manual rollback under pressure is error-prone
5. **Tune health check windows carefully** - Too short causes false positives, too long slows deployments
6. **Deployment speed can increase over time** - As confidence grows, safely reduce observation windows
