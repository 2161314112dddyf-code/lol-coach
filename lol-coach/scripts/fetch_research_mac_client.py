"""Fetch only exact-build public CDN chunks; never execute the downloaded file."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zstandard

ROOT=Path(__file__).resolve().parents[1]


def main():
    manifest=json.loads((ROOT/'data/research/mac_client_chunks.json').read_text())
    if manifest['manifestId']!='66B91DB25E5AD56E':raise ValueError('Wrong manifest')
    f=manifest['files'][0]
    if f['name']!='LeagueofLegends.app/Contents/MacOS/LeagueofLegends' or f['size']!=80518288:
        raise ValueError('Wrong target')
    dest=ROOT/'data/research/client_16.20.824.8524_mac'
    dest.mkdir(exist_ok=True)
    output=dest/'LeagueofLegends'
    if output.exists():raise ValueError('Already cached; use the offline audit, not another download')
    def fetch(entry):
        url='https://lol.dyn.riotcdn.net/channels/public/bundles/'+format(int(entry['bundleId']),'016X')+'.bundle'
        range_value=f"bytes={entry['offset']}-{entry['offset']+entry['compressedSize']-1}"
        req=Request(url,headers={'Range':range_value,'User-Agent':'lol-coach-source-audit/0.1'})
        with urlopen(req,timeout=45) as r:
            body=r.read(entry['compressedSize']+1);status=r.status;cr=r.headers.get('Content-Range')
        if status!=206 or len(body)!=entry['compressedSize']:raise ValueError('Range mismatch')
        data=zstandard.ZstdDecompressor().decompress(body,max_output_size=entry['uncompressedSize'])
        if len(data)!=entry['uncompressedSize']:raise ValueError('Chunk length mismatch')
        return data,dict(url=url,range=range_value,http_status=status,content_range=cr,
                         compressed_sha256=hashlib.sha256(body).hexdigest(),decoded_sha256=hashlib.sha256(data).hexdigest())
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(fetch,f['chunks']))
    data=b''.join(x[0] for x in rows)
    if len(data)!=f['size']:raise ValueError('File length mismatch')
    if output.exists():raise ValueError('Refuse overwrite')
    output.write_bytes(data)
    report={'build':'16.20.824.8524','manifest_id':manifest['manifestId'],
            'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
            'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'chunks':[x[1] for x in rows],
            'executed':False}
    (dest/'source.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='chunks'}))


if __name__=='__main__':main()
