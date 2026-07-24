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
