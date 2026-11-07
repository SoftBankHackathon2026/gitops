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

AWS SSO 토큰 만료로 EKS StorageClass/노드 조회 실패. 클러스터 수정 없음.
현재 RDS→Cloud SQL job/기존 target/온프렘 리소스 변경 없음.
GCP Secret, DB 역할, SG/네트워크, 실제 프록시 인증과 앱 제어 어댑터, E2E 전환은 미검증.
단일 Kafka의 가용성·처리량·복구시간 보장 시험은 수행하지 않았다.
