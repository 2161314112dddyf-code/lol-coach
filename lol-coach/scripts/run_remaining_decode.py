"""One offline entry point for the RPL-005 collection, analysis and raw checks."""
from collect_remaining_decode import main as collect
from analyze_remaining_gaps import main as analyze
from verify_remaining_decode import main as verify
from export_tower_vision import main as towers

if __name__=='__main__':
    collect()
    analyze()
    verify()
    towers()
