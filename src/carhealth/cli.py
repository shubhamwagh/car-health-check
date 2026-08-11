import click
import uvicorn


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (development)")
def main(host, port, reload):
    """Run the Car Health Check web app."""
    uvicorn.run("carhealth.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
