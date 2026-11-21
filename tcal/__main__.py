"""Command line: ``tcal`` starts the TUI; ``tcal --demo`` uses sample data.

``tcal login`` stores the iCloud account, ``tcal sync`` syncs once and
``tcal calendars`` lists the account's calendars.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import click

from tcal import paths
from tcal.config import Config, ConfigError, load_config, save_apple_id
from tcal.credentials import CredentialsError, get_password, store_password
from tcal.providers.base import Provider


def connect(config: Config, apple_id: str | None = None, password: str | None = None) -> Provider:
    """The configured account's provider; ``apple_id``/``password`` override the config."""
    from tcal.providers.icloud import ICloudProvider

    account = config.account
    apple_id = apple_id or account.apple_id
    if not apple_id:
        raise click.ClickException("no account set up: run `tcal login` (or try `tcal --demo`)")
    try:
        password = password or get_password(account)
    except CredentialsError as e:
        raise click.ClickException(str(e)) from None
    if not password:
        raise click.ClickException(
            "no password found in the keyring, password_cmd or $TCAL_PASSWORD; run `tcal login`"
        )
    return ICloudProvider.connect(apple_id, password, account.caldav_url)


@contextmanager
def _reported(what: str) -> Iterator[None]:
    """Turn provider/network errors into a clean CLI error."""
    try:
        yield
    except Exception as e:
        raise click.ClickException(f"{what}: {e}") from None


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        raise click.ClickException(f"config: {e}") from None


@click.group(invoke_without_command=True)
@click.option("--demo", is_flag=True, help="Run with built-in sample data (no account needed).")
@click.pass_context
def cli(ctx: click.Context, demo: bool) -> None:
    """A minimal, keyboard-based TUI calendar."""
    if ctx.invoked_subcommand is not None:
        return
    config = _config()

    from tcal.providers.fake import FakeProvider
    from tcal.source import StoreSource
    from tcal.store import Store
    from tcal.sync import sync_job
    from tcal.ui.app import TcalApp

    if demo:
        # A throwaway cache, fresh each run, so the demo never touches the real one.
        database = paths.demo_database_file()
        database.unlink(missing_ok=True)
        sync = sync_job(FakeProvider(), database, config.sync)
        sync()  # fill the cache before the first frame
    else:
        database = paths.database_file()
        sync = sync_job(connect(config), database, config.sync)
    with Store(database) as store:
        TcalApp(StoreSource(store), config, sync=sync).run()


@cli.command()
@click.option("--apple-id", prompt="Apple ID", help="Your Apple ID e-mail.")
@click.option(
    "--password",
    prompt="App-specific password (appleid.apple.com)",
    hide_input=True,
    help="An app-specific password, not your Apple ID password.",
)
def login(apple_id: str, password: str) -> None:
    """Verify an iCloud account and remember it (password in the system keyring)."""
    provider = connect(_config(), apple_id, password)
    with _reported("could not connect"):
        calendars = provider.list_calendars()
    try:
        store_password(apple_id, password)
    except CredentialsError as e:
        click.echo(f"warning: {e}; set password_cmd or $TCAL_PASSWORD instead", err=True)
    save_apple_id(apple_id)
    click.echo(f"Logged in as {apple_id}: {len(calendars)} calendars.")


@cli.command()
def sync() -> None:
    """Sync once with the server and print a summary."""
    from tcal.sync import sync_job

    config = _config()
    job = sync_job(connect(config), paths.database_file(), config.sync)
    with _reported("sync failed"):
        summary = job()
    click.echo(f"Synced: {summary}")


@cli.command()
def calendars() -> None:
    """List the account's calendars."""
    provider = connect(_config())
    with _reported("could not list calendars"):
        found = provider.list_calendars()
    for cal in found:
        click.echo(f"{cal.color}  {cal.name}{'  (read-only)' if cal.readonly else ''}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
