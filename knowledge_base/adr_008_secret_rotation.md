# ADR-008: Automated Secret Rotation Across Multi-Region Secrets Manager

## Status
Accepted

## Context

IBM Cloud Pipeline operated as a SaaS CI/CD platform under SOC2 compliance. Secret rotation was a compliance requirement - credentials could not remain static indefinitely.

The platform ran microservices across multiple regions, each with their own regional Secrets Manager (SM) instance. Services consumed secrets from their regional SM at startup or on credential refresh.

**The manual rotation process:**

1. Security team identifies credential due for rotation
2. Engineer manually generates new credential
3. Engineer manually updates Secrets Manager in each region
4. Engineer manually restarts each microservice consuming the credential
5. Engineer validates services are running with new credential
6. Document completion for SOC2 audit trail

**Problems with manual rotation:**
- Time-consuming across multiple regions (could take hours)
- Error-prone - easy to miss a region or a service
- Inconsistent execution - different engineers followed steps differently
- Created toil that scaled with number of secrets and regions
- Audit trail was manual and inconsistent
- Risk of service disruption if restart sequence was wrong

## Decision

We automated the entire secret rotation workflow using a pipeline-triggered approach:

### 1. Rotation Script

A bash script handled the credential replacement logic:

```
For each region:
  1. Fetch current live credential from production SM
  2. Generate new credential
  3. Store new credential in SM as active version
  4. Promote old credential to backup version
  5. Validate new credential is accessible
```

### 2. Webhook Pipeline Trigger

After credential replacement, a webhook triggered a downstream pipeline:

```
Rotation script completes
  → Sends webhook to pipeline system
  → Pipeline identifies all microservices consuming rotated secret
  → Pipeline restarts each microservice in controlled sequence
  → Services pick up new credential on restart
  → Pipeline validates service health post-restart
```

### 3. Multi-Region Execution

Script executed per region to ensure regional SM instances were all updated:
- Each region had its own SM instance
- Rotation executed sequentially per region
- Validation per region before proceeding to next
- Rollback to backup credential if validation failed

### 4. Audit Trail

Every rotation automatically generated:
- Timestamp of rotation per region
- Which credential was rotated
- Which services were restarted
- Health validation results
- Git commit recording rotation event for SOC2 audit

## Consequences

### Benefits
- ✅ Eliminated manual rotation toil entirely
- ✅ Consistent execution across all regions every time
- ✅ Automatic audit trail for SOC2 compliance
- ✅ Services pick up new credentials without manual intervention
- ✅ Backup credential preserved for rollback
- ✅ Reduced rotation time from hours to minutes
- ✅ Zero missed regions or services

### Trade-offs and Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Rotation script failure mid-region | Partial rotation state | Idempotent script, backup credential preserved |
| Service restart disrupts active work | Brief service interruption | Graceful restart, health checks before proceeding |
| Webhook failure | Services not restarted | Webhook retry logic, alerting on failure |
| New credential invalid | Services fail to start | Validate credential before triggering restarts |
| Wrong services restarted | Unintended disruption | Explicit service list per secret mapping |

## Implementation Details

### Rotation Script Structure (Pseudocode)

```bash
#!/bin/bash
# Secret rotation automation

SECRET_NAME=$1
REGIONS=("us-south" "eu-gb" "ap-north")

for REGION in "${REGIONS[@]}"; do
  echo "Rotating $SECRET_NAME in $REGION..."
  
  # Fetch current live credential from SM
  CURRENT_CRED=$(ibmcloud secrets-manager secret \
    --secret-id $SECRET_ID \
    --region $REGION \
    --output json | jq -r '.resources[0].secret_data.payload')
  
  # Store current as backup
  ibmcloud secrets-manager secret-version-create \
    --secret-id $SECRET_ID \
    --secret-version-prototype "{\"payload\": \"$CURRENT_CRED\", \"version_custom_metadata\": {\"status\": \"backup\"}}" \
    --region $REGION
  
  # Generate new credential
  NEW_CRED=$(generate_new_credential $SECRET_NAME)
  
  # Store new credential as active
  ibmcloud secrets-manager secret-version-create \
    --secret-id $SECRET_ID \
    --secret-version-prototype "{\"payload\": \"$NEW_CRED\", \"version_custom_metadata\": {\"status\": \"active\"}}" \
    --region $REGION
  
  # Validate new credential is accessible
  validate_credential $SECRET_NAME $NEW_CRED $REGION
  
  echo "$SECRET_NAME rotated in $REGION successfully"
done

# Trigger downstream pipeline via webhook
trigger_restart_pipeline $SECRET_NAME
```

