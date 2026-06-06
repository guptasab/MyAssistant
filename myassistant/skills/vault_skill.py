"""Vault skill — exposes encrypted vault to the agent."""
from __future__ import annotations

from myassistant.core import vault as v
from myassistant.core.registry import skill


@skill(name="vault_store",
       description=("Store a secret in the encrypted vault. Used for API tokens, "
                    "passwords, codes. Requires OLLIE_VAULT_PASSPHRASE env."),
       requires=["ollie_vault_passphrase"], sensitive=True)
def vault_store(name: str, value: str, kind: str = "secret", note: str = "") -> str:
    return v.store(name, value, kind, note)


@skill(name="vault_reveal",
       description="Reveal a stored secret by name. Sensitive — confirm with user first.",
       requires=["ollie_vault_passphrase"], sensitive=True)
def vault_reveal(name: str) -> str:
    return v.reveal(name)


@skill(name="vault_list",
       description="List vault item names + kinds (no values).")
def vault_list() -> str:
    items = v.list_items()
    if not items:
        return "(empty)"
    return "\n".join(f"{i['name']:<24} [{i['kind']}]  {i['note']}" for i in items)
