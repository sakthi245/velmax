# Hybrid Web Scraper - Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the Hybrid Web Scraper in production.

## Directory Structure

```
k8s/
├── base/                          # Base manifests (common to all environments)
│   ├── namespace.yaml             # Namespace definition
│   ├── configmaps.yaml            # Application configuration
│   ├── secrets.yaml               # Secrets (API keys, passwords)
│   ├── pvcs.yaml                  # Persistent Volume Claims
│   ├── api-deployment.yaml        # API server deployment
│   ├── worker-deployment.yaml     # Worker deployment
│   ├── hpa.yaml                   # Horizontal Pod Autoscalers
│   ├── network-policies.yaml      # Network policies for security
│   ├── rbac.yaml                  # RBAC permissions
│   ├── backup-cronjob.yaml        # Backup CronJob
│   ├── logging.yaml               # Fluent Bit logging
│   └── kustomization.yaml         # Base kustomization
├── overlays/
│   └── production/                # Production-specific overrides
│       └── kustomization.yaml
└── monitoring/
    ├── servicemonitor.yaml        # Prometheus ServiceMonitors
    ├── prometheus-rules.yaml      # Alerting rules
    └── grafana-dashboard.json     # Grafana dashboard
```

## Prerequisites

- Kubernetes 1.24+
- kubectl configured
- kustomize (built into kubectl 1.14+)
- Helm 3+ (for Prometheus Operator, Loki, Grafana)
- Storage classes: `nfs-client`, `fast-ssd`, `standard`
- Ingress controller (nginx-ingress recommended)
- Prometheus Operator (for ServiceMonitors and PrometheusRules)

## Quick Start

### 1. Install Dependencies

```bash
# Install Prometheus Operator
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring

# Install Loki
helm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki-stack -n monitoring

# Install Grafana (if not included in kube-prometheus-stack)
```

### 2. Create Storage Classes

Ensure these storage classes exist:

```bash
# nfs-client - for shared storage (output, playwright cache)
# fast-ssd - for databases (postgres, redis, prometheus)
# standard - for backups, grafana
```

### 3. Configure Secrets

Edit `k8s/base/secrets.yaml` with your actual API keys:

```bash
# Required secrets to update:
# - GROQ_API_KEY
# - SERPAPI_API_KEY
# - TINYFISH_API_KEY
# - POSTGRES_PASSWORD
# - REDIS_PASSWORD
# - RABBITMQ_PASSWORD
```

Or create from file:

```bash
kubectl create secret generic hybrid-scraper-secrets \
  --from-literal=GROQ_API_KEY=your-key \
  --from-literal=SERPAPI_API_KEY=your-key \
  --from-literal=TINYFISH_API_KEY=your-key \
  --from-literal=POSTGRES_PASSWORD=secure-password \
  --from-literal=REDIS_PASSWORD=secure-password \
  --from-literal=RABBITMQ_PASSWORD=secure-password \
  -n hybrid-scraper --dry-run=client -o yaml | kubectl apply -f -
```

### 4. Deploy

```bash
# Deploy base
kubectl apply -k k8s/base

# Or deploy production overlay
kubectl apply -k k8s/overlays/production

# Deploy monitoring
kubectl apply -k k8s/monitoring
```

## Verification

```bash
# Check deployments
kubectl get pods -n hybrid-scraper

# Check services
kubectl get svc -n hybrid-scraper

# Check HPA
kubectl get hpa -n hybrid-scraper

# Check PVCs
kubectl get pvc -n hybrid-scraper

# Check logs
kubectl logs -n hybrid-scraper -l app.kubernetes.io/component=api
kubectl logs -n hybrid-scraper -l app.kubernetes.io/component=worker
```

## Accessing Services

### API Server
```bash
# Port forward
kubectl port-forward -n hybrid-scraper svc/hybrid-scraper-api 8000:8000

# Or create ingress
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hybrid-scraper-api
  namespace: hybrid-scraper
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: scraper.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: hybrid-scraper-api
            port:
              number: 8000
EOF
```

