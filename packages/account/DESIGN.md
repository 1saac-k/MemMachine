# MemMachine 회원관리 서버 + CLI 설계 문서

> 상태: v1 설계 확정. 구현은 §16 마일스톤 순서로 진행하며, 각 마일스톤은
> 구현과 해당 범위 테스트(§14)를 함께 마친 뒤 다음 마일스톤으로 넘어간다.

## 1. 배경 및 목적

MemMachine 오픈소스 on-premise 서버 자체는 인증/인가/계정 개념이 전혀 없다
(`org_id`/`project_id`는 자유 문자열 네임스페이스일 뿐, 서버 미들웨어는
access-log와 metrics뿐 — `packages/server/src/memmachine_server/server/middleware.py`).

사내에 여러 명이 MemMachine을 공유해서 쓰려면, 그 위에 사람·조직·프로젝트
단위의 회원관리와 접근 통제 레이어가 필요하다. 본 문서는 그 레이어를
"회원관리 서버(API) + CLI"로 별도 구현하는 설계를 정의한다. 웹 UI는 범위 밖.

## 2. MemMachine과의 관계 / 아키텍처

- 회원관리 서버는 **리버스 프록시/게이트웨이**로 동작한다. docker-compose
  서비스명은 기존 `postgres`/`memmachine`/`docs`처럼 짧은 단일 단어로
  맞춰 **`account`**(컨테이너/서비스 지칭용, §11).
- 모든 클라이언트 트래픽은 이 게이트웨이를 거쳐야 하며: 인증 → `org_id`/
  `project_id` 권한 확인 → MemMachine API로 포워딩 → 응답 후처리(필요 시) →
  클라이언트에 반환.
- **프록시 범위**: `/api/v2/*` 데이터 API 중에서도 **요청 바디에 `org_id`/
  `project_id`가 직접 포함된 엔드포인트만** 프록시한다 (§2.1 참고). 그래야
  게이트웨이가 요청만 보고 권한 검사를 할 수 있다.
  - `/api/v2/config/*`(임베더/LLM 인프라 설정), `/mcp`, `/health`, `/metrics`는
    게이트웨이를 거치지 않고 MemMachine에 **직접, 사내망 내부에서만** 접근
    가능(외부 미노출). v1 회원관리 대상 아님.

### 2.1 v1 프록시 대상 엔드포인트 (정확한 목록)

MemMachine `/api/v2` 엔드포인트 중 **일부는 요청 바디에 org_id/project_id가
아예 없고 내부 opaque ID(`feature_id`/`category_id`/`tag_id`/`set_id`/
`set_type_id`)로만 주소된다** (`router.py` 확인 결과). 이런 엔드포인트는
게이트웨이가 요청만 보고 소속 org를 판별할 방법이 없으므로, **v1에서는
게이트웨이 프록시 대상에서 통째로 제외(차단, 404/501)**하기로 결정함.
필요해지면 v2에서 "생성 응답을 가로채 resource_id→org_id 매핑을 자체 DB에
색인"하는 방식으로 확장 검토.

**v1 프록시 O (org_id/project_id가 요청에 직접 있음):**

| 엔드포인트 |
|---|
| `POST /api/v2/projects` (생성) |
| `POST /api/v2/projects/get` |
| `POST /api/v2/projects/list` ⚠️응답 후처리 필요(§2.2) |
| `POST /api/v2/projects/delete` |
| `POST /api/v2/projects/episode_count/get` |
| `POST /api/v2/memories` (add) |
| `POST /api/v2/memories/search` |
| `POST /api/v2/memories/list` |
| `POST /api/v2/memories/episodic/delete` |
| `POST /api/v2/memory/episodic/config`, `/config/get` |
| `POST /api/v2/memory/episodic/short_term/config`, `/config/get` |
| `POST /api/v2/memory/episodic/long_term/config`, `/config/get` |
| `POST /api/v2/memories/semantic/set_type` (생성), `/set_type/list` |
| `POST /api/v2/memories/semantic/set_id/get`, `/set_id/list` |

**v1 프록시 X (opaque ID로만 주소, org_id 없음 — 차단):**

| 엔드포인트 | 주소 방식 |
|---|---|
| `POST /api/v2/memories/semantic/delete` | `feature_id` |
| `POST /api/v2/memories/semantic/feature`, `/feature/get`, `/feature/update` | `feature_id`/`set_id` |
| `POST /api/v2/memories/semantic/set_type/delete` | `set_type_id` |
| `POST /api/v2/memories/semantic/set/configure` | `set_id` |
| `POST /api/v2/memories/semantic/category*` (get/add/disable/delete/set_ids/get) | `set_id`/`category_id` |
| `POST /api/v2/memories/semantic/category/template`, `/template/list` | `set_type_id` |
| `POST /api/v2/memories/semantic/category/tag`, `/tag/delete` | `category_id`/`tag_id` |

- MemMachine의 실제 포트는 외부에 노출하지 않고 게이트웨이 포트만 공개
  (docker-compose 네트워크 격리).
- 통신은 평문 HTTP (사내망 전제, TLS 불필요. 필요시 앞단에 별도 리버스
  프록시로 TLS 종단).

### 2.2 producer_id / produced_for_id 처리

이 필드들은 인증 주체가 아니라 **프로젝트 내부의 대화 참여자 태그**
(MemMachine 자체 스펙). 게이트웨이는 **org_id/project_id 권한만 검사**하고
`producer_id`/`produced_for_id`는 클라이언트가 보낸 값 그대로 통과시킨다
(강제 치환 없음). 인증 주체 추적은 게이트웨이 자체 감사 로그에 별도로 남긴다.

### 2.3 `/projects/list` 응답 후처리

MemMachine의 `POST /api/v2/projects/list`는 서버의 모든 프로젝트를 org 필터
없이 전부 반환한다(`router.py`). 게이트웨이는 이 응답을 호출자가 접근 가능한
org로 **필터링한 후** 반환해야 한다 (요청 검사가 아니라 응답 후처리가
필요한 유일한 데이터 엔드포인트).

## 3. 범위 (v1)

- 지원: 사람 개인 계정 + 개인 토큰 기반 인증만 (MCP/훅 등에서 본인 토큰 직접 사용).
- **미지원**: 서비스/통합 계정(배치·백엔드 프로세스용 별도 principal). 이후
  버전 과제.
- 회원관리 CLI는 **기존 `packages/client`의 memmachine CLI(메모리 add/
  search/list 등)와 완전히 별개 도구**다. 사용자는 두 CLI를 각각 설치/실행:
  - `memmachine` CLI: base-url을 게이트웨이 주소로, 토큰을 Authorization
    헤더로 설정하면 기존 그대로 작동 (메모리 조작 전담, 수정 불필요).
  - `memmachine-account`: 가입/로그인/org/project 관리 전담, 이번에 새로
    만드는 대상.

## 4. 데이터 모델

### User (계정)

| 필드 | 설명 |
|---|---|
| `id` | 로그인 ID, 가입 시 사용자가 직접 입력. 개인 org의 org_id 원천. 영문/숫자 + `-` `.` 허용(`_` 불허), 특수문자로 시작/끝 불가, 특수문자 연속 불가. |
| `email` | 회사 도메인 allowlist 통과 필수. 인증/재설정에 사용. 가입 후 변경 가능(재인증 필요, 아래 `pending_email` 참고). |
| `pending_email` | 이메일 변경 요청 중 임시 저장되는 새 이메일. 인증 코드 확인 전까지 `email`은 그대로 유지, 확인되면 `email`로 교체하고 이 필드는 비움. |
| `password_hash` | argon2id 해시. 원문/가역 암호화 저장 금지. 최소 길이는 config `auth.password_min_length`(기본 8, §10), 그 외 복잡도 규칙 없음. |
| `is_admin` | 전역 관리자 플래그. config seed 이메일 목록으로 가입 시 자동 부여. |
| `status` | `pending_verification` \| `active` \| `deactivated` \| `locked`(§6 잠금 상태). |
| `personal_org_id` | `id`에서 파생 (`.` → `_`). 가입과 동시에 자동 생성되는 개인 전용 org. |
| `failed_login_count` | 연속 로그인 실패 횟수. 성공 시 0으로 리셋. |
| `created_at` / `updated_at` | 타임스탬프. |

