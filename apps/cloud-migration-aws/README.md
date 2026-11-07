# 온프렘 없이 AWS↔GCP 전환

```
AWS 트래픽 봇/외부 사용자 → 고정 HTTPS 접수 주소(ALB)
                              ↓
                      AWS durable-ingress ↔ AWS Redis AOF/PVC
                              ↓ 대상 전환
                      AWS 앱 또는 GCP GKE 앱 → 해당 DB

AWS RDS → AWS Connect(Source) → AWS Kafka/PVC → AWS Connect(Sink)
                                                     ↓ 같은 Pod의 Auth Proxy
                                                 GCP Cloud SQL

AWS 전환 Job: 앱 제어 어댑터(loopback) → AWS ingress 제어 API
             DB 검사·차단·비교 → Connect 제어 → 대상 변경·resume
```

실행 중 데이터·요청·제어 경로에는 온프렘/운영자 PC/port-forward가 없다.
GitOps를 반영하는 관리 접속과 실제 실행 경로는 구분한다.
반대 방향은 새 job·새 빈 대상 DB와 반대 source/target 설정으로 수행한다.
기존 온프렘 리허설 및 혜연의 RDS→Cloud SQL job을 자동 인계/재개하지 않는다.

## 고정 주소와 발신 IP

- 접수 주소: `https://cloud-migration.hackerthon.yubin.dev` (새 ALB를 가리키는 고정 DNS).
- GCP 앱: `https://gcp-migration.hackerthon.yubin.dev` (새 GCP static IP + ManagedCertificate).
- AWS 앱: 기존 `https://sample-app.hackerthon.yubin.dev`.
- AWS outbound는 기존 private subnet NAT Gateway EIP를 사용한다. 2026-11-07 EC2/route 조회에서
  실행 중인 EKS 노드 3개가 NAT 연결 private subnet에 있고 public IP가 없음을 확인했다.
  실제 목적지에서 발신 IP 확인은 배포 후 수행한다. 새 EIP/NAT를 중복 생성하지 않는다.
- IP/DNS Terraform: oneaction-infra `infra/cloud-migration-edge`.
- GCP 앱 HTTPS: gitops `apps/cloud-migration-gcp-edge`.

## 기본 상태 / 활성화 순서

이 base는 workload replicas=0, Job suspend=true다. AWS root에만 포함되어 있고,
ALB를 만드는 `apps/cloud-migration-aws-active`는 명시적으로 경로를 바꾸기 전에는 적용되지 않는다.
GCP edge Application도 `.staged.yaml`이며 root에 아직 포함하지 않았다.

1. 현재 RDS/GCP job 소유자와 단일 writer 및 DB 소유권을 확정한다. 새 Kafka에는 기존 offset이 없으므로
   기존 job/slot/checkpoint를 그대로 붙이지 않는다. 새 job·새 빈 대상 DB로 시작한다면
   `config.cloud.yaml`과 앱 대상 DB를 함께 바꾸며 `REPLACE_` 값을 없앤다. 현재 복사본을 비우지 않는다.
2. 아래 Secret을 승인된 Secret 관리 경로로 공급한다. 코드에 값은 없다. RDS SG는 EKS→5432를 허용하고,
   Google API443 및 Cloud SQL3307 outbound가 필요하다. GCP Auth Proxy는 Pod loopback5432만 바인드한다.
   Cloud SQL public IP는 `db_enable_proxy_public_ip=true`를 실제 GCP tfvars에 반영해 유지한다.
   authorized_networks를 추가하지 않으며 인증 프록시 이후는 TLS다.
3. GCP static IP/DNS와 정확한 `ghost-project-513812 / asia-northeast3 / oneaction-dev` GKE의
   Argo 등록을 준비한다. 기존 `tokyo-gke` 등록은 다른 프로젝트이므로 쓰지 않는다.
   GCP edge child를 root 목록에 추가하고 HTTPS 인증서 ACTIVE, 무인증 요청 거부,
   /api/info의 environment/database 및 /readyz를 확인한다.
4. AWS EKS EBS CSI/default StorageClass, 가용 CPU/메모리/ephemeral disk, NetworkPolicy enforcement를 확인한다.
   root child 경로를 `apps/cloud-migration-aws-active`로 바꿔 Argo가 큐·복제 도구·ALB를 띄운다.
   준비 단계에서 **트래픽 봇은 여전히 0, 전환 Job은 모두 suspended**다.
5. 생성된 ALB DNS를 Terraform aws_alb_dns_name에 반영한다. HTTPS 접수 API의 인증/Redis Ready,
   양쪽 앱 DB/계정/단일 writer를 확인한다. `cloud-ingress-initialize-001`만 Git에서 suspend=false로 바꾼다.
   이 Job은 기존 cutover.sqlite3가 있거나 epoch/초기 대상이 다르면 거절하고, 앱 readiness 확인 후 AWS 소비를 연다.
6. AWS 트래픽 봇 replicas=1을 GitOps로 활성화하면 노트북 없이 요청을 계속 생성한다.
   `cloud-migration-copy-001`을 unsuspend하면 AWS Job이 자체 프록시/어댑터를 켜고 migration.cloud run을 실행한다.
   READY(exit3)는 Job 성공으로 끝나며 승인을 자동 제공하지 않는다. 상태는 PVC에 보존한다.
