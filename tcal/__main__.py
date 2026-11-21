"""Command line: ``tcal`` starts the TUI; ``tcal --demo`` uses sample data."""

import click

from tcal.config import ConfigError, load_config


@click.group(invoke_without_command=True)
@click.option("--demo", is_flag=True, help="Run with built-in sample data (no account needed).")
@click.pass_context
def cli(ctx: click.Context, demo: bool) -> None:
    """A minimal, keyboard-based TUI calendar."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        config = load_config()
    except ConfigError as e:
        raise click.ClickException(f"config: {e}") from None

    if not demo:
        # The backend package replaces this with the SQLite-store source.
        raise click.ClickException("iCloud sync is not implemented yet; try `tcal --demo`.")

    from tcal.providers.fake import FakeProvider
    from tcal.source import ProviderSource
    from tcal.ui.app import TcalApp

    TcalApp(ProviderSource(FakeProvider()), config).run()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