### Org (조직)

| 필드 | 설명 |
|---|---|
| `org_id` | MemMachine SafeId 규칙 준수(영문/숫자/`_`/`-`/`:`, 마침표 불가). |
| `kind` | `personal` \| `shared`. |
| `created_by` | 생성자 user id. |
| `created_at` | 타임스탬프. |

- **개인 org**: 가입 시 자동 생성, 소유자 1인 고정, 멤버 추가/제거 자체가
  **불가능**(본인 전용).
- **공유 org**: 아무 로그인 사용자나 생성 가능, 생성자가 자동으로 owner.
  이후 owner가 기존 가입자를 멤버로 추가/제거 가능.
- 공유 org의 `org_id`는 생성 시 owner가 직접 이름을 정한다. 개인 id와
  달리 **처음부터 새로 짓는 이름**이므로 마침표 변환이 필요 없고, MemMachine
  SafeId 문자 규칙 중 우리가 쓰는 부분집합(영문 소문자/숫자/`-`/`_`,
  시작/끝·연속 특수문자 제한은 개인 id와 동일하게 적용)을 바로 검증한다.
  이때 `_`를 직접 쓸 수 있으므로, 이론적으로 다른 사용자의 개인 org_id(예:
  `kim.yohan` → `kim_yohan`)와 이름이 겹칠 수 있다 — 이건 공유 org 생성
  시 어차피 필요한 **전역 org_id 유일성 검사**(다른 공유 org와도 겹치면
  안 되므로) 하나로 자연스럽게 커버된다. 별도 특수 로직 불필요.

### OrgMembership (공유 org에만 존재)

| 필드 | 설명 |
|---|---|
| `org_id` | 대상 org. |
| `user_id` | 대상 사용자. |
| `role` | `owner` \| `member`. |

### Project 권한 모델

- Project 실체(메모리 backend 설정)는 MemMachine 쪽에만 존재
  (`org_id`+`project_id`). 회원관리 서버는 Project를 자체 DB에 **따로
  저장하지 않는다** — 권한 판단은 org 멤버십 단위로만 이뤄지고, project
  생성/조회/삭제는 게이트웨이가 매 요청마다 MemMachine으로 그대로 프록시한다.
- org 멤버(owner/member 모두)는 그 org의 모든 project에 접근 가능
  (project별 세분화된 권한 없음).
- project 생성 시 `ProjectConfig`는 기본값(빈 값 → MemMachine cfg.yml 기본
  리소스)만 사용. project_id 이름 규칙은 공유 org_id와 동일한 문자 규칙,
  단 **org 내에서만 고유하면 됨**(전역 유일성 불필요 — MemMachine 자체가
  org_id+project_id 복합키이므로).

### Token (세션/발급 토큰)

| 필드 | 설명 |
|---|---|
| `token_hash` | 토큰 원문은 저장하지 않고 해시만 저장. |
| `user_id` | 소유자. |
| `created_at` | 발급 시각. |
| `revoked_at` | null이면 유효. |
| `last_used_at` | 마지막 사용 시각 (감사/`token list` 표시용). |

