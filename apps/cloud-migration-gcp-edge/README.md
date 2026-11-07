# GCP 앱 HTTPS 진입점

대상은 ghost-project-513812 / asia-northeast3 / oneaction-dev GKE다.
2026-11-07 API 읽기로 sample-app namespace의 sample-app Service 및 Rollout을 확인했다.
Service는 active hash를 선택하고 NEG ingress=true를 이미 가진다. 이 구성은 Service/selector/DB/앱을 바꾸지 않는다.
별도 Ingress, Google ManagedCertificate, HTTP→HTTPS redirect만 추가한다.

oneaction-infra/infra/cloud-migration-edge로 고정 IP·DNS를 준비한 뒤,
정확한 GKE를 중앙 Argo에 등록하고 argocd/aws-migration/cloud-migration-gcp-edge.staged.yaml을
root의 명시적 목록에 추가한다. 아직 포함하지 않았으므로 merge만으로 GCP 변경이 적용되지 않는다.
기존 tokyo-gke 등록은 다른 프로젝트를 가리켜 재사용하면 안 된다.

인증서 ACTIVE, /readyz, /api/info의 environment/database 일치 및 무인증 요청 거부를 확인한다.
현재 사용 중인 HTTP LoadBalancer는 자동 삭제하지 않는다. 새 경로 검증과 기존 사용자 인계가 끝난 후
원 소유 GitOps에서 public Service를 ClusterIP로 변경하고 직접 접근 제거를 별도 검토한다.
모든 쓰기 주체가 AWS 접수 경로로 통합되기 전에는 전환을 시작하지 않는다.
이 PR은 새 DB/DB 권한/Secret을 바꾸지 않는다. 새 빈 대상 DB가 필요하면 앱 DB 연결도 그 DB로 맞춰야 한다.

https://docs.cloud.google.com/kubernetes-engine/docs/how-to/ingress-configuration
