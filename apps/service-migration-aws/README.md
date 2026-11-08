# 온프렘 → AWS DB·앱·접수서비스 이전

이번 단계는 DB와 요청을 처리하는 앱, 접수서비스 및 Redis 원장을 AWS로 옮긴다.
**기존 사용자 도메인의 DNS/Caddy 전환은 다음 단계**다. 현재 공개 주소를 자동으로
바꾸거나, 이전 완료만으로 온프렘을 즉시 꺼도 된다고 표시하지 않는다.
기존 `cloud-migration-aws`의 AWS↔GCP 실험과 독립적인 namespace/원장을 사용한다.

```
기존 내부 트래픽봇 → 온프렘 접수서비스(forward 전용)
                            ↓
               AWS service-receipt ↔ AWS Redis AOF/PVC
                            ↓
                    AWS EKS sample-app → AWS RDS

직접 대상 검증 → AWS service-receipt → AWS EKS sample-app → AWS RDS
기존 사용자 공개 DNS/프록시 → 이번 단계에서 바꾸지 않음
```

앱은 `apps/sample-app/runtime/full-aws`가 기존 AWS wrapper 위에 같은 신규 이미지
커밋을 명시해 EKS에 배포한다. DB Secret·RDS CA·API 인증·Ingress TLS는 기존 AWS
wrapper를 재사용한다. 러너는 `/api/info.version`을 `destination_app_version`과 비교해
의도한 앱 이미지가 준비됐는지 확인한다. full wrapper는 Pod와 Service에 같은
`ghost.dev/migration-version` selector를 적용해 카나리 중 남은 구버전 Pod로
요청이 섞이지 않게 한다. 새 Pod가 Ready가 되기 전에는 목적지 앱이 일시적으로
503을 반환할 수 있으므로 준비 완료 전에 이전을 시작하지 않는다.
DB-only 경로 `aws_db`(온프렘 앱→RDS)가 아니라 `aws_eks`를 선택한다.
새 AWS 접수서비스는 초기 standby이며, import/activate 전에는 요청을 수락하지 않는다.
앱 readiness는 기대 `environment=aws`, `database=migration_demo`와 일치해야 한다.
완료 검증은 AWS 접수 주소를 직접 호출해 원장 identity와 보존된 요청을 확인한다.

## 저장소 경로와 기본 상태

| 경로 | 역할 | 기본 적용 |
|---|---|---|
| `apps/sample-app/runtime/full-aws` | 동일 신규 앱 이미지로 EKS 준비 | 명시 활성화 때 선택 |
| `argocd-full-service` | EKS 앱 + AWS receipt의 활성화 그래프 | 기본 root에서 선택하지 않음 |
| `apps/service-migration-aws` | AWS 접수서비스·Redis·NetworkPolicy | replicas=0, ALB 없음 |
| `apps/service-migration-aws-active` | AWS 준비 환경 | 명시 승격 때 replicas=1 + HTTPS ALB |
| `apps/durable-ingress-full-aws` | 온프렘 접수 seal/export/forward 설정 | 기존 Argo 경로 유지, 자동 적용 안 함 |
| `apps/live-db-cutover-full-aws` | full config 선택·새 인증값 참조 | 기존 DB-only 러너 경로 유지 |
| `argocd/aws-migration/service-migration.yaml` | AWS app-of-apps 자식 | 안전한 base 경로 |
| oneaction-infra `infra/service-migration-edge` | AWS 접수 전용 주소 | ALB hostname 없으면 레코드 없음 |

새 endpoint `service-migration.hackerthon.yubin.dev`는 러너가 목적지에 안전하게
접근하기 위한 준비 주소다. 기존 사용자가 접속하는 도메인 레코드를 바꾸는 작업과 다르다.
`full_migration` 설정에는 공개 경로를 바꾸는 `traffic:` 절이 없다.

이미지 핀은 2026-11-08 registry manifest 조회로 게시를 확인한 main 빌드다.
소스 커밋이 존재하는 것과 registry에 이미지가 게시된 것은 다르므로 이후 갱신에도 게시 확인이 필요하다.

| 사용처 | 게시된 이미지 태그 | 확인한 manifest digest |
|---|---|---|
| 원본/대상 접수서비스·EKS 앱 | `docker.io/kty1021/sample-app:8313bcf696306994d0daeb64ac8a7b0f2ca29489` | `sha256:8872fd812e4eb11294d8fb06d9776967e2ab7096a19e515754a408f337d1a76a` |
| full 러너 | `ghcr.io/softbankhackathon2026/migration-tools:f67bc776a37a9e10da097e53f45a555b3dcbf8de` | `sha256:b55a404c3a806961e01d7b4c18a673201002415ec070330c89eb8d0e9b304b13` |