- **만료 없음**, `logout`/`token revoke`로 수동 폐기만.
- 계정당 여러 토큰(여러 기기) 동시 발급 허용, 개수 제한 없음.
- **토큰 유효성 검사는 "토큰이 revoke 안 됨" 뿐 아니라 "소유자 `status ==
  active`"까지 매 요청마다 함께 확인한다.** 그렇지 않으면 토큰이 만료되지
  않으므로 계정을 비활성화해도 기존 토큰으로 계속 접근이 가능해지는 허점이
  생긴다. `deactivated`/`locked`/`pending_verification` 상태의 사용자는
  보유 토큰이 살아있어도 모든 요청이 거부된다.

### EmailChallenge (이메일 인증 / 비밀번호 재설정 공용)

| 필드 | 설명 |
|---|---|
| `user_id` | 대상 사용자. |
| `purpose` | `signup_verification` \| `password_reset` \| `lockout_reset`(§6) \| `email_change`. |
| `code_hash` | 숫자 코드의 해시(코드 원문 미저장). 자릿수는 config `auth.email_code_length`(기본 6, §10). |
| `expires_at` | 발급 후 유효시간. config `auth.email_code_expiry_minutes`(기본 30, §10). |
| `consumed_at` | 사용 완료 시각(재사용 방지). |

### AuditLog (감사 로그)

| 필드 | 설명 |
|---|---|
| `timestamp` | 요청 시각. |
| `user_id` | 호출한 계정(비인증 요청, 예: 로그인 실패는 시도된 `id` 문자열로 기록). |
| `method` / `path` | HTTP 메서드/경로. |
| `org_id` / `project_id` | 프록시 대상 데이터 엔드포인트인 경우만 채움(§2.1 대상 외 엔드포인트는 비움). |
| `status_code` | 응답 상태 코드(권한 거부 403 포함). |

무기한 보관, 별도 삭제 없음(§18 요약 참고).

## 5. 인증(Authentication) 플로우

### 회원가입

1. `memmachine-account signup` → `id`, `email`, `password` 입력(비밀번호는 프롬프트,
   화면에 표시 안 함).
2. `id` 형식 검증(허용 문자/시작·끝/연속 규칙) + 중복 확인.
3. `email` 도메인이 config의 allowlist에 있는지 확인.
4. 통과 시 계정 생성(`status=pending_verification`), 개인 org 자동 생성
   (`org_id = id.replace(".", "_")`). `id`에서 `_`를 아예 금지했으므로 이
   치환은 단사(injective) — 서로 다른 두 `id`가 같은 개인 org_id로
   충돌하는 경우는 구조적으로 발생하지 않는다(별도 충돌 처리 불필요).
5. SMTP로 6자리 인증 코드 발송 (`EmailChallenge(purpose=signup_verification)`,
   유효시간 30분).
6. `memmachine-account verify --id <id> --code <code>` → 코드 일치 확인 → `status=active`.
   **admin 승인 절차 없음.**
7. 가입 이메일이 config의 seed-admin 목록에 있으면 `is_admin=true` 자동 부여.

### 로그인

- `memmachine-account login` → `id` + `password` 프롬프트.
- 성공: `failed_login_count=0` 리셋, 토큰 발급(응답으로 1회만 노출,
  이후 해시만 저장), 로컬 파일(`~/.config/memmachine-account/credentials`,
  평문 저장 — 내부망 전제)에 저장.
- 실패: `failed_login_count += 1`. **config `auth.failed_login_lockout_threshold`(기본 5)회
  연속 실패 시 §6 잠금 절차 발동.**

### 비밀번호 재설정 (분실 시, 본인 요청)

1. `memmachine-account reset-password request --email <email>` → 6자리 코드 발송
   (`purpose=password_reset`).
2. `memmachine-account reset-password confirm --id <id> --code <code>` → 새 비밀번호 입력 →
   `password_hash` 갱신.

### 로그인 config 임계치 초과 시 잠금 (§6과 동일 정책, 여기서는 플로우 관점)

1. `failed_login_lockout_threshold`번째(기본 5) 연속 실패 즉시: `status=locked`, `password_hash`를 **사용 불가능한
   랜덤 값으로 강제 초기화**(기존 비밀번호로 로그인 완전 차단). **기존에
   발급된 로그인 토큰(다른 기기/세션)은 그대로 유지** — 이미 로그인된
   세션에는 영향 없음. `purpose=lockout_reset` 코드를 가입 이메일로 발송.
2. 사용자는 `memmachine-account unlock --id <id> --code <code>` → 코드 확인 → 새 비밀번호
   설정 → `status=active`, `failed_login_count=0`.
3. 잠금 상태에서는 코드 확인 전까지 로그인 자체가 항상 거부(비밀번호 무관).

### 최초 admin 부트스트랩

- config 파일에 seed-admin 이메일 목록. 해당 이메일로 가입 시 자동
  `is_admin=true`.
- `memmachine-account admin sync-seed-admins`는 **양방향 동기화**다: 현재
  `is_admin=false`인데 이메일이 seed 목록에 있는 사용자는 승격(promoted),
  반대로 `is_admin=true`인데 이메일이 더 이상 seed 목록에 없는 사용자는
  강등(demoted) — config에서 이메일을 빼는 것만으로 admin 권한을 회수하는
  유일한 경로. 단, 이 동기화로 admin이 0명이 되면 실행 자체를 거부한다
  (최소 1명의 admin 보장).

## 6. 권한(Role) 체계

- **전역**: `admin`(config seed로만 부여) / 일반 사용자.
  - admin: 전체 사용자·org 조회, 사용자 비활성화/완전삭제, seed-admin 재적용.
  - **admin 권한은 계정/org 관리(`/account/v1/admin/*`)에 한정된다. 자신이
    멤버가 아닌 org의 실제 메모리 데이터(`/api/v2/*` 프록시)에는 admin도
    접근 불가** — 팀 간 데이터 프라이버시를 admin에게도 동일하게 적용
    (데이터 접근이 필요하면 admin 스스로 그 org에 멤버로 추가되어야 함).
- **org 단위**: `owner` / `member` (공유 org에만 존재; 개인 org는 본인 =
  유일 소유자, 멤버십 개념 없음).
  - owner: project 생성/삭제, 기존 가입자를 멤버로 추가/제거.
  - member: 그 org의 project에 memory read/write (project별 세분화 없음).
  - 아무 사용자나 새 공유 org 생성 가능, 생성자가 자동 owner.
  - **마지막 owner 보호**: org에 owner가 0명이 되는 상태를 만들 수 없다 —
    owner가 1명뿐일 때는 본인이 스스로 탈퇴(leave)하거나 `org set-role`로
    member로 강등될 수 없음(먼저 다른 멤버를 `org set-role --role owner`로
    지정해야 함). admin의 완전삭제 대상 org라면 예외.
  - member는 `org leave <org_id>` 명령으로 스스로 탈퇴 가능(owner가 강제
    제거하는 것과 별개의, 자기 자신에 대한 경로).

### 6.1 org_id/project_id 필수화 (universal 기본값 차단)

MemMachine은 `org_id`/`project_id`를 생략하면 `"universal"`이라는 공용
기본값으로 처리한다(`DEFAULT_ORG_AND_PROJECT_ID`, `spec.py`). 이 기본값은
누구의 소유도 아니므로, **게이트웨이는 프록시하는 모든 요청에서 org_id와
project_id를 필수 필드로 강제**하고, 생략되어 MemMachine 기본값에 의존하는
요청은 거부한다(400). "universal" org 자체도 특별 취급 없이 다른 org와
동일하게 멤버십 검사 대상.

## 7. 계정 삭제/비활성화 정책

- `admin`이 사용자를 제거 → 기본은 **비활성화(deactivate)**: 로그인/토큰
  발급 차단만, 개인 org 포함 MemMachine 데이터는 유지.
- 완전 삭제(개인 org 및 MemMachine 데이터까지 연쇄 삭제)는 admin이 명시적
  실행하는 별도 명령(`memmachine-account admin purge-user --id <id>`)으로만, 되돌릴 수
  없음을 CLI에서 경고 후 확인받고 수행.

## 8. 회원관리 서버 자체 API (게이트웨이가 노출하는 control-plane API)

`/api/v2/*`(MemMachine 프록시)와 구분되는 자체 네임스페이스 `/account/v1/*`.

### 8.1 공통 규약

- **에러 포맷**: MemMachine 자체(`memmachine_server.server.api_v2.exceptions.RestError`)와
  동일한 봉투를 그대로 미러링한다 — `{"detail": {"code": int, "message": str,
  "exception": str|null, "internal_error": str|null, "trace": str|null}}`.
  프록시된 MemMachine 에러도 같은 모양이므로 CLI의 에러 처리 코드를 하나로
  통일할 수 있다.
- **인증 헤더**: `Authorization: Bearer <token>` (없거나 무효/폐기/소유자
  비활성 상태 → 401).
- **id 중복/미존재류 오류는 409/404, 형식 오류는 400, 권한 없음은 403**으로
  통일.
- 이메일 존재 여부를 외부에 흘리지 않기 위해 `reset-password/request`는
  이메일 존재 여부와 무관하게 항상 동일한 202 응답을 반환한다(사용자
  열거 공격 방지, 비용 낮은 기본기라 채택).

### 8.2 엔드포인트 상세

| 메서드/경로 | 인증 | 요청 바디 | 성공 응답 | 주요 에러 |
|---|---|---|---|---|
| `POST /account/v1/signup` | 불필요 | `{id, email, password}` | `201 {id, email, status:"pending_verification", personal_org_id}` | `400` id/password 형식, `403` 도메인 미허용, `409` id/email 중복 |
| `POST /account/v1/verify-email` | 불필요 | `{id, code}` | `200 {status:"active"}` | `400` 코드 불일치/만료, `404` id 없음 |
| `POST /account/v1/resend-code` | 불필요 | `{id}` | `202 {message}` | `409` 재발급 가능한 대기 상태 아님(`pending_verification`/`locked`이 아닌 경우) — 서버가 현재 `status`로 목적(signup_verification/lockout_reset)을 판단, 클라이언트가 purpose를 지정하지 않음 |
| `POST /account/v1/login` | 불필요 | `{id, password}` | `200 {token, user:{id,email,is_admin,status}}` (token은 이 응답에서만 원문 노출) | `401` 자격증명 불일치(계정 존재 여부 불문 동일 메시지), `423` locked, `403` pending_verification/deactivated |
| `POST /account/v1/logout` | 토큰 | (없음) | `204` | `401` |
| `POST /account/v1/reset-password/request` | 불필요 | `{email}` | `202 {message}` (계정 존재 여부 무관 항상 동일) | — |
| `POST /account/v1/reset-password/confirm` | 불필요 | `{id, code, new_password}` | `200 {message}` | `400` 코드/비번 형식, `410` 코드 만료 |
| `POST /account/v1/unlock` | 불필요 | `{id, code, new_password}` | `200 {status:"active"}` | `400` 코드 불일치/만료, `409` locked 상태 아님 |
| `GET /account/v1/me` | 토큰 | — | `200 {id,email,is_admin,status,created_at,orgs:[{org_id,kind,role}]}` | `401` |
| `POST /account/v1/change-password` | 토큰 | `{current_password,new_password}` | `200 {message}` | `401` 현재 비번 불일치, `400` 새 비번 형식 |
| `GET /account/v1/tokens` | 토큰 | — | `200 {tokens:[{token_id,created_at,last_used_at}]}` (원문 미노출) | `401` |
| `DELETE /account/v1/tokens/{token_id}` | 토큰 | — | `204` | `404` 본인 소유 아님/없음 |
| `POST /account/v1/orgs` | 토큰 | `{org_id}` | `201 {org_id,kind:"shared",role:"owner"}` | `400` 형식, `409` 이미 존재(개인 org_id와 충돌 포함, §4 참고) |
| `GET /account/v1/orgs` | 토큰 | — | `200 {orgs:[{org_id,kind,role}]}` | `401` |
| `POST /account/v1/orgs/{org_id}/members` | 토큰(owner) | `{user_id, role?:"owner"\|"member"=member}` | `201 {org_id,user_id,role}` | `400` 개인 org 대상, `403` owner 아님, `404` user_id 없음, `409` 이미 멤버 |
| `DELETE /account/v1/orgs/{org_id}/members/{user_id}` | 토큰(owner) | — | `204` | `400` 개인 org, `403` owner 아님, `404` 멤버 아님, `409` 마지막 owner 보호 |
| `POST /account/v1/orgs/{org_id}/leave` | 토큰(멤버) | — | `204` | `400` 개인 org(탈퇴 불가), `404` 멤버 아님, `409` 마지막 owner 보호 |
| `GET /account/v1/orgs/{org_id}/members` | 토큰(멤버) | — | `200 {members:[{user_id,role}]}` (개인 org는 본인 1명 `role:"owner"`) | `403` 멤버 아님 |
| `POST /account/v1/orgs/{org_id}/members/{user_id}/set-role` | 토큰(owner) | `{role:"owner"\|"member"}` | `200 {org_id,user_id,role}` | `400` 개인 org, `403` owner 아님, `404` 멤버 아님, `409` 마지막 owner를 member로 강등 시도 |
| `POST /account/v1/change-email` | 토큰 | `{new_email}` | `202 {message}` (기존 email은 유지, `pending_email`에 임시 저장) | `400` 도메인 미허용, `409` 다른 계정이 이미 사용 중 |
| `POST /account/v1/change-email/confirm` | 토큰 | `{code}` | `200 {email}` (`pending_email`이 `email`로 교체) | `400` 코드 불일치/만료 |
| `GET /account/v1/admin/users` | 토큰(admin) | — | `200 {users:[{id,email,is_admin,status,created_at}]}` | `403` |
| `POST /account/v1/admin/users/{id}/deactivate` | 토큰(admin) | — | `200 {id,status:"deactivated"}` | `404`, `403` |
| `POST /account/v1/admin/users/{id}/purge` | 토큰(admin) | `{confirm_id}`(=`{id}`와 동일해야 함) | `200 {id,deleted_org_ids:[...]}` | `400` confirm_id 불일치, `404`, `403` |
| `POST /account/v1/admin/users/{id}/revoke-tokens` | 토큰(admin) | — | `200 {id,revoked_count}` | `404`, `403` |
| `POST /account/v1/admin/sync-seed-admins` | 토큰(admin) | — | `200 {promoted:[id,...], demoted:[id,...]}` | `403`, `409` 이 작업으로 admin이 0명이 되면 거부(최소 1명 보호) |
| `GET /account/v1/admin/orgs` | 토큰(admin) | — | `200 {orgs:[{org_id,kind,created_by,member_count}]}` | `403` |
| `GET /account/v1/health` | 불필요 | — | `200 {status:"healthy"}` | — |

Project 관련 엔드포인트는 별도로 만들지 않고 `/api/v2/projects*`
(MemMachine 프록시 경로, §2.1)를 그대로 사용 — 게이트웨이가 org 권한만
검사 후 포워딩, 응답/에러 모양은 MemMachine 것 그대로(§8.1 에러 포맷과
동일 계열이라 자연히 일관됨).

## 9. CLI 명령 체계 (`memmachine-account`)

기존 `mem-cli`/`memmachine`(packages/client/src/memmachine_client/cli.py)와
**동일한 argparse 컨벤션**을 그대로 따른다:

- 2단계 서브파서(`<noun> <verb>`)까지만 허용, 3단계 중첩 금지 (`config
  resources`처럼 명사 하나 더 붙는 경우는 예외). → `admin` 아래를
  `admin <verb>-<noun>` 형태로 평탄화(예: `admin list-users`).
- 식별자는 위치인자가 아니라 **`--xxx-id` 형태의 옵션**으로 받는다
  (기존 CLI의 `--org-id`/`--project-id`, `memory delete --id/--ids` 패턴
  미러링). 자유 텍스트만 위치인자로 받는다(예: 없음 — 이 CLI엔 자유 텍스트
  입력이 없음).
- **출력은 항상 JSON**(`print_json`과 동일한 스타일: 들여쓰기 2칸, 키
  정렬, 안정적 출력). 별도 `--json`/테이블 모드 플래그 없음 — 기존 CLI와
  동일하게 통일.
- **에러**: `{prog}: error: <message>`를 stderr에 출력하고 종료 코드 2
  (`_die` 패턴 그대로).
- **비밀번호류(`password`, `new_password`, `current_password`)는 절대
  플래그로 받지 않는다** — 항상 `getpass`로 숨김 입력 프롬프트. `--api-key`
  플래그처럼 고정 자격증명을 매번 넘기는 기존 CLI 관례와 달리, 로그인
  비밀번호는 매 세션 사람이 직접 타이핑하는 비밀값이라 쉘 히스토리/프로세스
  목록 노출을 피하기 위해 의도적으로 다르게 간다.

### 9.1 전역 옵션 / 환경변수

기존 CLI가 `MEMMACHINE_*` 환경변수를 쓰므로, 이름 충돌을 피하려고
**`MEMMACHINE_ACCOUNT_*`**로 네임스페이스를 분리한다(같은 쉘에서 두 CLI를
같이 써도 서로 값이 섞이지 않게).

| 옵션 | 환경변수 | 기본값 | 설명 |
|---|---|---|---|
| `--base-url` | `MEMMACHINE_ACCOUNT_URL` | `http://localhost:8090` | 게이트웨이 주소 |
| `--token` | `MEMMACHINE_ACCOUNT_TOKEN` | (로그인 시 저장된 파일값) | 토큰 수동 지정(스크립트/CI용, 있으면 로컬 저장 토큰보다 우선) |
| `--credentials-file` | `MEMMACHINE_ACCOUNT_CREDENTIALS_FILE` | `~/.config/memmachine-account/credentials` | 로그인 토큰 저장 위치 |

### 9.2 명령 목록 (옵션 포함)

```
memmachine-account signup --id <id> --email <email>
    # password는 프롬프트. 성공 시 "6자리 코드가 <email>로 발송됨" 안내만 출력(코드 자체는 미출력)

memmachine-account verify --id <id> --code <code>
memmachine-account resend-code --id <id>
    # status가 pending_verification/locked일 때만 동작. password_reset/email_change 코드는
    # 대신 각각 `reset-password request`/`change-email request`를 다시 호출해서 재발급.

memmachine-account login --id <id>
    # password는 프롬프트. 성공 시 token을 --credentials-file에 저장, stdout에는 {id,email,is_admin,status}만 JSON 출력(토큰 원문은 파일에만)

memmachine-account logout

memmachine-account whoami

memmachine-account change-password
    # current_password, new_password 둘 다 프롬프트

memmachine-account change-email request --email <new_email>
memmachine-account change-email confirm --code <code>

memmachine-account reset-password request --email <email>

memmachine-account reset-password confirm --id <id> --code <code>
    # new_password는 프롬프트

memmachine-account unlock --id <id> --code <code>
    # new_password는 프롬프트

memmachine-account token list
memmachine-account token revoke --token-id <token_id>

memmachine-account org create --org-id <org_id>
memmachine-account org list
memmachine-account org members --org-id <org_id>
memmachine-account org add-member --org-id <org_id> --user-id <user_id> [--role owner|member]   # 기본 member
memmachine-account org remove-member --org-id <org_id> --user-id <user_id>
memmachine-account org set-role --org-id <org_id> --user-id <user_id> --role owner|member
memmachine-account org leave --org-id <org_id>

memmachine-account project create --org-id <org_id> --project-id <project_id> [--description <text>]
memmachine-account project list [--org-id <org_id>]
memmachine-account project get --org-id <org_id> --project-id <project_id>
memmachine-account project episode-count --org-id <org_id> --project-id <project_id>
memmachine-account project delete --org-id <org_id> --project-id <project_id> [--yes]
    # --yes 없으면 "삭제하려면 project_id를 다시 입력하세요: " 프롬프트로 재확인.
    # MemMachine 메모리까지 영구 삭제됨을 사전에 경고 문구로 표시.

memmachine-account admin list-users
memmachine-account admin deactivate-user --id <id>
memmachine-account admin purge-user --id <id> [--yes]
    # --yes 없으면 "완전 삭제하려면 id를 다시 입력하세요: " 프롬프트. 되돌릴 수 없음 경고.
    # 재입력받은 값을 API의 confirm_id로 그대로 전달(별도 --confirm-id 플래그 없음).
    # project delete와 달리 이 엔드포인트는 우리 소유라 confirm_id를 서버 쪽에서도
    # 한 번 더 검증(이중 방어). project delete는 MemMachine 프록시라 서버 측 confirm
    # 필드를 추가할 수 없어 CLI 재입력 프롬프트가 유일한 안전장치.
memmachine-account admin revoke-tokens --id <id>
memmachine-account admin list-orgs
memmachine-account admin sync-seed-admins

memmachine-account health
```

## 10. 설정 파일(config) 스키마 예시

`memmachine-account-server`는 `MEMMACHINE_ACCOUNT_CONFIG` 환경변수(기본값
`~/.config/memmachine-account/config.yml`, 컨테이너에서는 보통
`/config/account.yml`로 마운트)로 지정된 YAML 파일을 읽는다 — MemMachine
서버가 `~/.config/memmachine/.env`를 찾는 방식과 같은 결.

```yaml
server:
  host: 0.0.0.0
  port: 8090
  workers: 1              # SQLite 특성상 v1은 1로 고정 권장. >1은 WAL 모드 필요(비공식, 미검증)

logging:                  # MemMachine cfg.yml의 logging: 섹션과 동일한 결
  level: info             # debug | info | warning | error | critical
  format: "%(asctime)s [%(levelname)s] %(name)s - %(message)s"

memmachine_upstream:
  base_url: http://memmachine:8080   # 프록시 대상 (docker network 내부)
  timeout_seconds: 30                # MemMachine 응답 대기 한도, 초과 시 504

storage:
  sqlite_path: /data/memmachine-account.db

auth:
  allowed_email_domains:
    - company.com          # '@' 뒷부분과 대소문자 무시 정확히 일치(서브도메인 자동 포함 안 됨 — 필요하면 별도로 나열)
  seed_admins:
    - admin@company.com
  password_min_length: 8
  failed_login_lockout_threshold: 5   # 연속 로그인 실패 허용 횟수 (§5/§6 "5회"가 이 값)
  email_code_length: 6                # 인증/재설정/잠금해제 코드 자릿수 (§5 "6자리"가 이 값)
  email_code_expiry_minutes: 30       # 모든 EmailChallenge purpose 공통 만료시간(§5 "30분"이 이 값)

smtp:
  host: smtp.company.com
  port: 587
  username: notifications@company.com
  password: <SMTP_PASSWORD>
  from_address: memmachine-noreply@company.com
  encryption: starttls    # starttls(587 관례) | ssl(465 관례, 암시적 TLS) | none
  timeout_seconds: 10      # 메일 발송 자체의 타임아웃. 초과/발송 실패 시 해당 API 호출은 500으로 실패
                            # (조용히 무시하지 않음 — 코드가 발송 안 됐는데 pending 상태로 방치되는 상황 방지)
```

**config에 없는 것(의도적으로 하드코딩, 코드 상수)**:
- §2.1의 v1 프록시 허용/차단 엔드포인트 목록 — config로 노출하면 운영자가
  실수로 opaque-ID 엔드포인트(§2.1 차단 대상)를 열어버릴 수 있어, 보안
  경계는 코드 레벨 상수로만 고정하고 config로는 건드릴 수 없게 한다.
- 비밀번호 해시 알고리즘(argon2id 고정), 토큰 만료 정책(무만료 고정),
  코드 재발급 쿨다운(없음 고정) — 모두 §18 요약에 정리된 고정 설계로,
  잘못 바꾸면 보안/정합성이 깨지는 값이라 config 스위치를 두지 않는다.

## 11. 배포

- 저장소: 회원관리 서버 자체 **SQLite** (`/data/memmachine-account.db`,
  §10 config의 `storage.sqlite_path`).
- 배포 대상: **Docker Compose만** (Helm/K8s 범위 밖).
- 실제 저장소 루트 `docker-compose.yml`을 직접 확인한 결과(서비스:
  `postgres`, `neo4j`, `memmachine`, `docs`; 네트워크 `memmachine-network`
  단일 bridge; 볼륨은 `<name>_data`/`<name>_logs`, `driver: local`)를
  기준으로 아래처럼 병합한다.
- **기존 파일에서 실제로 바뀌는 부분은 `memmachine` 서비스의 `ports:` 제거뿐이다**
  (§2 결정: MemMachine 포트는 compose 네트워크 내부에만 노출, `account`만
  공개 포트 보유). 이건 동작 변경이므로 명확히 표시함 — 지금까지
  `localhost:8080`으로 MemMachine에 직접 붙던 사용자는 이후 반드시
  `account` 게이트웨이(기본 8090)를 거쳐야 한다.
- `account` 서비스는 새 `Dockerfile.account`(저장소 루트, `Dockerfile`과
  같은 컨텍스트)로 빌드한다. `packages/account`는 다른 워크스페이스
  패키지에 의존하지 않지만, uv workspace/`uv.lock`을 그대로 재사용하려면
  빌드 컨텍스트는 저장소 루트여야 한다(`docs`처럼 서브디렉터리 자체를
  컨텍스트로 못 씀).

```yaml
# 저장소 루트 Dockerfile.account (기존 루트 Dockerfile의 uv 빌드 패턴 재사용,
# NLTK 다운로드·GPU 분기는 memmachine-server 전용이라 제외)
FROM python:3.12-slim-trixie AS builder
RUN apt-get update && apt-get upgrade -y && apt-get install -y curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --upgrade pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
ARG SCM_VERSION="0.0.0"
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SCM_VERSION}
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package memmachine-account --no-install-workspace --no-editable --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package memmachine-account --no-editable --no-dev

FROM python:3.12-slim-trixie AS final
RUN apt-get update && apt-get upgrade -y && apt-get install -y curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV HOST=0.0.0.0
EXPOSE 8090
CMD ["sh", "-c", "memmachine-account-server"]
```

```yaml
# docker-compose.yml — 전체(기존 서비스 + account 신설), 변경분은 <<< 주석 표시
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: memmachine-postgres
    restart: unless-stopped
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-memmachine}
      POSTGRES_USER: ${POSTGRES_USER:-memmachine}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-memmachine_password}
      POSTGRES_INITDB_ARGS: "--encoding=UTF-8 --lc-collate=C --lc-ctype=C"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-memmachine} -d ${POSTGRES_DB:-memmachine}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - memmachine-network

  neo4j:
    image: neo4j:5.23-community
    container_name: memmachine-neo4j
    restart: unless-stopped
    ports:
      - "${NEO4J_HTTP_PORT:-7474}:7474"
      - "${NEO4J_HTTPS_PORT:-7473}:7473"
      - "${NEO4J_PORT:-7687}:7687"
    environment:
      NEO4J_EDITION: community
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-neo4j_password}
      NEO4J_server_bolt_thread__pool__max__size: 2000
      NEO4J_server_memory_heap_initial__size: 512m
      NEO4J_server_memory_heap_max__size: 1G
      NEO4J_server_default__listen__address: 0.0.0.0
      NEO4J_server_bolt_listen__address: 0.0.0.0:7687
      NEO4J_server_http_listen__address: 0.0.0.0:7474
      NEO4J_server_https_listen__address: 0.0.0.0:7473
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - neo4j_import:/var/lib/neo4j/import
      - neo4j_plugins:/plugins
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "${NEO4J_USER:-neo4j}", "-p", "${NEO4J_PASSWORD:-neo4j_password}", "RETURN 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s
    networks:
      - memmachine-network

  memmachine:
    image: ${MEMMACHINE_IMAGE:-memmachine/memmachine}
    pull_policy: ${PULL_POLICY:-always}
    container_name: memmachine-app
    restart: unless-stopped
    # <<< ports: 제거됨 — 더 이상 호스트에 직접 노출하지 않음, account 게이트웨이만 통과
    environment:
      POSTGRES_HOST: ${POSTGRES_HOST:-postgres}
      POSTGRES_PORT: ${POSTGRES_PORT:-5432}
      POSTGRES_USER: ${POSTGRES_USER:-memmachine}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-memmachine_password}
      POSTGRES_DB: ${POSTGRES_DB:-memmachine}
      NEO4J_HOST: ${NEO4J_HOST:-neo4j}
      NEO4J_PORT: ${NEO4J_PORT:-7687}
      NEO4J_USER: ${NEO4J_USER:-neo4j}
      NEO4J_PASSWORD: ${NEO4J_PASSWORD:-neo4j_password}
      MEMORY_CONFIG: ${MEMORY_CONFIG:-/app/configuration.yml}
      MCP_BASE_URL: ${MCP_BASE_URL:-http://memmachine:8080}
      GATEWAY_URL: ${GATEWAY_URL:-http://localhost:8080}
      FAST_MCP_LOG_LEVEL: ${FAST_MCP_LOG_LEVEL:-INFO}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      MEMMACHINE_WORKERS: ${MEMMACHINE_WORKERS:-1}
      MEMMACHINE_CONFIG_API: ${MEMMACHINE_CONFIG_API:-}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      HOST: 0.0.0.0
    volumes:
      - ./configuration.yml:/app/configuration.yml:rw,Z
      - memmachine_logs:/tmp/memory_logs
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "--fail", "--silent", "http://localhost:8080/api/v2/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    networks:
      - memmachine-network
    extra_hosts:
      - "host.docker.internal:host-gateway"

  # <<< 신설
  account:
    build:
      context: .
      dockerfile: Dockerfile.account
    container_name: memmachine-account
    restart: unless-stopped
    ports:
      - "${MEMMACHINE_ACCOUNT_PORT:-8090}:8090"
    environment:
      MEMMACHINE_ACCOUNT_CONFIG: /config/account.yml
    volumes:
      - ./account.yml:/config/account.yml:ro,Z
      - account_data:/data
    depends_on:
      memmachine:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "--fail", "--silent", "http://localhost:8090/account/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - memmachine-network

  docs:
    build:
      context: docs/
      dockerfile: Dockerfile
    ports:
      - "${DOCS_PORT:-3000}:3000"
    volumes:
      - ./docs:/docs:ro,Z

volumes:
  postgres_data:
    driver: local
  neo4j_data:
    driver: local
  neo4j_logs:
    driver: local
  neo4j_import:
    driver: local
  neo4j_plugins:
    driver: local
  memmachine_logs:
    driver: local
  account_data:          # <<< 신설
    driver: local

networks:
  memmachine-network:
    driver: bridge
    name: memmachine-network
```

`account.yml`(§10 스키마)은 `memmachine`의 `configuration.yml`처럼 저장소
루트에 사용자가 직접 만들어 두는 파일이며, `memmachine_upstream.base_url`은
`http://memmachine:8080`(compose 네트워크 내부 서비스명)으로 설정한다.

## 12. 패키징 / 코드 위치

기존 저장소 컨벤션(직접 확인, `pyproject.toml` / `packages/{client,common,server}`)의
빌드 방식(**uv workspace**, `src/` 레이아웃, `setuptools`+`setuptools-scm`
빌드, `[project.scripts]` 콘솔 진입점, `<name>_tests/` + pytest,
ruff(`extend = "../../pyproject.toml"`) + `ty` 타입체크)은 그대로 따르되,
**패키지는 3분할하지 않고 단일 패키지**로 둔다 — 작은 내부 도구 특성상
관리 포인트를 최소화하는 쪽을 택함(서버 설치자든 CLI 사용자든 동일 패키지
하나만 알면 됨. 대신 CLI만 쓰려는 사람도 FastAPI/SQLAlchemy 등 서버
의존성을 함께 설치하게 되는 점은 트레이드오프로 받아들임).

| 패키지 디렉터리 | 배포명 | 임포트 패키지 |
|---|---|---|
| `packages/account` | `memmachine-account` | `memmachine_account` |

내부 모듈 구성(제안, `memmachine_server`/`memmachine_client` 레이아웃 미러링):

```
packages/account/
  pyproject.toml
  src/memmachine_account/
    __init__.py
    api/
      spec.py           # /account/v1/* 요청·응답 pydantic 모델 (memmachine_common/api/spec.py 네이밍 미러링)
      doc.py             # 엔드포인트 설명 문자열 모음 (memmachine_common/api/doc.py 미러링)
    server/
      app.py            # FastAPI 게이트웨이 앱 (§2, §8 구현)
      middleware.py      # access-log 미들웨어 (memmachine_server 패턴 미러링)
      auth.py            # 인증/토큰/잠금 로직
      orgs.py             # org/멤버십 로직
      proxy.py            # §2.1 허용목록 기반 MemMachine 프록시 + 권한검사
      storage.py           # SQLAlchemy 모델/세션 (SQLite)
      mail.py               # SMTP 발송
    cli/
      __init__.py
      main.py            # `memmachine-account` 진입점
      commands/            # signup/login/org/project/admin 서브커맨드
  account_tests/
    ...                   # 단위/통합 테스트 (§14)
```

콘솔 스크립트 (`memmachine-server = "memmachine_server.server.app:main"` 패턴 미러링):

```toml
# packages/account/pyproject.toml
[project.scripts]
memmachine-account = "memmachine_account.cli.main:main"
memmachine-account-server = "memmachine_account.server.app:main"
```

`root pyproject.toml`에 두 군데 추가 (기존 3개 패키지와 동일한 패턴):
```toml
[tool.uv.workspace]
members = ["packages/client", "packages/common", "packages/server", "packages/account"]

[tool.uv.sources]
memmachine-account = { workspace = true }
```

재사용 대상(기존 코드에서 확인됨):
- FastAPI 앱 구성 패턴: `packages/server/src/memmachine_server/server/app.py`
  (`FastAPI` 서브클래스 + `add_exception_handler` + 미들웨어 등록 방식)
- 미들웨어 패턴: `packages/server/src/memmachine_server/server/middleware.py`
  (`AccessLogMiddleware`, `RequestMetricsMiddleware` — account-server도 동일
  패턴의 access-log 미들웨어를 둔다)
- CLI 진입점 패턴: `packages/client/src/memmachine_client/cli.py`
- pydantic 요청/응답 모델 분리 패턴: `packages/common/src/memmachine_common/api/spec.py`
- 프록시 대상 HTTP 클라이언트: `httpx`(비동기, FastAPI와 궁합 좋음)를 새 의존성으로 추가

## 13. 헬스체크 / 로깅

- account-server는 `GET /account/v1/health`(인증 불필요)를 노출 —
  docker-compose healthcheck 대상. MemMachine 자체 `/health`와는 별개.
- 요청 접근 로그는 MemMachine의 `AccessLogMiddleware`와 동일한 패턴으로
  stdout에 구조화 로그 출력(컨테이너 로그 수집 전제).
- 감사 로그(누가 언제 어떤 org/project를 호출했는지)는 §4의 `AuditLog`
  테이블에 남긴다(§15 요청 처리 파이프라인에서 기록 시점 명시).

## 14. 테스트 계획

기존 컨벤션 미러링: `packages/account/account_tests/` + pytest, 서버·CLI를
하위 디렉터리로 구분(`account_tests/server/`, `account_tests/cli/`).
**구현과 테스트는 마일스톤 단위로 함께 진행**(§16) — 여기 나열된 케이스는
해당 기능을 구현하는 마일스톤에서 바로 같이 작성한다(전부 구현 후 맨
마지막에 몰아서 작성하지 않음).

### 14.1 서버 단위 테스트 (MemMachine은 `respx`/`httpx` mock으로 대체)

**인증**
- 가입 성공 → `pending_verification` + 개인 org 자동 생성
- 가입 실패: id 형식 위반(특수문자 시작/끝·연속·`_` 포함), 이메일 도메인
  미허용(403), id 중복(409), email 중복(409)
- `verify`: 코드 일치→active, 불일치(400), 만료(400, `email_code_expiry_minutes` 경과)
- `resend-code`: pending_verification/locked에서만 동작(그 외 409), 재발급 시 이전 코드 무효화
- 로그인 성공 → 토큰 발급, `failed_login_count` 리셋
- 로그인 실패 누적 → `failed_login_lockout_threshold`(기본 5)회째 `locked` 전환,
  `password_hash` 랜덤화, **기존 토큰은 유지되는지 확인**
- `locked` 상태: 맞는 비밀번호로도 로그인 거부(423)
- `pending_verification`/`deactivated` 상태 로그인 거부(403)
- `unlock`: 정상 복귀, `locked` 아닌 상태에서 호출 시 409
- `change-password`: 현재 비번 불일치(401), 새 비번 길이 미달(400)
- `reset-password/request`: 존재하지 않는 이메일이어도 응답이 완전히
  동일한지(타이밍·바디 — 사용자 열거 방지 검증)
- `change-email/request`→`confirm`: 확인 전까지 `email` 불변, 도메인
  미허용(400), 타 계정 사용 중인 이메일(409)

**토큰**
- revoke된 토큰 → 401
- **소유자 `status != active`인(아직 revoke 안 된) 토큰 → 401** (§4 핵심 로직, 반드시 검증)
- `token list` 응답에 토큰 원문이 없는지
- 타인 토큰 id로 revoke 시도 → 404

**org/멤버십**
- org 생성 정상/충돌(다른 사용자 개인 org_id와 우연히 겹치는 실제 케이스, §4)
- 개인 org 대상 add-member/remove-member/set-role/leave → 전부 400
- 존재하지 않는 user_id add-member → 404
- 마지막 owner: remove-member/set-role(강등)/leave 전부 409
- 정상 owner→member 강등(다른 owner 존재) → 200
- 개인 org members 조회 → 본인 1명, role owner

**권한 검사/프록시(§2.1)**
- 허용목록 엔드포인트: 멤버 org(200, mock 호출 확인) / 비멤버 org(403) /
  org_id·project_id 생략 또는 `"universal"`(400)
- 차단목록 엔드포인트(§2.1 X표 전부): 어떤 토큰으로도 404/501
- `/projects/list`: 여러 org 섞인 MemMachine 응답에서 비멤버 org 항목이
  실제로 걸러지는지
- `producer_id`/`produced_for_id`: 임의 값이 변조 없이 그대로 전달되는지

**admin**
- 비-admin의 admin 엔드포인트 호출 → 403
- `deactivate` 이후 그 사용자의 기존 토큰 → 401 (토큰 유효성 로직과 연결 확인)
- `purge`: confirm_id 불일치(400), 성공 시 MemMachine project 삭제 호출까지 mock으로 검증
- `revoke-tokens`: 실행 후 해당 계정 모든 토큰 401
- `sync-seed-admins`: 승격+강등 동시 케이스, 결과적으로 admin 0명이 되면 거부(409)

**감사 로그**: 성공/실패 케이스 모두 `AuditLog`에 기대 필드로 기록되는지

### 14.2 서버 통합 테스트

- 실제 `memmachine-server`를 테스트 설정으로 같이 띄워 smoke test 최소 1세트:
  signup → verify → login → org create → project create → (memmachine
  client로 직접) memory add/search → project delete 전체 왕복.
  기존 저장소가 이미 쓰는 `testcontainers` 방식 재사용 검토(SQLite 자체는
  불필요, MemMachine 쪽 의존성만 해당).

### 14.3 CLI 테스트

기존 `packages/client/client_tests/test_cli.py` 패턴 미러링, HTTP 계층 mock.
- 각 명령 인자 파싱 및 `--credentials-file` 저장/로드
- JSON 출력 스키마, 에러 시 `{prog}: error: ...` + exit code 2
- **비밀번호가 프로세스 인자 목록에 절대 노출되지 않는지**(항상 프롬프트인지 검증)
- `project delete`/`admin purge-user`의 `--yes` 유무에 따른 확인 프롬프트 동작

## 15. 요청 처리 파이프라인 (SW 설계)

### 15.1 프록시 대상 요청(§2.1 허용목록)

```
1. Authorization: Bearer <token> 파싱 (없으면 401)
2. 토큰 조회: revoke_at IS NULL AND user.status == 'active' (아니면 401)
3. 요청 경로가 §2.1 허용목록에 있는지 확인 (없으면 404/501 — 차단목록)
4. 요청 바디에서 org_id/project_id 추출 (없거나 'universal' 기본값 의존 → 400)
5. 권한 확인: user가 해당 org의 멤버(personal 소유자 포함)인지 (아니면 403)
6. MemMachine으로 그대로 포워딩 (httpx, timeout_seconds 적용)
7. (POST /projects/list에 한해) 응답 바디를 호출자 접근 가능 org로 필터링
8. AuditLog 기록 (user_id, method, path, org_id, project_id, status_code)
9. 응답 반환 (MemMachine 에러 포맷 그대로 pass-through)
```

### 15.2 control-plane 요청(`/account/v1/*`)

```
1. 인증 불필요 엔드포인트(signup/login/verify-email/resend-code/
   reset-password/unlock/health)는 2 생략
2. Authorization 파싱 + 토큰 유효성(위와 동일 규칙)
3. 엔드포인트별 인가 확인 (admin 전용 / org owner 전용 / org 멤버 전용 등, §8.2)
4. 비즈니스 로직 실행 (auth.py/orgs.py, §12 모듈 구성)
5. AuditLog 기록 (org_id/project_id는 해당 없으면 비움)
6. §8.1 에러 포맷으로 응답
```

## 16. 구현 계획 (마일스톤 — 구현·테스트 반복)

**원칙: 각 마일스톤은 "구현 + 그 범위의 테스트"를 한 세트로 끝낸다.**
다음 마일스톤은 이전 마일스톤의 테스트가 전부 그린 상태에서만 시작한다
(끝에 몰아서 테스트하지 않음).

| # | 마일스톤 | 구현 범위 | 함께 끝내는 테스트(§14 대응) |
|---|---|---|---|
| 1 | 스캐폴딩 + 스토리지 | `packages/account` 골격(§12), SQLAlchemy 모델 6종, SQLite 초기화, root workspace 등록 | 모델 제약조건(유니크/충돌) 테스트 |
| 2 | 인증 코어 | signup/verify/resend-code/login/logout/change-password/reset-password/unlock/change-email, argon2 해시, EmailChallenge, SMTP 발송(§10) | §14.1 "인증" 전체 |
| 3 | 토큰 | 토큰 발급/조회/폐기, "revoke 안 됨 AND status==active" 검사 로직 | §14.1 "토큰" 전체 |
| 4 | org/멤버십 | create/list/members/add-member/remove-member/set-role/leave, 마지막 owner 보호, 개인 org 예외처리 | §14.1 "org/멤버십" 전체 |
| 5 | 게이트웨이 프록시 | §2.1 허용/차단목록, 권한검사 미들웨어, `/projects/list` 응답 필터링, producer_id pass-through | §14.1 "권한 검사/프록시" 전체 |
| 6 | admin | list-users/deactivate/purge/revoke-tokens/sync-seed-admins(양방향)/list-orgs | §14.1 "admin" 전체 |
| 7 | 감사 로그 + 헬스체크 | `AuditLog` 기록 지점 전체 배선, `GET /account/v1/health` | §14.1 "감사 로그" |
| 8 | CLI | §9 명령 전체(signup~admin), 자격증명 파일 처리 | §14.3 전체 |
| 9 | 통합/배포 | 실제 memmachine-server 연동 smoke test, `Dockerfile.account`, `docker-compose.yml` 반영(§11) | §14.2 전체 |

## 17. OPEN (미정 — 계속 논의 필요)

- [x] ~~§2.1에서 v1 제외로 결정된 Semantic Memory 하위 리소스 API를 v2에서
      소유권 인덱스 방식으로 확장할지 여부~~ → **CLOSED.** 사용자가 추후
      직접 재검토 예정. v1 결정(§2.1, 제외)은 그대로 유지.

현재 열린 항목 없음. (v1 범위 내 세부사항은 §2~§16에서 이미 확정됨)

## 18. 지금까지 결정 요약 (빠른 참조)

| 항목 | 결정 |
|---|---|
| 런타임 역할 | 리버스 프록시/게이트웨이 |
| 인증 방식 | 비밀번호 로그인 + 발급 토큰(만료 없음, 수동 폐기만) |
| 저장소 | 자체 SQLite |
| 배포 | Docker Compose만, 평문 HTTP |
| 이메일 인증 | SMTP + 6자리 코드, 가입 즉시 활성화(admin 승인 없음) |
| 이메일 도메인 제한 | config 파일 하드코딩 allowlist |
| org 모델 | 개인 org(가입 시 자동, 멤버 관리 불가) + 공유 org(누구나 생성, 생성자=owner) |
| 권한 체계 | 전역 admin / 일반 사용자 + org owner/member |
| org-owner 권한 | project 생성/삭제, 기존 가입자 멤버 추가/제거 |
| project 권한 | org 멤버십 단위(= 세분화 없음) |
| producer_id/produced_for_id | 게이트웨이가 그대로 통과(강제 치환 없음) |
| v1 프록시 범위 | org_id/project_id가 요청에 직접 있는 엔드포인트만 (§2.1) |
| 서비스 계정 | v1 미지원 (사람 개인 토큰만) |
| CLI 구성 | 기존 memmachine CLI와 완전 별개 도구 |
| admin 부트스트랩/회수 | config seed-admin 이메일 목록, `sync-seed-admins`는 승격+강등 양방향(admin 0명 방지) |
| 계정 삭제 | 기본 비활성화만(데이터 유지), 완전삭제는 admin 별도 명령 |
| 로그인 잠금 | 5회 연속 실패 시 비밀번호 강제 랜덤화 + 이메일 재인증 필요, 기존 토큰은 유지 |
| 비밀번호 정책 | 최소 8자, argon2id 해시, 복잡도 규칙 없음 |
| id 문자 규칙 | 영문/숫자 + `-` `.` (`_` 불허), 시작/끝/연속 특수문자 금지, org_id 변환 시 `.`→`_`(단사라 개인-개인 충돌 불가능) |
| 패키징 위치 | `packages/account` 단일 신설 (서버+CLI 한 패키지, uv workspace 추가). 진입점 `memmachine-account`(CLI)/`memmachine-account-server`(게이트웨이) 2개 |
| CLI 실행 파일명 | `memmachine-account` |
| 이메일 코드 재발급 | 쿨다운 없음(재발급 시 이전 코드 무효화). signup/lockout은 `resend-code`, password_reset/email_change는 `request` 재호출 |
| 감사 로그 보존 | 무기한 보관, 별도 삭제 없음, `AuditLog` 테이블 |
| admin의 데이터 접근 | 불가 (admin은 계정/org 관리 전용, 멤버 아닌 org의 메모리 접근 불가) |
| org_id/project_id 기본값("universal") | 게이트웨이가 모든 요청에 명시 강제, 생략 시 거부 |
| 마지막 owner 보호 | org에 owner 0명 상태 불가, `org leave`는 마지막 owner면 거부 |
| 토큰 유효성 판정 | revoke 안 됨 AND 사용자 status==active 둘 다 필요 |
| 헬스체크 | `GET /account/v1/health` (인증 불필요, MemMachine `/health`와 별개) |
| 회원 검색 | 없음 — admin만 전체 사용자 조회 가능, org-owner는 상대 id를 사내 공지로 알아야 함 |
| 이메일 변경 | `change-email request/confirm`, 코드 확인 전까지 기존 email 유지(`pending_email`) |
| org 역할 변경 | `org set-role`(owner 전용), 마지막 owner 강등 시도는 409 |
| project 단건 조회 | `project get`, `project episode-count` (기존엔 create/list/delete만 있었음) |
| 프록시 허용목록(§2.1) | config 노출 안 함, 코드 상수로 고정(운영자 실수로 보안경계 완화 방지) |
| SMTP 암호화 방식 | `smtp.encryption: starttls\|ssl\|none` (587=starttls, 465=ssl 관례) |
| 업스트림/SMTP 타임아웃 | `memmachine_upstream.timeout_seconds`(504), `smtp.timeout_seconds`(발송 실패 시 500, 조용히 무시 안 함) |
| 워커 프로세스 수 | `server.workers: 1` 고정 권장(SQLite, >1은 WAL 필요·미검증) |
| 로깅 | `logging.level`/`logging.format`, MemMachine cfg.yml과 동일한 결 |
| docker-compose 변경점 | 기존 파일 중 `memmachine` 서비스의 `ports:`를 제거(breaking) + `account` 서비스/볼륨 신설. `postgres`/`neo4j`/`docs`는 무변경 |
| 빌드 방식 | 저장소 루트 `Dockerfile.account` 신설(기존 루트 `Dockerfile`의 uv 빌드 패턴 재사용, NLTK/GPU 제외), 빌드 컨텍스트는 루트(uv workspace 재사용 위해) |
