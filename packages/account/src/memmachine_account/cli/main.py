"""`memmachine-account` CLI entry point (DESIGN.md §9).

Mirrors the conventions of `memmachine_client.cli`: argparse with
`<noun> <verb>` subcommands (2 levels max), `--xxx-id`-style options
instead of positional identifiers, always-JSON output, and
`{prog}: error: <message>` + exit code 2 on failure. Deliberately
diverges on one point: passwords are never accepted as flags, only via
hidden `getpass` prompts, since they are typed secrets rather than a
long-lived credential like an API key (DESIGN.md §9).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from memmachine_account.cli.client import AccountClient, AccountCliError
from memmachine_account.cli.credentials import (
    clear_credentials,
    load_credentials,
    save_credentials,
)

ENV_BASE_URL = "MEMMACHINE_ACCOUNT_URL"
ENV_TOKEN = "MEMMACHINE_ACCOUNT_TOKEN"
DEFAULT_BASE_URL = "http://localhost:8090"
DEFAULT_PROG = "memmachine-account"


def _die(message: str, *, prog: str = DEFAULT_PROG) -> None:
    sys.stderr.write(f"{prog}: error: {message}\n")
    raise SystemExit(2)


def print_json(value: object) -> None:
    """Print an object as stable, readable JSON (mirrors memmachine_client.cli.print_json)."""
    sys.stdout.write(f"{json.dumps(value, indent=2, sort_keys=True)}\n")


def _prompt_password(label: str = "Password") -> str:
    return getpass.getpass(f"{label}: ")


def build_client(args: argparse.Namespace) -> AccountClient:
    """Resolve base_url/token from flags, env vars, and the saved credentials file."""
    base_url = args.base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL
    token = args.token or os.environ.get(ENV_TOKEN)
    if token is None:
        saved = load_credentials(args.credentials_file)
        if saved is not None:
            token = saved["token"]
    return AccountClient(base_url=base_url, token=token)


def add_global_args(parser: argparse.ArgumentParser) -> None:
    """Add the base-url/token/credentials-file options shared by every command."""
    parser.add_argument("--base-url", help=f"Gateway URL. Defaults to ${ENV_BASE_URL}.")
    parser.add_argument(
        "--token", help=f"Bearer token (overrides saved login). Defaults to ${ENV_TOKEN}."
    )
    parser.add_argument("--credentials-file", help="Path to the saved-login credentials file.")


def build_parser(prog: str) -> argparse.ArgumentParser:
    """Build the full `memmachine-account` argument parser."""
    parser = argparse.ArgumentParser(prog=prog, description="MemMachine account management CLI")
    add_global_args(parser)
    parser.set_defaults(prog=parser.prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    signup = subparsers.add_parser("signup", help="Create a pending account.")
    signup.add_argument("--id", required=True)
    signup.add_argument("--email", required=True)

    verify = subparsers.add_parser("verify", help="Confirm a signup verification code.")
    verify.add_argument("--id", required=True)
    verify.add_argument("--code", required=True)

    resend = subparsers.add_parser("resend-code", help="Resend a pending signup/unlock code.")
    resend.add_argument("--id", required=True)

    login = subparsers.add_parser("login", help="Log in and save a token locally.")
    login.add_argument("--id", required=True)

    subparsers.add_parser("logout", help="Revoke the current token and clear saved login.")
    subparsers.add_parser("whoami", help="Show the current account and org memberships.")
    subparsers.add_parser("change-password", help="Change your password.")

    change_email = subparsers.add_parser("change-email", help="Change your email.")
    change_email_sub = change_email.add_subparsers(dest="change_email_command", required=True)
    change_email_request = change_email_sub.add_parser("request", help="Start an email change.")
    change_email_request.add_argument("--email", required=True)
    change_email_confirm = change_email_sub.add_parser("confirm", help="Confirm an email change.")
    change_email_confirm.add_argument("--code", required=True)

    reset_password = subparsers.add_parser("reset-password", help="Reset a forgotten password.")
    reset_password_sub = reset_password.add_subparsers(
        dest="reset_password_command", required=True
    )
    reset_password_request = reset_password_sub.add_parser(
        "request", help="Send a reset code."
    )
    reset_password_request.add_argument("--email", required=True)
    reset_password_confirm = reset_password_sub.add_parser(
        "confirm", help="Confirm a reset code."
    )
    reset_password_confirm.add_argument("--id", required=True)
    reset_password_confirm.add_argument("--code", required=True)

    unlock = subparsers.add_parser("unlock", help="Unlock a locked account.")
    unlock.add_argument("--id", required=True)
    unlock.add_argument("--code", required=True)

    token = subparsers.add_parser("token", help="Manage your own login tokens.")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_sub.add_parser("list", help="List your tokens.")
    token_revoke = token_sub.add_parser("revoke", help="Revoke one of your tokens.")
    token_revoke.add_argument("--token-id", required=True)

    org = subparsers.add_parser("org", help="Manage organizations.")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_create = org_sub.add_parser("create", help="Create a shared org.")
    org_create.add_argument("--org-id", required=True)
    org_sub.add_parser("list", help="List orgs you belong to.")
    org_members = org_sub.add_parser("members", help="List an org's members.")
    org_members.add_argument("--org-id", required=True)
    org_add_member = org_sub.add_parser("add-member", help="Add a member to a shared org.")
    org_add_member.add_argument("--org-id", required=True)
    org_add_member.add_argument("--user-id", required=True)
    org_add_member.add_argument("--role", default="member", choices=["owner", "member"])
    org_remove_member = org_sub.add_parser(
        "remove-member", help="Remove a member from a shared org."
    )
    org_remove_member.add_argument("--org-id", required=True)
    org_remove_member.add_argument("--user-id", required=True)
    org_set_role = org_sub.add_parser("set-role", help="Promote/demote a shared org member.")
    org_set_role.add_argument("--org-id", required=True)
    org_set_role.add_argument("--user-id", required=True)
    org_set_role.add_argument("--role", required=True, choices=["owner", "member"])
    org_leave = org_sub.add_parser("leave", help="Leave a shared org.")
    org_leave.add_argument("--org-id", required=True)

    project = subparsers.add_parser("project", help="Manage projects (proxied to MemMachine).")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_create = project_sub.add_parser("create", help="Create a project.")
    project_create.add_argument("--org-id", required=True)
    project_create.add_argument("--project-id", required=True)
    project_create.add_argument("--description", default="")
    project_list = project_sub.add_parser("list", help="List accessible projects.")
    project_list.add_argument("--org-id")
    project_get = project_sub.add_parser("get", help="Get one project.")
    project_get.add_argument("--org-id", required=True)
    project_get.add_argument("--project-id", required=True)
    project_episode_count = project_sub.add_parser(
        "episode-count", help="Get a project's episode count."
    )
    project_episode_count.add_argument("--org-id", required=True)
    project_episode_count.add_argument("--project-id", required=True)
    project_delete = project_sub.add_parser(
        "delete", help="Permanently delete a project and its memories."
    )
    project_delete.add_argument("--org-id", required=True)
    project_delete.add_argument("--project-id", required=True)
    project_delete.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    admin = subparsers.add_parser("admin", help="Admin-only account/org management.")
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)
    admin_sub.add_parser("list-users", help="List every registered user.")
    admin_deactivate = admin_sub.add_parser("deactivate-user", help="Deactivate a user.")
    admin_deactivate.add_argument("--id", required=True)
    admin_purge = admin_sub.add_parser("purge-user", help="Irreversibly delete a user.")
    admin_purge.add_argument("--id", required=True)
    admin_purge.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    admin_revoke = admin_sub.add_parser("revoke-tokens", help="Revoke all of a user's tokens.")
    admin_revoke.add_argument("--id", required=True)
    admin_sub.add_parser("list-orgs", help="List every org on the server.")
    admin_sub.add_parser("sync-seed-admins", help="Reconcile admins with the config seed list.")

    subparsers.add_parser("health", help="Check the gateway's health.")

    return parser


def _confirm_or_die(prompt_value: str, args: argparse.Namespace, *, prog: str) -> None:
    if args.yes:
        return
    typed = input(f"Type '{prompt_value}' to confirm, this cannot be undone: ")
    if typed != prompt_value:
        _die("confirmation did not match, aborted", prog=prog)


def run_command(client: AccountClient, args: argparse.Namespace) -> int:  # noqa: C901
    """Dispatch the parsed command to the gateway and print its JSON result."""
    command = args.command

    if command == "signup":
        password = _prompt_password()
        print_json(client.request("POST", "/account/v1/signup", {"id": args.id, "email": args.email, "password": password}))
    elif command == "verify":
        print_json(client.request("POST", "/account/v1/verify-email", {"id": args.id, "code": args.code}))
    elif command == "resend-code":
        print_json(client.request("POST", "/account/v1/resend-code", {"id": args.id}))
    elif command == "login":
        password = _prompt_password()
        result = client.request("POST", "/account/v1/login", {"id": args.id, "password": password})
        assert isinstance(result, dict)  # login always returns a JSON object
        save_credentials(
            {"base_url": client.base_url, "id": args.id, "token": str(result["token"])},
            args.credentials_file,
        )
        print_json(result["user"])
    elif command == "logout":
        client.request("POST", "/account/v1/logout")
        clear_credentials(args.credentials_file)
    elif command == "whoami":
        print_json(client.request("GET", "/account/v1/me"))
    elif command == "change-password":
        current = _prompt_password("Current password")
        new = _prompt_password("New password")
        print_json(
            client.request(
                "POST", "/account/v1/change-password",
                {"current_password": current, "new_password": new},
            )
        )
    elif command == "change-email":
        _run_change_email(client, args)
    elif command == "reset-password":
        _run_reset_password(client, args)
    elif command == "unlock":
        new_password = _prompt_password("New password")
        print_json(
            client.request(
                "POST", "/account/v1/unlock",
                {"id": args.id, "code": args.code, "new_password": new_password},
            )
        )
    elif command == "token":
        _run_token(client, args)
    elif command == "org":
        _run_org(client, args)
    elif command == "project":
        _run_project(client, args)
    elif command == "admin":
        _run_admin(client, args)
    elif command == "health":
        print_json(client.request("GET", "/account/v1/health"))
    else:
        _die("a command is required", prog=args.prog)
    return 0


def _run_change_email(client: AccountClient, args: argparse.Namespace) -> None:
    if args.change_email_command == "request":
        print_json(client.request("POST", "/account/v1/change-email/request", {"new_email": args.email}))
    else:
        print_json(client.request("POST", "/account/v1/change-email/confirm", {"code": args.code}))


def _run_reset_password(client: AccountClient, args: argparse.Namespace) -> None:
    if args.reset_password_command == "request":
        print_json(client.request("POST", "/account/v1/reset-password/request", {"email": args.email}))
    else:
        new_password = _prompt_password("New password")
        print_json(
            client.request(
                "POST", "/account/v1/reset-password/confirm",
                {"id": args.id, "code": args.code, "new_password": new_password},
            )
        )


def _run_token(client: AccountClient, args: argparse.Namespace) -> None:
    if args.token_command == "list":
        print_json(client.request("GET", "/account/v1/tokens"))
    else:
        client.request("DELETE", f"/account/v1/tokens/{args.token_id}")


def _run_org(client: AccountClient, args: argparse.Namespace) -> None:
    if args.org_command == "create":
        print_json(client.request("POST", "/account/v1/orgs", {"org_id": args.org_id}))
    elif args.org_command == "list":
        print_json(client.request("GET", "/account/v1/orgs"))
    elif args.org_command == "members":
        print_json(client.request("GET", f"/account/v1/orgs/{args.org_id}/members"))
    elif args.org_command == "add-member":
        print_json(
            client.request(
                "POST", f"/account/v1/orgs/{args.org_id}/members",
                {"user_id": args.user_id, "role": args.role},
            )
        )
    elif args.org_command == "remove-member":
        client.request("DELETE", f"/account/v1/orgs/{args.org_id}/members/{args.user_id}")
    elif args.org_command == "set-role":
        print_json(
            client.request(
                "POST", f"/account/v1/orgs/{args.org_id}/members/{args.user_id}/set-role",
                {"role": args.role},
            )
        )
    elif args.org_command == "leave":
        client.request("POST", f"/account/v1/orgs/{args.org_id}/leave")


def _run_project(client: AccountClient, args: argparse.Namespace) -> None:
    if args.project_command == "create":
        print_json(
            client.request(
                "POST", "/api/v2/projects",
                {"org_id": args.org_id, "project_id": args.project_id, "description": args.description},
            )
        )
    elif args.project_command == "list":
        body = {"org_id": args.org_id} if args.org_id else {}
        print_json(client.request("POST", "/api/v2/projects/list", body))
    elif args.project_command == "get":
        print_json(
            client.request(
                "POST", "/api/v2/projects/get", {"org_id": args.org_id, "project_id": args.project_id}
            )
        )
    elif args.project_command == "episode-count":
        print_json(
            client.request(
                "POST", "/api/v2/projects/episode_count/get",
                {"org_id": args.org_id, "project_id": args.project_id},
            )
        )
    elif args.project_command == "delete":
        sys.stderr.write(
            "warning: this permanently deletes all MemMachine memories under this project.\n"
        )
        _confirm_or_die(args.project_id, args, prog=args.prog)
        client.request(
            "POST", "/api/v2/projects/delete", {"org_id": args.org_id, "project_id": args.project_id}
        )


def _run_admin(client: AccountClient, args: argparse.Namespace) -> None:
    if args.admin_command == "list-users":
        print_json(client.request("GET", "/account/v1/admin/users"))
    elif args.admin_command == "deactivate-user":
        print_json(client.request("POST", f"/account/v1/admin/users/{args.id}/deactivate"))
    elif args.admin_command == "purge-user":
        sys.stderr.write("warning: this permanently deletes the account and all its data.\n")
        _confirm_or_die(args.id, args, prog=args.prog)
        print_json(
            client.request(
                "POST", f"/account/v1/admin/users/{args.id}/purge", {"confirm_id": args.id}
            )
        )
    elif args.admin_command == "revoke-tokens":
        print_json(client.request("POST", f"/account/v1/admin/users/{args.id}/revoke-tokens"))
    elif args.admin_command == "list-orgs":
        print_json(client.request("GET", "/account/v1/admin/orgs"))
    elif args.admin_command == "sync-seed-admins":
        print_json(client.request("POST", "/account/v1/admin/sync-seed-admins"))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for `memmachine-account`."""
    parser = build_parser(prog=Path(sys.argv[0]).name if argv is None else DEFAULT_PROG)
    args = parser.parse_args(argv)
    client = build_client(args)
    try:
        return run_command(client, args)
    except AccountCliError as exc:
        _die(str(exc), prog=args.prog)
        return 2  # unreachable, _die raises SystemExit; keeps type checkers happy


if __name__ == "__main__":
    raise SystemExit(main())
