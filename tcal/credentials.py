"""The app-specific password: system keyring -> ``password_cmd`` -> ``$TCAL_PASSWORD``."""

import os
import subprocess

import keyring
from keyring.errors import KeyringError

from tcal.config import AccountConfig

SERVICE = "tcal"
ENV_VAR = "TCAL_PASSWORD"


class CredentialsError(RuntimeError):
    pass


def get_password(account: AccountConfig) -> str | None:
    try:
        password = keyring.get_password(SERVICE, account.apple_id)
    except KeyringError:
        password = None
    if password:
        return password
    if account.password_cmd:
        result = subprocess.run(account.password_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise CredentialsError(f"password_cmd failed: {result.stderr.strip()}")
        if password := result.stdout.strip():
            return password
    return os.environ.get(ENV_VAR) or None


def store_password(apple_id: str, password: str) -> None:
    """Save in the system keyring; CredentialsError if there is no usable keyring."""
    try:
        keyring.set_password(SERVICE, apple_id, password)
    except KeyringError as e:
        raise CredentialsError(f"could not save to the keyring: {e}") from None
