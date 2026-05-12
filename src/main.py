import typer
from rich.console import Console

from src.ui.interact import SonexApp

APP_VERSION = "1.0.0"

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version", "-v",
        is_eager=True,
    ),
):
    if version:
        typer.echo(f"v{APP_VERSION}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        SonexApp().run()
        raise typer.Exit()