7. 최종 확인 후 설정의 CLOUD_APPROVAL_ID를 실제 승인 식별자로 채우고 `cloud-migration-approve-001`을 unsuspend한다.
   같은 상태를 읽어 fence→compare→connector stop→앱 target→resume을 수행한다.
   Job은 backoffLimit=0이며, 오류를 자동 재시도로 덮지 않는다. 기존 Job pod spec 변경은 하지 말고
   새 Job 이름으로 제출한다. FAILED 재시도는 원인 확인 후 새 Job의 args에 --retry를 명시한다.

## 제어 구현

`control/adapter.py`는 전환 Job 안에서 loopback8081에 바인드하고, cloud CLI의 기존 앱 제어 계약을 구현한다.
/status의 mode를 state로 매핑하고, /drain은 큐 전체가 아니라 진행 중 전달만 기다린다.
/target은 paused/in_flight=0 확인 후 expected_epoch로 CAS하며, 같은 대상 재요청은 epoch를 증가시키지 않는다.
/resume 전 /readyz·/api/info의 environment/DB·writes_paused=false를 GET으로 확인한다. 시험 INSERT는 없다.
앱 설정의 DB명은 마스터의 source/target DB명과 일치해야 시작하며, 미입력 REPLACE 값은 거절한다.
제어는 동시에 하나만 처리하며, 잘못된 상태·누락·접근 실패는 거절한다.

`control/ingress.js`는 검증된 sample-app 이미지의 기존 Redis 전달 구현을 재사용한다.
초기 대상 aws를 명시하고 API/control 인증값을 필수로 받는다. /api 요청은 Bearer 인증을 통과해야 한다.
재시작하면 target/epoch는 Redis에서 복구하지만 paused로 시작하므로 운영자가 상태 확인 후 재개해야 한다.
임의 재시작 때 자동 resume하지 않는다. 제어9092는 runner Job만, Redis6379는 ingress만 접근한다.
ALB에는 접수8080만 연결한다. control이나 Kafka/Connect REST를 외부에 노출하지 않는다.

## Secret 계약

| Secret | 키 | 소비자 |
|---|---|---|
| cloud-migration-connect-credentials | aws_cdc_password, aws_sink_password, gcp_cdc_password, gcp_sink_password | Connect |
| cloud-migration-runner-credentials | aws_admin_password, aws_verify_password, gcp_admin_password, gcp_verify_password | 전환 Job |
| cloud-migration-gcp-auth | credentials.json | Pod별 Auth Proxy |
| cloud-ingress-auth | api-token, control-token, aws-token, gcp-token | 접수·봇·어댑터 (필요 키만) |

api-token은 트래픽 봇 계약상 32자 이상 Bearer 형식으로 공급한다. aws/gcp-token은 실제 각 앱 토큰과 일치해야 한다.
GCP ADC는 Cloud SQL Client 권한을 가진 승인된 자격증명이며 단기 federation을 우선 검토한다.
RDS는 verify-full (공개 CA 마운트), Cloud SQL은 같은 Pod loopback만 sslmode=disable이다.
앱 NOLOGIN 해제·DB 연결 변경은 별도 선행 조건이며, 실행기가 앱 계정으로 DB 로그인하지 않는다.

## 범위·위험·롤백

Kafka·Redis·접수 서비스는 각각 단일 인스턴스로 HA가 아니다. Kafka/PVC 손실은 offset 손실이다.
Redis AOF와 봇 ledger는 별도 PVC, DB 비교 임시 공간은 Job의 emptyDir(최대4Gi)에 둔다.
전체 resource requests는 각 매니페스트 기준으로 산정한다. initialize/copy/approve Job은 순서대로 실행한다.
공용 상태 PVC의 파일 잠금은 중복 실행을 거절한다. 다른 노드에서 동시에 띄우면 RWO attach 대기도 발생할 수 있다.
실제 E2E 전환·앱 요청 무손실·클라우드 TLS/IAM/DB 권한 검증은 아직 끝나지 않았다.

현재 GCP HTTP LoadBalancer와 기존 요청 생성기는 자동으로 제거하지 않는다.
모든 writer를 AWS 접수 경로로 통합하고 기존 경로 인계를 마치기 전에는 전환을 시작하지 않는다.
NEEDS_RECOVERY에서는 유일 writer를 결정하기 전 source fence를 풀지 않는다.
실행 전에는 base 경로/replicas0으로 되돌린다. 실행 이후에는 정상 중단·writer 결정을 먼저 한다.
PVC/namespace/slot/checkpoint 삭제로 롤백하지 않는다. DNS/IP를 운영 트래픽보다 먼저 삭제하지 않는다.

## 재현

```
kubectl kustomize apps/cloud-migration-aws
kubectl kustomize apps/cloud-migration-aws-active
kubectl kustomize apps/cloud-migration-gcp-edge
python3 -m unittest discover -s apps/cloud-migration-aws/tests -p 'test_*.py'
python3 apps/cloud-migration-aws/tests/control_smoke.py
```

검증 증거와 미검증 범위: [VALIDATION.md](VALIDATION.md).
공식 근거: [Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/sql-proxy),
[GKE HTTPS](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/ingress-configuration).
