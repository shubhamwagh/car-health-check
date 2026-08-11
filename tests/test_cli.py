from unittest.mock import patch

from click.testing import CliRunner

from carhealth.cli import main


def test_cli_help():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output


def test_cli_invokes_uvicorn_with_options():
    with patch("carhealth.cli.uvicorn.run") as run_mock:
        CliRunner().invoke(main, ["--host", "0.0.0.0", "--port", "9000", "--reload"])
        run_mock.assert_called_once_with("carhealth.main:app", host="0.0.0.0", port=9000, reload=True)
