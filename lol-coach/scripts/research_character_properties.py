"""Read-only PROP v3 research for locally extracted object configurations.

Format reference: https://github.com/CommunityDragon/CDTB/blob/master/cdtb/binfile.py
Restricted to the observed 16.20 field kinds; unknown kinds fail explicitly.
"""
import json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def fnv(s):
    h=0x811c9dc5
    for b in s.lower().encode():h=((h^b)*0x1000193)&0xffffffff
    return h


class Reader:
    def __init__(self,data,names):self.data=data;self.pos=0;self.names=names
    def read(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError('Truncated PROP')
        out=self.data[self.pos:self.pos+n];self.pos+=n;return out
    def fmt(self,s):return struct.unpack('<'+s,self.read(struct.calcsize('<'+s)))
    def number(self,s):return self.fmt(s)[0]
    def label(self,h):return self.names.get(h,f'{{{h:08x}}}')
    def string(self):return self.read(self.number('H')).decode('utf8')
    def count(self,s):
        n=self.number(s)
        if n>100000:raise ValueError('Excessive PROP count')
        return n
    def fields(self,count,depth=0):
        if depth>24:raise ValueError('Excessive PROP depth')
        fields={}
        for _ in range(count):
            h,t=self.fmt('IB');name=self.label(h)
            if name in fields:raise ValueError('Duplicate property')
            fields[name]=self.value(t,depth+1)
        return fields
    def value(self,t,depth):
        formats={0:'3H',1:'?',2:'b',3:'B',4:'h',5:'H',6:'i',7:'I',8:'q',9:'Q',10:'f',11:'2f',12:'3f',13:'4f',14:'16f',15:'4B',18:'Q',0x87:'B'}
        if t in formats:
            values=self.fmt(formats[t]);return values[0]if len(values)==1 else values
        if t==16:return self.string()
        if t in (17,0x84):return self.label(self.number('I'))
        if t in (0x82,0x83):
            h=self.number('I')
            if h==0 and t==0x82:return None
            n=self.number('I');end=self.pos+n;count=self.count('H');value=self.fields(count,depth)
            if self.pos!=end:raise ValueError('Nested PROP boundary mismatch')
            return dict(__type=self.label(h),**value)
        if t in (0x80,0x81):
            kind=self.number('B');size=self.number('I');end=self.pos+size;n=self.count('I')
            value=[self.value(kind,depth+1)for _ in range(n)]
            if self.pos!=end:raise ValueError('List PROP boundary mismatch')
            return value
        if t==0x85:
            kind,present=self.fmt('BB')
            if present not in (0,1):raise ValueError('Invalid optional presence')
            return self.value(kind,depth+1)if present else None
        if t==0x86:
            key,val=self.fmt('BB');size=self.number('I');end=self.pos+size;n=self.count('I')
            values=[(self.value(key,depth+1),self.value(val,depth+1))for _ in range(n)]
            if self.pos!=end:raise ValueError('Map PROP boundary mismatch')
            return values
        raise ValueError(f'Unsupported PROP type {t:#x}')
    def parse(self):
        if self.read(4)!=b'PROP' or self.number('I')!=3:raise ValueError('Unsupported PROP file')
        links=[self.string()for _ in range(self.count('I'))]
        types=[self.number('I')for _ in range(self.count('I'))];out={}
        for typ in types:
            n=self.number('I');end=self.pos+n;path,count=self.fmt('IH');fields=self.fields(count)
            if self.pos!=end:raise ValueError('Entry PROP boundary mismatch')
            out[self.label(path)]=dict(__type=self.label(typ),**fields)
        if self.pos!=len(self.data):raise ValueError('Unconsumed PROP suffix')
        return dict(entries=out,linked=links)


def main():
    names={};keys=set()
    def collect(v):
        if isinstance(v,dict):
            for k,x in v.items():keys.add(k);collect(x)
        elif isinstance(v,list):
            for x in v:collect(x)
        elif isinstance(v,str)and len(v)<200:keys.add(v)
    for folder in ('data/raw','data/research/world_sources/raw'):
        for p in (ROOT/folder).glob('*.bin'):
            b=p.read_bytes()
            if not b.startswith(b'{'):continue
            try:collect(json.loads(b))
            except (ValueError,UnicodeDecodeError):continue
    for k in keys:
        if not k.startswith('{'):names[fnv(k)]=k
    folder=ROOT/'data/private/replay_completion/character_sources';results=[]
    for p in folder.glob('*.bin'):
        try:
            result=Reader(p.read_bytes(),names).parse();(folder/(p.stem+'.json')).write_text(json.dumps(result,indent=2));results.append(dict(name=p.stem,status='parsed'))
            def vision(v,path=''):
                if not isinstance(v,dict):return
                for k,x in v.items():
                    if any(s in k.lower()for s in ('vision','sight','reveal')):print(p.stem,path+'/'+k,json.dumps(x))
                    vision(x,path+'/'+k)
            vision(result)
        except ValueError as exc:results.append(dict(name=p.stem,error=str(exc)))
    (folder/'parse_results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))


if __name__=='__main__':main()
