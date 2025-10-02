import subprocess, sys, json, os
from pathlib import Path

def test_cli_validate_config():
    result = subprocess.run([sys.executable, "-m", "llmbench.cli", "validate-config", "config/config_mock.yaml"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Fingerprint:" in result.stdout


def test_cli_run(tmp_path: Path):
    outdir = tmp_path / "cli_run"
    result = subprocess.run([
        sys.executable,
        "-m",
        "llmbench.cli",
        "run",
        "config/config_mock.yaml",
        "-o",
        str(outdir),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # Check report
    assert (outdir / "report.md").exists()
    assert (outdir / "global_summary.json").exists()

