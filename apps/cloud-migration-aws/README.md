# AWS에서 실행하는 클라우드 간 PostgreSQL 복제

현재 온프렘 작업과 분리된 EKS 전용 배포다. 경로는
`RDS private endpoint → EKS Connect(Source) → EKS Kafka → EKS Connect(Sink) → 같은 Pod의 Cloud SQL Auth Proxy → Cloud SQL`.
전환 실행기도 EKS에서 실행한다. Kafka 주소·Connect 주소·DB 프록시는 온프렘을 참조하지 않는다.
기존 온프렘 `migration-cdc`, 현재 복사 완료한 대상 DB, job 및 checkpoint는 수정하지 않는다.

## 배포 상태와 활성화

`argocd/aws-migration-root`의 명시적 목록에 child Application을 추가했다.
새 namespace는 `cloud-migration`. 세 workload는 모두 replicas=0으로 시작한다.
이는 실행 중인 복제를 자동으로 재개하거나 같은 DB에 두 sink를 붙이지 않기 위한 초기 상태다.
실제 배포·AWS↔GCP 통신·사용자 인수 완료를 의미하지 않는다.

1. AWS SSO 갱신 후 EKS 가용 리소스, 기본 EBS StorageClass/CSI, NetworkPolicy enforcement를 확인한다.
   리허설 구성의 총 requests는 CPU 500m / 메모리 1920Mi, Kafka PVC 20Gi, 실행기 상태 PVC 2Gi다.
   비교용 /tmp는 최대 4Gi ephemeral disk다. 노드 여유/ephemeral-storage와 실제 DB 크기를 확인한다.
   **Kafka는 단일 broker/controller, 복제 계수 1이라 HA 구성이 아니다.** PVC 손실은 offset 손실이다.
2. 아래 Secret을 승인된 Secret 관리 경로로 제공한다. 값은 Git/로그/CLI 인수에 넣지 않는다.
   이 PR은 Secret 값이나 IAM 권한을 생성하지 않는다. 다른 namespace의 기존 Secret을 자동 재사용하지 않는다.
3. `settings.yaml`의 인스턴스 이름, `config.cloud.yaml`의 역할/DB명/테이블과 앱 제어 URL을 담당자와 확정한다.
   현재 대상 DB의 초기 복사 데이터를 덮어쓰지 않는다. 새 job은 **새 빈 대상 DB**를 사용한다.
   예시의 `REPLACE_` 값은 실제 값으로 교체해야 한다.
4. Cloud SQL public IP가 활성화되어야 한다. 이 경로는 AWS에서 IAM 인증 프록시로 직접 연결하며
   Cloud SQL authorized network에 0.0.0.0/0을 추가하지 않는다. Terraform이 public IP를 끄면 연결이 끊기므로
   인프라 소유자와 desired state를 먼저 맞춘다. RDS는 EKS에서 VPC 사설 경로와 SG 5432 허용이 필요하다.
   AWS outbound DNS, Google API 443, Cloud SQL 3307을 허용한다. 프록시의 로컬5432는 Pod loopback만 바인드한다.
5. Git에서 Kafka replicas만 1로 바꾸고 Argo 동기화/Ready/PVC를 확인한다. 이어 Connect·runner를 1로 바꾼다.
   연결 플러그인 목록과 STOP/offset API를 확인한다. 기존 데이터 복제는 아직 시작하지 않는다.
6. 실행기 컨테이너에서 `python -m migration.cloud --config /etc/cloud-migration/config.yaml --state-dir /var/lib/worker plan`으로 확인한다.
   기존 cloud job 소유자와 writer/대상/slot/publication 인계를 확정한 뒤에만 같은 명령의 마지막을 `run`으로 바꾼다.
   READY 이후 `run --approve <승인 식별자>`는 별도 운영 결정이다. 매니페스트는 run/approve를 자동 호출하지 않는다.

### Secret 계약

| Secret | 키 | 소비자 |
|---|---|---|
| cloud-migration-connect-credentials | aws_cdc_password, aws_sink_password, gcp_cdc_password, gcp_sink_password | Connect만 |
| cloud-migration-runner-credentials | aws_admin_password, aws_verify_password, gcp_admin_password, gcp_verify_password | 실행기만 |
| cloud-migration-gcp-auth | credentials.json | 두 Pod의 프록시만 |

GCP 인증 파일은 Cloud SQL Client 권한을 가진 승인된 ADC 자격증명이다. 단기 federation을 우선 검토한다.
자동 IAM DB 로그인을 켠 구성이 아니므로 DB 로그인 비밀번호도 따로 필요하다.
app 역할은 실행기가 DB 로그인에 사용하지 않는다. 앱 NOLOGIN 해제 및 요청 라우팅은 앱 담당자의 전환 계약에 속한다.
공개 RDS CA는 libpq `PGSSLROOTCERT` 및 JDBC 기본 경로 `/kafka/.postgresql/root.crt`에 제공한다.
RDS는 verify-full, GCP는 같은 Pod loopback 구간만 sslmode=disable이며 프록시 이후는 인증된 TLS다.

### 앱 제어 경로

`application.control_url`은 **AWS에서 실행하는 어댑터**의 HTTPS 주소로 확정해야 한다.
어댑터는 `status/pause/drain/target/resume/healthz` 계약 전체를 구현해야 한다.
이 PR은 담당자가 개발 중인 어댑터나 durable-ingress를 복제하지 않는다.
온프렘의 어댑터/ingress를 계속 쓰면 DB 복제 데이터 경로는 AWS로 옮겨도 전체 전환 제어는 여전히 온프렘에 의존한다.
따라서 현재 이 구성만으로 전체 서비스의 온프렘 독립이 완료되었다고 표시하면 안 된다.

## 기존 작업 인계와 복구

- `internal_forward_20261107`을 재개하지 않는다. 현재 RDS→Cloud SQL 초기 복사 job 역시 자동 인계하지 않는다.
- 새 Kafka에는 기존 Connect 내부 토픽/offset이 없다. 같은 job/slot으로 바로 실행하면 안전한 이어받기가 되지 않는다.
- 가장 명확한 검증 경로는 기존 작업을 소유자가 정리한 뒤 새 job·새 빈 대상 DB로 다시 복사하는 것이다.
  기존 복사를 보존하며 이관하려면 Kafka 데이터/내부 토픽, connector config, DB slot/publication,
  마스터 checkpoint와 잠금, writer 차단 상태를 함께 이관하는 별도 절차가 필요하다.
- 승인 이후 오류/NEEDS_RECOVERY는 자동 rollback/unfence하지 않는다. 원본·대상 중 유일 writer를 먼저 결정한다.
- 신규 작업 실행 전에는 Git에서 replicas=0으로 되돌릴 수 있다. 실행 뒤에는 운영 중단 절차를 먼저 수행한다.
  PVC/namespace/slot 삭제로 rollback하지 않는다. Argo prune은 꺼 두었고 PVC는 보존한다.

## 검증

```
kubectl kustomize apps/cloud-migration-aws > /tmp/cloud-migration-aws.yaml
kubectl kustomize argocd > /tmp/aws-applications.yaml
```

로컬 Kafka/Connect 기동·재시작 증거는 VALIDATION.md에 기록한다.
실제 RDS/Cloud SQL 연결, IAM, SG, EKS 자원, 어댑터, 사용자 요청 전환은 별도 실환경 검증 대상이다.

공식 근거: [Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/sql-proxy),
[Apache Kafka Docker](https://kafka.apache.org/39/getting-started/docker/).