### Webhook Pipeline Trigger

```bash
trigger_restart_pipeline() {
  SECRET_NAME=$1
  
  # Send webhook to pipeline system
  curl -X POST $PIPELINE_WEBHOOK_URL \
    -H "Content-Type: application/json" \
    -d "{
      \"secret_name\": \"$SECRET_NAME\",
      \"rotation_timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
      \"action\": \"restart_consumers\"
    }"
}
```

### Downstream Restart Pipeline

```
1. Receive webhook with secret_name
2. Look up service map: which services consume this secret
3. For each service:
   a. Trigger rolling restart
   b. Wait for pods to be ready
   c. Validate service health
4. Report completion status
5. Write audit record to Git
```

### Secret-to-Service Mapping

```yaml
# secret-service-map.yaml
secrets:
  database-credentials:
    services:
      - api-service
      - worker-service
      - reporting-service
    restart_order: sequential   # Restart one at a time
    
  redis-password:
    services:
      - cache-service
      - session-service
    restart_order: parallel     # Can restart simultaneously
    
  external-api-key:
    services:
      - integration-service
    restart_order: sequential
```

### Validation Logic

```bash
validate_credential() {
  SECRET_NAME=$1
  CREDENTIAL=$2
  REGION=$3
  
  # Attempt to use credential against target service
  case $SECRET_NAME in
    "database-credentials")
      test_db_connection $CREDENTIAL $REGION
      ;;
    "redis-password")
      test_redis_connection $CREDENTIAL $REGION
      ;;
  esac
  
  if [ $? -ne 0 ]; then
    echo "Credential validation failed in $REGION. Rolling back..."
    rollback_credential $SECRET_NAME $REGION
    exit 1
  fi
}
```

## SOC2 Audit Trail

Every rotation produced a Git commit:

```
feat: rotate database-credentials [automated]

Rotation timestamp: 2024-03-15T10:30:00Z
Regions rotated: us-south, eu-gb, ap-north
Services restarted: api-service, worker-service, reporting-service
Validation: PASSED all regions
Triggered by: scheduled rotation policy
```

## Monitoring and Alerting

Key metrics:
- `secret_rotation_success_total` - Count of successful rotations
- `secret_rotation_failure_total` - Count of failures (alert on any)
- `secret_rotation_duration_seconds` - Time to complete full rotation
- `service_restart_success_rate` - Services successfully restarted after rotation

Alert on:
- Any rotation failure (immediate)
- Rotation duration > 30 minutes (investigate)
- Service failing to restart after credential rotation (immediate)
- Secret approaching expiry without rotation scheduled (warning)

## Related Decisions

- ADR-005: CVE Automation (similar pipeline-triggered automation pattern)
- ADR-003: Pipeline as Code (restart pipeline defined as code)
- ADR-009: SOC2 Compliance Operations (rotation supports compliance requirements)

## Lessons Learned

1. **Backup credential before replacing** - Always preserve rollback path
2. **Validate before restarting services** - Bad credential + service restart = outage
3. **Sequential restarts by default** - Parallel restarts can cascade failures
4. **Webhook retry logic is essential** - Network failures cannot leave services on old credentials
5. **Service map must be maintained** - Outdated mapping causes missed restarts
6. **Audit trail must be automatic** - Manual audit records are inconsistent and incomplete
7. **Test rotation in dev first** - Rotation scripts need their own testing lifecycle
