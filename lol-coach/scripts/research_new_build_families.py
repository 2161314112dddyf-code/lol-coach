"""Read-only cross-opcode probe; structural hits never become accepted gameplay."""
import argparse,hashlib,json,re,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.export_replay_ten import load_reviewed
from lol_coach.replay_container import packets,container_info


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);_,decoder,inverse,deps=load_reviewed(ROOT.parent);jobs=[]
    for stem in ('HN1-11372643015','HN1-11404040952'):
        path=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl');raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        info=container_info(raw);stats=json.loads(info['metadata'].get('statsJson','[]'))
        roster=[{k:r[k] for k in ('SKIN','TEAM','CHAMPION_NAME') if k in r} for r in stats]
        names={str(r.get('SKIN',r.get('CHAMPION_NAME',''))) for r in stats}-{''}
        families=Counter();attempts=Counter();hits=Counter();examples=defaultdict(list);tokens=defaultdict(list);lengths=defaultdict(Counter);skips=Counter()
        for r in packets(raw):
            if r['stream'] not in (1,2):continue
            key=f"{r['stream']}:{hex(r['opcode'])}";blob=r['payload'];families[key]+=1;lengths[key][len(blob)]+=1
            for name in names:
                # Exact ASCII token only, not a champion substring in arbitrary bytes.
                if re.search(rb'(?<![A-Za-z0-9_])'+re.escape(name.encode('ascii'))+rb'(?![A-Za-z0-9_])',blob) and len(tokens[name])<8:
                    tokens[name].append(dict(family=key,param=hex(r['param']),time=r['time'],chunk=r['chunk'],offset=r['offset']))
            if not 16<=len(blob)<=65536:skips[key]+=1;continue
            attempts[key]+=1
            try:d=decoder.decode_packet(blob,inverse)
            except (ValueError,IndexError):continue
            hits[key]+=1
            if len(examples[key])<3:examples[key].append(dict(time=r['time'],chunk=r['chunk'],offset=r['offset'],decoded=d))
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
        job=dict(replay=stem,version=info['version'],source=str(path),source_sha256=sha,metadata_roster=roster,
            scanned_live_and_checkpoint_packets=sum(families.values()),old_rule_attempts=sum(attempts.values()),
            structural_hits=dict(hits),hit_examples=dict(examples),plain_identity_token_witnesses=dict(tokens),
            families=[dict(family=k,count=n,old_rule_attempts=attempts[k],size_exclusions=skips[k],lengths=dict(lengths[k])) for k,n in families.most_common()],
            identity_mapping_verified=False,decision_input_eligible=False,
            limitations=['Only the old byte table and path grammar were tested across all opcodes',
                        'Payloads outside 16..65536 bytes excluded explicitly',
                        'Plain tokens are research witnesses, not entity/team assignments',
                        'Negative results do not exclude a new byte codec or changed path layout'])
        (out/(stem+'.json')).write_text(json.dumps(job,indent=2),encoding='utf8');jobs.append({k:v for k,v in job.items() if k not in ('families','hit_examples')})
        print(json.dumps(jobs[-1]),flush=True)
    (out/'summary.json').write_text(json.dumps(dict(jobs=jobs,dependencies=deps,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2),encoding='utf8')


if __name__=='__main__':main()
