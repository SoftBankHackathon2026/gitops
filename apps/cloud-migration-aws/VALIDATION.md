# 검증 기록 — 2026-11-07

- `kubectl kustomize apps/cloud-migration-aws`: PASS, 10개 리소스 렌더.
- `kubectl kustomize argocd`: PASS, AWS root에서 child 포함.
- 정적 확인: workload 3개 replicas=0, 전용 namespace, ClusterIP만 노출,
  Secret 값 미포함, 렌더에 온프렘 주소 참조 없음. Kubernetes API schema/server dry-run은 미실행.
- GHCR tools `cb3a99cb3a7b7b567627f9472c181a68aca467a0` 실제 이미지로
  `migration.cloud ... plan`: 종료 0, 마스킹 JSON 파싱 성공.
  이는 예시 설정의 구조 검사이며 REPLACE 값의 실제 연결 성공이 아니다.
- Kafka 3.9.1 + 로컬 빌드 Debezium 3.7.0.Final: 기동 성공.
  REST: Connect 4.3.1, PostgreSQL Source/JDBC Sink 3.7.0.Final 확인.
  실제 AWS용 Connect GHCR 태그 존재는 registry manifest 조회로 확인했고,
  로컬 기동은 동일 버전의 `migration-connect:local` 이미지로 수행했다.
- Connect 내부 offset 토픽: replication factor=1, cleanup.policy=compact 확인.
- 빈 Docker named volume의 root 소유권 때문에 첫 Kafka 시작 실패.
  시험 볼륨 소유권을 1000으로 맞춘 뒤 성공. Kubernetes 구성은 fsGroup=1000을 사용한다.
  실제 EBS CSI의 fsGroup 적용은 AWS에서 추가 검증한다.
- Kafka에 시험 메시지 기록 후 컨테이너 강제 재생성, 같은 볼륨에서 메시지 재조회 성공.
  Connect 내부 토픽 보존 및 `/connectors` 응답 확인. 실제 DB connector offset 복구 시험은 아니다.
- `bash -n tests/smoke.sh`, `git diff --check`: PASS.

19:14 재연결 후 t3underline 프로필로 대상 계정 및 oneaction EKS ACTIVE 확인.
기본 aws-eks 컨텍스트는 다른 클러스터를 가리키며 SSO가 만료되어 있었음.
현재 외부 IP가 oneaction의 publicAccessCidrs에 없음을 비교 확인하여,
실제 EKS StorageClass/노드/API 검증은 여전히 불가. 허용 목록·클러스터 수정 없음.
현재 RDS→Cloud SQL job/기존 target/온프렘 리소스 변경 없음.
GCP Secret, DB 역할, SG/네트워크, 실제 프록시 인증과 앱 제어 어댑터, E2E 전환은 미검증.
단일 Kafka의 가용성·처리량·복구시간 보장 시험은 수행하지 않았다.

## 클라우드 전체 경로 확장 — 19:30 추가 검증

- 최종 base25 / AWS active26 / GCP edge3 / AWS root3 리소스 렌더 PASS.
- base의 모든 workload replicas=0, 세 Job suspend=true/backoffLimit0, Secret 값 없음.
  active는 큐·복제 도구·ALB만 활성화하며 봇0/Job suspended 유지 확인.
- 앱 제어 어댑터 단위 테스트11 PASS: pause/drain/epoch/target 멱등성, backlog가 있어도 in-flight0이면
  drain 완료, 상태 이상/미등록 대상/동시 제어/HTTPS 미준수/health 실패 거절. 앱 DB명과 마스터 DB 설정 불일치/같은 앱 endpoint도 거절.
- `python3 tests/control_smoke.py` PASS: 배포할 sample-app 이미지 + 실제 Redis + TLS 시험 앱2개 +
  실제 tools 이미지에서 API/control 무인증 거절, AWS 초기 target, paused 중 접수 유지,
  backlog를 남긴 drain, GCP target 변경 후 queued 요청 전달 및 GET 확인.
  시험 앱은 메모리 저장 fixture로 PostgreSQL CDC/실클라우드 전환 시험이 아니다. 테스트 컨테이너 정리 완료.
- 실제 AWS metadata: ACM wildcard 인증서 ISSUED, NAT Gateway 사용 가능,
  EKS 노드3개 모두 NAT 연결 private subnet/public IP없음 확인. NAT가 실제 앱 요청에 보이는지는 미검증.
- 실제 GCP API: ghost-project-513812 oneaction-dev RUNNING, sample-app active Service의 NEG 활성화,
  앱 REQUEST_API_AUTH/TOKEN 환경변수명 및 Cloud SQL proxy sidecar 존재 확인(Secret 값 조회 안 함).
  sample-app HTTPS Ingress는 아직 없으며 기존 platform Ingress만 존재. 다른 프로젝트 tokyo-gke 등록과 구분.
- oneaction-infra cloud-migration-edge: terraform init(-backend=false)/validate/fmt PASS.
  Cloud SQL 공개주소 opt-in: google7.29 mock-provider plan tests2 PASS, 기본 비공개 및
  opt-in 시 authorized_networks0/TLS 유지 확인. 실제 Terraform plan/apply는 미실행.

준비만 완료: DNS/IP 생성·GKE 정확한 Argo 등록·Secret 공급·새 DB/역할·writer 인계·GitOps 실제 배포·E2E 남음.