빌드 근거: [sample-app main CI](https://github.com/SoftBankHackathon2026/sample-app/actions/runs/42434508786),
[runner main CI](https://github.com/SoftBankHackathon2026/Hackathon/actions/runs/42434857960).
접수서비스 2개와 EKS 앱 이미지·버전 selector·`destination_app_version`은 같은 sample-app SHA다.
게시 확인은 Secret·TLS·실제 통합 시험 완료를 의미하지 않는다.
canonical `fleet_reporter.py` 동기화는 기본 러너 ConfigMap 해시도 바꾸므로 GitOps 머지/
동기화 전에 기존 전환 작업이 실행 중이지 않은지 확인한다. 상태 PVC는 유지한다.
source/destination 접수의 시작 명령은 `HANDOFF_PROTOCOL_VERSION=1`을 확인한다.
구버전 이미지가 standby/forward 환경변수를 무시하고 접수하는 일을 막기 위해
지원하지 않는 이미지는 시작에 실패한다.
앱 설정에서 기존 RDS 쓰기를 열거나 데이터를 지우지 않는다. PRECHECK는 대상 앱 계정의
INSERT가 닫혔는지 확인하므로, 이미 대상이 라이브 writer이면 운영 인계부터 필요하다.

## Secret 계약

값을 Git·명령 인수·문서에 기록하지 않는다. 기존 승인된 Secret 관리 경로로 공급한다.
이 파일들은 Secret 참조만 만들며 실제 값이나 기존 계정 권한을 임의 복제하지 않는다.
현재 `external-secrets-sample-app` 컨트롤러는 `sample-app` namespace만 감시하므로
새 `service-migration` namespace의 Secret은 자동 생성되지 않는다. 승인된 Secret
공급 경로를 먼저 마련해야 하며, 그 전에는 receipt Pod가 기동하지 않는 것이 정상이다.

| 위치 | Secret/키 | 사용처 |
|---|---|---|
| AWS `service-migration` | `service-migration-auth/api-token` | AWS receipt `/api` 인증 |
| AWS `service-migration` | `service-migration-auth/control-token` | `/control` 인증, API 토큰과 별개 |
| AWS `service-migration` | `service-migration-auth/app-token` | AWS EKS 앱의 기존 요청 API 토큰 |
| 온프렘 `hackathon` | `service-migration-auth/api-token` | source forward + 러너 목적지 검증 |
| 온프렘 `hackathon` | `service-migration-auth/control-token` | 러너 AWS handoff 제어 |
| 온프렘 `hackathon` | `sample-app-eks-api-token/token` | 러너 EKS readiness 확인 |
| 온프렘 `hackathon` | `durable-ingress-control/token` | source handoff 제어, 필수 |

양쪽 `api-token`, `control-token`은 각각 같은 값이어야 한다. `app-token`은 실제 EKS
앱 API 토큰과 같아야 한다. 제어 인증값을 공개 API 토큰으로 사용하지 않는다.
`/control`은 ALB HTTPS→8080 내부 경로이며 반드시 별도 bearer를 요구한다.
9092 Service와 Redis 외부 주소를 만들지 않는다. Redis6379는 receipt Pod만 접근한다.
NetworkPolicy는 EKS CNI의 실제 enforcement 여부도 배포 때 확인해야 한다.

## 적용 순서

1. 새 sample-app handoff 이미지와 migration runner 이미지를 게시한 뒤 핀을 갱신한다.
   `service-migration-aws`, `durable-ingress-full-aws`, `sample-app/runtime/full-aws`는
   같은 게시된 sample-app 이미지를 쓰며 full config의 `destination_app_version`도 같은 SHA다.
   `live-db-cutover-full-aws`는 full_migration을 이해하는 runner 이미지를 쓴다.
2. AWS EKS 앱 `/readyz`, `/api/info`와 DB명·AWS 환경을 확인한다. 현재 writer와 전환 대상의
   소유권을 확인하고 원본/대상 DB를 초기화하거나 기존 job을 재사용하지 않는다.
3. Secret을 공급하고 AWS root의 GitOps source 경로를 `argocd-full-service`로 선택한다.
   이 그래프는 기존 `sample-app-aws`의 첫 source를 `runtime/full-aws`로, 새 receipt
   child를 `service-migration-aws-active`로 지정한다. Argo가 새 앱 이미지와
   receipt·Redis·ALB를 배포한다. 기존 분석 source와 Secret/TLS 선언을 보존한다. Redis PVC를 보존한다.
4. 실제 ALB hostname을 `infra/service-migration-edge`에 넣어 승인된 Terraform 경로로
   목적지 주소를 준비한다. ALB ACM 인증서가 새 hostname을 포함하고 `ISSUED`인지 확인한다.
   기존 예시 인증서의 SAN이 다르면 실제 인증서 ARN으로 GitOps를 갱신한다. TLS 검증을 끄지 않는다.
5. 온프렘 durable-ingress Argo 경로를 `apps/durable-ingress-full-aws`로, 러너 경로를
   `apps/live-db-cutover-full-aws`로 바꿔 Argo 동기화한다. 서비스 재시작은 전달을 paused로
   시작한다. 진행 중인 기존 전환 작업이 없어야 한다.
6. 새 `full_service_forward_001` 작업으로 실행한다. 플랫폼 보고기의 base config는
   `/etc/live-cutover/config.full-aws.yaml`이다. 이 설정은 온프렘→AWS 전용이므로
   귀환/리허설 작업에 재사용하지 않는다. 출발 DB `migration_demo_return`→AWS `migration_demo`.
   플랫폼 환경 `onprem`은 `platform_data_targets`에서 실제 DB target `onprem_return`로
   명시적으로 매핑한다. `platform_apps`는 `sample-app`,
   `hackathon/Deployment/sample-app`, `hackathon/Rollout/sample-app`만 허용하는 명시적
   별칭 목록이다. 이 중 정확히 1개를 선택하고 방향이 일치하는 작업만 실행한다.
   다른 namespace의 동명 앱이나 여러 앱을 이 데모 preset으로 이전했다고 표시하지 않는다.
7. READY 이후 실제 승인으로 전환한다. 러너가 source 접수 seal·진행 중 요청 정리·원본 DB
   쓰기 차단·CDC 최종 확인 후 원장/대기 요청 import와 AWS 활성화를 수행한다.
   이전 source 접수는 forwarding 전용이 된다. 기존 DNS/Caddy 표식은 바꾸지 않는다.
8. AWS receipt ledger identity와 앱 environment/database, 보존된 요청과 AWS 신규 요청
   처리를 검증한다. 트래픽봇은 검증 후 정지한다. DNS 전환은 다음 단계로 남는다.

**개발 검증은 운영 전환 검증이 아니다.** 이 변경만 머지하면 기존 DB-only 잡이
자동으로 전체 이전을 실행하지 않는다. 활성화에 필요한 이미지·Secret·목적지 TLS가
실제 준비된 뒤 full overlay를 선택해야 한다. 가연의 실제 통합 테스트 전에는 완료로 표시하지 않는다.

## 실패 복구와 다음 단계

seal 뒤에는 source가 새 로컬 요청을 수락하지 않는다. 재시작도 seal을 지우지 않는다.
전송 중 실패는 같은 handoff ID로 재개한다. 목적지 원장/PVC 삭제로 재시도하지 않는다.
AWS activate 또는 대상 DB 쓰기를 시도한 뒤에는 source writer를 자동 재개하지 않는다.
응답 유실 시에도 AWS가 이미 처리했을 수 있으므로 상태를 조회해 이어간다.

다음 단계는 기존 사용자 진입점의 DNS/프록시를 AWS 앱과 AWS 접수서비스로 넘기는 것이다.
그 전에는 기존 공개 주소가 온프렘 앱으로 갈 수 있고, 직접 온프렘 접수 주소를 쓰는
클라이언트는 forwarding에 의존한다. **온프렘 전체 종료는 이 단계의 완료 조건이 아니다.**
공개 경로 인계와 구주소 트래픽 확인 뒤 별도 GitOps 변경으로 종료한다.

## 로컬 검증

```sh
kubectl kustomize apps/service-migration-aws
kubectl kustomize apps/service-migration-aws-active
kubectl kustomize apps/durable-ingress-full-aws
kubectl kustomize apps/live-db-cutover-full-aws
kubectl kustomize argocd
kubectl kustomize argocd-full-service
kubectl kustomize apps/sample-app/runtime/full-aws
python3 tests/full-service-migration.test.py
python3 tests/cutover-bot-wiring.test.py
```

Python 테스트는 PyYAML과 kubectl을 사용한다. 서버·Secret·DB에 접근하지 않는
렌더/계약 검증이며 실제 DNS/TLS/Argo 동기화/마이그레이션 실행을 대신하지 않는다.
