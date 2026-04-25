# ADR-007: Daemonset OnDelete Update Strategy for Live Kubernetes Updates

## Status
Accepted

## Context

Critical infrastructure components at IBM Cloud Pipeline were deployed as Kubernetes DaemonSets. DaemonSets run one pod per node, making updates particularly sensitive - a bad update could simultaneously affect every node in a cluster.

Key DaemonSet components:
- **Kata-Deploy:** Deploys Kata Containers runtime on nodes, creating lightweight VM isolation for pipeline tasks
- **Node agents:** Monitoring and operational agents running on every node

Default Kubernetes DaemonSet update strategy (RollingUpdate) presented challenges:
- Rolling updates proceed automatically without validation gates
- Difficult to control pace of updates across nodes
- No natural checkpoint to validate stability before proceeding
- Kata runtime updates could disrupt active pipeline tasks on nodes

The team needed a way to update DaemonSets safely on a live production cluster without disrupting running workloads.

## Decision

We adopted the **OnDelete update strategy** for critical DaemonSet components, combined with controlled node draining to manage update progression safely.

### 1. OnDelete Update Strategy

```yaml
spec:
  updateStrategy:
    type: OnDelete
```

With OnDelete:
- Kubernetes does NOT automatically update pods when the DaemonSet spec changes
- Pods only update when manually deleted
- Gives complete control over update progression
- Each node can be updated individually with validation between nodes

### 2. Controlled Update Progression

Update process per node:
1. Cordon node (prevent new workloads from scheduling)
2. Drain node (gracefully evict existing workloads)
3. Delete DaemonSet pod on node (triggers update to new version)
4. Validate new pod is running and healthy
5. Uncordon node (allow workloads to resume)
6. Proceed to next node

### 3. Integration with Canary Strategy

DaemonSet updates integrated with AZ-level canary strategy:
- Complete all nodes in lowest-traffic AZ first
- Validate AZ stability before moving to next AZ
- Maintain previous version on fallback subregion nodes

### 4. Autoscaling Awareness

Before draining nodes:
- Verify cluster autoscaler can provision replacement capacity
- Ensure workloads evicted from drained node have somewhere to schedule
- Monitor cluster resource headroom throughout update

### 5. Kata-Specific Considerations

Kata Containers runtime updates required additional care:
- Active pipeline tasks use Kata runtime for VM isolation
- Draining node gracefully completes or migrates active tasks
- New Kata version validated with test pipeline task before proceeding

## Consequences

### Benefits
- ✅ Complete control over update pace
- ✅ Natural validation checkpoint between each node
- ✅ No automatic progression - human or automation decides when to proceed
- ✅ Minimal disruption to active workloads
- ✅ Easy rollback - simply delete pods on remaining nodes to revert
- ✅ Works safely on live production clusters

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Slower updates | Takes longer to update all nodes | Acceptable for safety-critical components |
| Version skew between nodes | Temporary mixed versions during update | Backward compatible changes, short update windows |
| Manual process risk | Human error in update sequence | Automation scripts, runbooks |
| Node drain disrupts workloads | Active tasks evicted | Graceful drain, adequate cluster capacity |

## Implementation Details

### DaemonSet Configuration

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: kata-deploy
spec:
  updateStrategy:
    type: OnDelete    # Manual control over updates
  selector:
    matchLabels:
      app: kata-deploy
  template:
    spec:
      tolerations:
        - key: node-role.kubernetes.io/master
          effect: NoSchedule
      containers:
        - name: kata-deploy
          image: kata-containers/kata-deploy:latest
```

### Update Script (Pseudocode)

```bash
#!/bin/bash
# Safe DaemonSet update with OnDelete strategy

DAEMONSET="kata-deploy"
NAMESPACE="kube-system"

for NODE in $(kubectl get nodes -o name); do
  echo "Updating $NODE..."
  
  # Cordon node
  kubectl cordon $NODE
  
  # Drain node gracefully
  kubectl drain $NODE --ignore-daemonsets --delete-emptydir-data --grace-period=60
  
  # Delete DaemonSet pod to trigger update
  POD=$(kubectl get pod -n $NAMESPACE -o name --field-selector spec.nodeName=$NODE | grep $DAEMONSET)
  kubectl delete $POD -n $NAMESPACE
  
  # Wait for new pod to be ready
  kubectl wait --for=condition=ready pod -l app=$DAEMONSET \
    -n $NAMESPACE --field-selector spec.nodeName=$NODE --timeout=300s
  
  # Validate
  echo "Validating $NODE..."
  sleep 60  # Observation window
  
  # Check error rates here (integrate with monitoring)
  
  # Uncordon node
  kubectl uncordon $NODE
  
  echo "$NODE updated successfully"
done
```

### Validation Checks Per Node

```
- DaemonSet pod status: Running
- Pod readiness probe: Passing
- Kata runtime responding to test task
- No error spike in node logs
- Node accepting new workload scheduling
```

## Monitoring During Updates

Key metrics:
- DaemonSet pod version per node (`kubectl get ds -o wide`)
- Node readiness status
- Active pipeline task count per node
- Kata runtime error rate
- Cluster capacity headroom

## Rollback Procedure

If issues detected on a node:
```bash
# Revert DaemonSet to previous version
kubectl set image daemonset/kata-deploy kata-deploy=kata-containers/kata-deploy:previous-version

# Delete pod on affected node to trigger revert
kubectl delete pod -n kube-system <kata-pod-name>

# Uncordon node after validation
kubectl uncordon <node-name>
```

## Related Decisions

- ADR-006: Canary Deployment Strategy (AZ-level progression)
- ADR-002: Node Health Monitoring (validates node health during updates)
- ADR-001: Kubernetes Cost Optimization (autoscaling provides capacity during drains)

## Lessons Learned

1. **OnDelete gives control that RollingUpdate cannot** - For critical DaemonSets, manual control is worth the overhead
2. **Automate the per-node sequence** - Manual steps at scale are error-prone
3. **Observation window is critical** - Rushing between nodes misses delayed failures
4. **Cluster capacity must be planned** - Draining nodes without headroom causes scheduling failures
5. **Kata updates need task-aware draining** - Active VM-isolated tasks need graceful completion
6. **Test rollback procedure regularly** - Rollback under pressure without practice fails
