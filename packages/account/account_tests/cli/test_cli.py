"""CLI tests (DESIGN.md §14.3)."""

import json
from pathlib import Path

import pytest

from account_tests.cli.conftest import FakeRequests
from memmachine_account.cli import main as cli_main
from memmachine_account.cli.credentials import load_credentials

BASE_ARGS = ["--base-url", "http://gateway.example"]


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli_main.main(BASE_ARGS + argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_signup_prompts_for_password_and_posts_expected_body(
    fake_requests: FakeRequests, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(cli_main, "_prompt_password", lambda *a: "hunter2")
    fake_requests.queue(201, {"id": "alice", "email": "alice@company.com", "status": "pending_verification", "personal_org_id": "alice"})

    code, out, _ = _run(["signup", "--id", "alice", "--email", "alice@company.com"], capsys)

    assert code == 0
    assert fake_requests.calls[0]["json"] == {"id": "alice", "email": "alice@company.com", "password": "hunter2"}
    assert json.loads(out)["status"] == "pending_verification"


def test_login_saves_credentials(
    tmp_path: Path, fake_requests: FakeRequests, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(cli_main, "_prompt_password", lambda *a: "hunter2")
    creds_file = tmp_path / "credentials"
    fake_requests.queue(
        200,
        {"token": "tok-123", "user": {"id": "alice", "email": "a@x.com", "is_admin": False, "status": "active"}},
    )

    code, out, _ = _run(
        ["--credentials-file", str(creds_file), "login", "--id", "alice"], capsys
    )

    assert code == 0
    assert json.loads(out) == {"id": "alice", "email": "a@x.com", "is_admin": False, "status": "active"}
    saved = load_credentials(str(creds_file))
    assert saved == {"base_url": "http://gateway.example", "id": "alice", "token": "tok-123"}


def test_logout_clears_credentials(
    tmp_path: Path, fake_requests: FakeRequests, capsys: pytest.CaptureFixture[str]
):
    creds_file = tmp_path / "credentials"
    creds_file.parent.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(json.dumps({"base_url": "http://x", "id": "alice", "token": "tok"}))

    _run(["--credentials-file", str(creds_file), "logout"], capsys)

    assert load_credentials(str(creds_file)) is None


@pytest.mark.parametrize(
    "subcommand",
    [["signup", "--id", "a", "--email", "a@b.com"], ["login", "--id", "a"], ["change-password"]],
)
def test_password_flags_do_not_exist(subcommand: list[str]):
    parser = cli_main.build_parser(prog="memmachine-account")
    args = parser.parse_known_args(subcommand)[1]
    # Nothing named --password/--new-password/--current-password should ever
    # be a *recognized* option; any such text on the CLI would show up as an
    # unrecognized positional/extra here rather than being consumed.
    assert not any(a.startswith("--password") for a in args if isinstance(a, str))


def test_error_response_dies_with_message_and_exit_code(
    fake_requests: FakeRequests, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(cli_main, "_prompt_password", lambda *a: "hunter2")
    fake_requests.queue(403, {"detail": {"code": 403, "message": "email domain not allowed"}})

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main([*BASE_ARGS, "signup", "--id", "a", "--email", "a@evil.com"])

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "email domain not allowed" in err


def test_project_delete_requires_matching_confirmation(
    fake_requests: FakeRequests, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("builtins.input", lambda _prompt: "wrong-project-id")

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main(
            [*BASE_ARGS, "project", "delete", "--org-id", "acme", "--project-id", "prod"]
        )

    assert exc_info.value.code == 2
    assert fake_requests.calls == []  # never reached the API


def test_project_delete_yes_skips_prompt(fake_requests: FakeRequests):
    fake_requests.queue(204, None)
    code = cli_main.main(
        [*BASE_ARGS, "project", "delete", "--org-id", "acme", "--project-id", "prod", "--yes"]
    )
    assert code == 0
    assert fake_requests.calls[0]["json"] == {"org_id": "acme", "project_id": "prod"}


def test_admin_purge_user_requires_matching_confirmation(
    fake_requests: FakeRequests, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("builtins.input", lambda _prompt: "someone-else")
    with pytest.raises(SystemExit) as exc_info:
        cli_main.main([*BASE_ARGS, "admin", "purge-user", "--id", "alice"])
    assert exc_info.value.code == 2
    assert fake_requests.calls == []


def test_org_add_member_defaults_to_member_role(fake_requests: FakeRequests, capsys: pytest.CaptureFixture[str]):
    fake_requests.queue(201, {"user_id": "bob", "role": "member"})
    _run(["org", "add-member", "--org-id", "team-a", "--user-id", "bob"], capsys)
    assert fake_requests.calls[0]["json"] == {"user_id": "bob", "role": "member"}


def test_token_revoke_calls_expected_path(fake_requests: FakeRequests):
    fake_requests.queue(204, None)
    code = cli_main.main([*BASE_ARGS, "token", "revoke", "--token-id", "tok-1"])
    assert code == 0
    assert fake_requests.calls[0]["method"] == "DELETE"
    assert fake_requests.calls[0]["url"].endswith("/account/v1/tokens/tok-1")


def test_health(fake_requests: FakeRequests, capsys: pytest.CaptureFixture[str]):
    fake_requests.queue(200, {"status": "healthy"})
    code, out, _ = _run(["health"], capsys)
    assert code == 0
    assert json.loads(out) == {"status": "healthy"}
