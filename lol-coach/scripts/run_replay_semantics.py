"""Reproduce RPL-006 decoding and crosschecks on existing local replay inputs."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for script in ('export_skill_ranks.py', 'export_spell_slots.py',
                   'check_replay_semantics.py', 'research_inventory_undo.py', 'check_keyframe_clock.py'):
        subprocess.run([sys.executable, str(ROOT/'scripts'/script)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
