"""Exercise public CLI behavior without requiring optional packages."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

import pytest
from reliclab_cli import main as cli


@pytest.mark.parametrize("argument", ["--version", "--help"])
def test_information_commands(argument: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([argument])
    assert error.value.code == 0
    assert "relic" in capsys.readouterr().out


def test_doctor(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor"]) == 0
    assert "does not imply implemented" in capsys.readouterr().out


@pytest.mark.parametrize("extra", ["runtime", "ui"])
def test_missing_extra_is_actionable(
    extra: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = installed_version

    def version(name: str) -> str:
        if name == cli.OPTIONAL_PACKAGES[extra]:
            raise PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(cli, "version", version)
    with pytest.raises(SystemExit) as error:
        cli.main(["doctor", "--require", extra])
    assert error.value.code == 1
    assert f"reliclab[{extra}]" in capsys.readouterr().err
    assert cli.main(["doctor"]) == 0


def test_missing_core_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(cli, "version", missing)
    with pytest.raises(SystemExit) as error:
        cli.main(["doctor"])
    assert error.value.code == 1


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["run"])
    assert error.value.code == 2
