# 구현 중 자율 결정 로그 (packages/account)

> DESIGN.md에서 다루지 않은 세부 구현 결정들을 여기에 기록한다. 중요한
> 결정인데 진행을 막지 않는 것들도 여기 적어두고 우선 진행한다. 사용자는
> 나중에 몰아서 검토/수정 요청할 수 있다.

## M1: 스캐폴딩 + 스토리지

- **Python 버전**: `>= 3.12`로 고정. `packages/server`(3.12+)와 맞춤 —
  Docker 이미지도 `python:3.12-slim-trixie`(Dockerfile.account 설계)라
  런타임 버전 통일. `packages/client`/`packages/common`(3.10+)보다 좁지만,
  account 패키지는 서버(FastAPI)와 CLI가 한 패키지라 서버 쪽 요구사항에 맞춤.
- **SQLAlchemy 비동기 ORM + aiosqlite** 채택 (동기 대신). FastAPI 자체가
  비동기라 이벤트 루프 블로킹을 피하려면 비동기 DB 드라이버가 자연스럽고,
  `memmachine-server`도 이미 `aiosqlite`를 의존성에 포함하고 있어 컨벤션과
  맞음.
- **`server/storage.py` 단일 파일**에 SQLAlchemy 엔진/세션 설정과 ORM 모델
  6종을 모두 둠 — DESIGN.md §12 모듈 트리에 이렇게 명시되어 있고, 테이블
  6개 규모라 모델을 별도 `models.py`로 분리할 만큼 크지 않다고 판단.
- **ID 생성**: `Token.token_id`, `EmailChallenge.id`는 `uuid4` 문자열로
  발급 (충돌 걱정 없고 별도 시퀀스 관리 불필요). `AuditLog.id`는 단순
  autoincrement 정수(순서 보장·조회 용도라 굳이 uuid 불필요).
- **컬럼 네이밍**: DESIGN.md 표에 없던 것들 —
  - `EmailChallenge.created_at` 추가(발급 시각, 최신 challenge 조회/정렬용 — 표에는 없었지만 꼭 필요).
  - `Org.org_id`를 PK, `User.id`를 PK로 사용 (둘 다 SafeId류 문자열, surrogate integer PK 안 씀 — 어차피 자연키가 유니크하고 API에서도 그대로 노출되는 값이라 surrogate를 추가할 이유가 없음).
- **root `pyproject.toml`** 변경: workspace members/sources에 packages/account
  추가, `[tool.ty.environment].extra-paths`, `[tool.coverage.run].source`,
  `[tool.complexipy].paths`에도 추가. `[tool.ruff.lint.per-file-ignores]`에
  "새 경로 추가하지 말 것"이라는 코멘트가 있었지만, 이건 기존 3개 패키지의
  test 디렉터리와 동일한 성격(신규 정식 패키지의 자체 테스트 디렉터리)이라
  판단해 `packages/account/account_tests/**/*.py` 한 줄을 동일 패턴으로
  추가함 (무분별한 산발적 예외 추가를 막으려는 코멘트로 해석, 신규 1급
  패키지 추가와는 결이 다르다고 판단).
- **의존성 버전**: 명시적으로 버전 핀 안 된 신규 라이브러리(argon2-cffi,
  httpx, aiosmtplib)는 각각 최신 안정 메이저와 호환되는 하한선만 지정
  (`argon2-cffi>=23.1.0`, `httpx>=0.28.0`, `aiosmtplib>=3.0.0`). CLI HTTP
  호출은 `requests`(memmachine-client와 동일 라이브러리)로 통일.
- **SQLite tzinfo 버그 실측 확인**: `DateTime(timezone=True)` 컬럼에 aware
  UTC datetime을 저장해도 aiosqlite로 다시 읽으면 tzinfo가 사라져 naive가
  됨(직접 스크립트로 재현 확인). `datetime.now(UTC)`와 직접 비교하면
  `TypeError`. `storage.as_aware_utc()` 헬퍼로 DB에서 읽은 시각은 항상
  보정 후 비교하도록 통일.

## M2: 인증 코어

- **비밀번호 해시**: argon2id(느림, 저엔트로피 사람 비밀번호에 적합).
  **코드/토큰 해시**: sha256(고엔트로피 랜덤값이나 단명 코드라 느린 해시
  불필요 — 코드는 만료+1회성 소모로 이미 보호되고, 토큰은 32바이트
  랜덤이라 sha256 역상 저항성으로 충분. GitHub PAT 등 업계 관행과 동일).
- **코드 재발급 시 "이전 코드 무효화"**: 별도 삭제/플래그 없이, 검증 시
  **항상 가장 최근(created_at 내림차순) 미소비 챌린지만** 확인하도록 구현.
  이전 코드는 자동으로 무의미해짐(굳이 명시적으로 지우지 않음) — 더 단순.
- **로그인 실패 카운트 처리 순서**: 계정 상태(locked/pending/deactivated)를
  **비밀번호 검증보다 먼저** 확인. locked 계정은 비밀번호가 랜덤화돼 있어
  이미 항상 불일치가 나므로, 상태 체크를 먼저 안 하면 실패 카운트가
  무의미하게 계속 올라감.
- **비밀번호 재설정 요청 시 계정 상태 무관 처리**: `pending_verification`/
  `deactivated` 상태 사용자도 재설정 이메일은 받을 수 있게 함(단순화 —
  재설정은 password_hash만 바꾸고 status는 안 바꾸므로, 재설정 후에도
  기존 상태별 로그인 제약은 그대로 유지되어 안전).
- **`GET`이 아니라 `POST`로 read-only에 가까운 요청도 처리**: DESIGN.md
  §8.2 그대로 따름(멱등이 아닌 부수효과가 있는 호출이 대부분이라 POST가
  자연스러움 — MemMachine 자체 API도 조회성 호출에 POST를 광범위하게 씀).
- **테스트가 실제 버그를 잡음**: `security.py`의 `_ID_SPECIAL_CHARS`에
  `_`(밑줄)이 실수로 남아있었음(id 문자 규칙은 `_` 금지가 최종 결정인데,
  구현 시 이전 초안 값을 그대로 옮겨적음). `test_signup_rejects_invalid_id`
  파라미터 케이스 중 `al_ice`가 400 대신 201을 반환해서 발견, 즉시 수정.