### Grafana
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Login: admin / (check secret prometheus-grafana)
```

### Prometheus
```bash
kubectl port-forward -n monitoring svc/prometheus-operated 9090
```

### RabbitMQ Management
```bash
kubectl port-forward -n hybrid-scraper svc/rabbitmq 15672:15672
# Login: guest / (check secret)
```

## Scaling

### Manual Scaling
```bash
kubectl scale deployment hybrid-scraper-api --replicas=5 -n hybrid-scraper
kubectl scale deployment hybrid-scraper-worker --replicas=10 -n hybrid-scraper
```

### Auto-scaling (HPA)
The HPA automatically scales based on:
- CPU utilization (target 70%)
- Memory utilization (target 80%)
- Task queue depth
- Task throughput

View HPA status:
```bash
kubectl get hpa -n hybrid-scraper -w
```

## Backup & Restore

### Manual Backup
```bash
kubectl create job --from=cronjob/hybrid-scraper-backup manual-backup-$(date +%Y%m%d-%H%M%S) -n hybrid-scraper
```

### Restore from Backup
```bash
# Restore PostgreSQL
kubectl exec -it postgres-0 -n hybrid-scraper -- pg_restore -U scraper -d scraper_distributed /backups/backup_file.sql.gz

# Restore Kubernetes resources
kubectl apply -f /backups/backup_timestamp/k8s_resources_timestamp.yaml
```

## Monitoring

### Key Metrics to Watch
- `scraper_worker_tasks_total` - Task throughput
- `scraper_worker_queue_depth` - Queue backlog
- `scraper_worker_task_duration_seconds` - Latency (P95, P99)
- `scraper_worker_engine_usage_total` - Engine distribution
- `scraper_worker_engine_errors_total` - Error rates by engine

### Alerts
Critical alerts are configured in `k8s/monitoring/prometheus-rules.yaml`:
- Service down
- High error rate
- Queue backlog
- High latency
- Resource exhaustion
- PVC capacity

## Troubleshooting

### Common Issues

1. **Workers not starting**
   - Check PVCs are bound
   - Check Playwright browser installation
   - Check resource limits

2. **High error rate**
   - Check target site blocking
   - Check CAPTCHA handling
   - Review engine fallback logic

3. **Queue backlog**
   - Scale up workers: `kubectl scale deployment hybrid-scraper-worker --replicas=10`
   - Check HPA status
   - Review rate limits

4. **High memory usage**
   - Check browser pool settings
   - Reduce `pool_max` in config
   - Enable more aggressive recycling

### Debug Commands
```bash
# Describe pod
kubectl describe pod -n hybrid-scraper -l app.kubernetes.io/component=worker

# Check events
kubectl get events -n hybrid-scraper --sort-by='.lastTimestamp'

# Check HPA metrics
kubectl get hpa -n hybrid-scraper -o yaml

# Port forward for debugging
kubectl port-forward -n hybrid-scraper svc/hybrid-scraper-worker 9090
curl localhost:9090/metrics | grep scraper_worker
```

## Upgrading

```bash
# Update image tag in kustomization.yaml
kustomize edit set image hybrid-scraper=hybrid-scraper:0.4.0

# Apply
kubectl apply -k k8s/overlays/production

# Rollback if needed
kubectl rollout undo deployment/hybrid-scraper-api -n hybrid-scraper
kubectl rollout undo deployment/hybrid-scraper-worker -n hybrid-scraper
```

## Security Checklist

- [ ] All secrets updated with production values
- [ ] Network policies applied
- [ ] RBAC permissions minimal
- [ ] Pod security policies enabled
- [ ] Container images scanned for vulnerabilities
- [ ] Non-root containers enforced
- [ ] Read-only root filesystem where possible
- [ ] Secrets encrypted at rest
- [ ] TLS certificates for ingress
- [ ] Audit logging enabled

## Support

For issues, check:
1. GitHub Issues
2. Documentation
3. Logs: `kubectl logs -n hybrid-scraper -l app.kubernetes.io/name=hybrid-scraper --tail=100 -f`