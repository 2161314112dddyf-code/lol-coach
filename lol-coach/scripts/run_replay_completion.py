"""Reproduce accepted RPL-008 exports from the existing local source set."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    (ROOT/'data/private/replay_completion').mkdir(parents=True,exist_ok=True)
    for script in ('research_compound_inventory.py','export_inventory_live_events.py',
                   'export_lane_identities.py','export_neutral_identities.py','export_created_objects.py'):
        subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,check=True)


if __name__=='__main__':main()
