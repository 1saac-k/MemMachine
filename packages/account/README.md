# MemMachine Account

A reverse-proxy gateway and CLI (`memmachine-account`) that add user
accounts, organizations, and per-project access control in front of an
on-premise MemMachine deployment, which otherwise has no authentication of
its own. See [`DESIGN.md`](./DESIGN.md) for the full design (data model,
API/CLI spec, config schema, deployment) and [`DECISIONS.md`](./DECISIONS.md)
for implementation decisions not covered by the design doc.

## Installation

### Development installation

If you are working on the package locally inside the MemMachine monorepo,
install it from source:

```bash
pip install -e packages/account
```

## Running

```bash
# Gateway (proxies to MemMachine, requires MEMMACHINE_ACCOUNT_CONFIG)
memmachine-account-server

# CLI
memmachine-account signup --id alice --email alice@company.com
```
