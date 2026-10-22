"""Reproduce RPL-007 using existing private replay inputs and frozen exports."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for name in ('export_spell_targets.py', 'research_state_and_spawn.py'):
        subprocess.run([sys.executable, str(ROOT/'scripts'/name)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
