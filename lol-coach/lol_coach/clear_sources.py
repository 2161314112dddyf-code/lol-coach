"""Extract source-reported clear entries, without inventing measured durations."""
from html.parser import HTMLParser


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=''
    def handle_data(self,data):
        if self.cell is not None:self.cell+=data
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(self.cell.strip());self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def extract_clear_candidates(html,champion):
    parser=TableRows();parser.feed(html)
    headers=None;result=[]
    expected=['Champion','Patch','Camps','Smite(s)','Time','Path','Link','Player']
    for row in parser.rows:
        if all(k in row for k in expected):
            if headers is not None:raise ValueError('Multiple tables require explicit selection')
            headers={k:row.index(k) for k in expected}
            headers['notes']=next((i for i,v in enumerate(row) if v.startswith('Notes/Details')),None)
            continue
        if headers is None:continue
        if len(row)<=headers['Champion'] or row[headers['Champion']]!=champion:continue
        if len(row)<=max(v for v in headers.values() if v is not None):raise ValueError('Truncated champion row')
        values={k:row[i] if i is not None and row[i] else None for k,i in headers.items()}
        result.append({'source_row_label':row[0], 'record_type':'source_reported_candidate_not_measurement',
                       'reported':values,'patch_mapping_status':'unverified_not_target_patch_proof',
                       'time_display_meaning':'unverified_game_clock_or_duration',
                       'elapsed_seconds':None,'start_game_time_seconds':None,'end_game_time_seconds':None,
                       'end_health':None,'end_mana':None,'end_level':None,'end_position':None,
                       'video_reviewed':False,'action_model_eligible':False,
                       'missing':['video start/end observations','level/items/runes/skill order','operation and leash conditions',
                                  'end state','patch compatibility','measurement uncertainty']})
    if headers is None:raise ValueError('Expected clear-table headers missing')
    return result
