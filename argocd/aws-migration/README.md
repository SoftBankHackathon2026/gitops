# EKS application migration bootstrap

The live `sample-app-aws` previously referenced generated `overlays/aws`, so the
DB runtime wrapper committed in Git was not deployed. `aws-migration-root` now
reconciles the explicit list in `argocd/kustomization.yaml`: the existing sample
application, its namespace-scoped External Secrets controller, and the staged
[AWS cloud replication stack](../../apps/cloud-migration-aws/README.md) (replicas=0).
It does not adopt platform, monitoring, GCP, or onprem applications.

Prerequisites:

1. Apply `oneaction-infra/infra/eks-sample-app` and provision the remote Secret's
   `database_url` and `request_api_token` in memory.
2. Publish the verified sample-app commit to ECR. The runtime wrapper pins that
   commit; RDS uses verify-full with the public trust bundle ConfigMap.
3. Initially register `argocd/aws-migration-root.yaml` once (user approved exception
   to the no-manual-cluster-change rule). All subsequent app changes use GitOps.
4. Point `sample-app.hackerthon.yubin.dev` at the existing sample ALB after its
   HTTPS listener is ready. Requests require the API token; HTTP redirects to TLS.
5. Wait for ESO Ready, Rollout Healthy, `/readyz` 200 and AWS environment/version.
   Verify unauthenticated request API calls are rejected. Writes start paused.

The new ESO chart is 2.12.0, identical to the existing controllers. It shares their
CRDs/webhook, creates no cluster RBAC, and watches only `sample-app`. Its Pod
Identity reads only `oneaction/sample-app`. Existing controllers stay unchanged.

Switching the durable ingress requires its own GitOps target/token reference,
followed by pause → compare-and-set target → resume through the loopback control
API. A process restart pauses delivery while durable receipt continues. Do not
switch until EKS passes preflight. Keep the old backend until all accepted IDs are
confirmed. Database return uses `/etc/live-cutover/config.return-durable.yaml`
(`durable_return_001`) and must be verified separately from application routing.

Root pruning is off and child applications have no cascading deletion finalizer.
Rollback uses a Git revert of the runtime change after routing back; do not delete
the root/Secret as a way to roll back traffic. CA material here is public.

Local validation: app and root Kustomize renders; exact chart SHA256 and rendered
namespace-only RBAC; Terraform four-new-resource plan/apply. These are deployment
preparations, not evidence of successful EKS traffic or DB return.
