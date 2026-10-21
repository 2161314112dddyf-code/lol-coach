"""Conservative grid contacts of packet-planned polylines, not actual trajectories."""
import math
from .ngrid import KNOWN_MASK


def segment_cells(grid, start, end):
    """All cells touched, including both sides of a grid line and corner contacts."""
    for p in (start,end):
        if len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p):
            raise ValueError('Invalid path coordinate')
        grid.cell_at(*p)  # Reject outside declared bounds; never silently clip.
    ax=(start[0]-grid.bounds_min[0])/grid.cell_size
    az=(start[1]-grid.bounds_min[2])/grid.cell_size
    bx=(end[0]-grid.bounds_min[0])/grid.cell_size
    bz=(end[1]-grid.bounds_min[2])/grid.cell_size
    times={0.0,1.0}
    for a,b in ((ax,bx),(az,bz)):
        if a!=b:
            for boundary in range(math.floor(min(a,b))+1,math.ceil(max(a,b))):
                t=(boundary-a)/(b-a)
                if 0<t<1:times.add(t)
    ordered=sorted(times)
    probes=ordered+[(a+b)/2 for a,b in zip(ordered,ordered[1:])]
    cells=set()
    def indices(v):
        nearest=round(v)
        return (nearest-1,nearest) if abs(v-nearest)<1e-9 else (math.floor(v),)
    for t in probes:
        for x in indices(ax+(bx-ax)*t):
            for z in indices(az+(bz-az)*t):
                if 0<=x<grid.width and 0<=z<grid.height:cells.add((x,z))
    return sorted(cells)


def audit_polyline(grid, points, overlays=()):
    if not points:raise ValueError('Empty path')
    cells=set()
    segments=list(zip(points,points[1:])) or [(points[0],points[0])]
    for a,b in segments:cells.update(segment_cells(grid,a,b))
    blocked=[]; uncertain=[]
    for x,z in sorted(cells):
        flag=grid.flags[z*grid.width+x]
        if flag & (2|4):blocked.append({'cell_x':x,'cell_z':z,'raw_flags':flag})
        # Known position of bit 128 does not imply known semantics.
        if flag & (128|1024|2048) or flag & ~KNOWN_MASK:
            uncertain.append({'cell_x':x,'cell_z':z,'raw_flags':flag})
    coverage=[]
    for overlay in overlays:
        hits={(x,z) for x,z in cells for r in overlay['regions']
              if r['x']<=x<r['x']+r['width'] and r['z']<=z<r['z']+r['height']}
        if hits:coverage.append({'path':overlay['source']['internal_path'],'contact_cells':len(hits),
                                'active':None,'applied':False})
    return {'status':'base_flag_contact' if blocked else 'no_base_blocking_flag_contact',
            'contact_cell_count':len(cells),'blocking_flag_contacts':blocked,'uncertain_flag_contacts':uncertain,
            'overlay_region_contacts':coverage,
            'planned_polyline_length_game_units':sum(math.dist(a,b) for a,b in segments),
            'actual_distance_travelled':None,'actual_duration_seconds':None,'actual_passability':None,
            'method':'zero_radius_segment_supercover_including_boundary_contacts',
            'meaning':'planned path vs static base-grid flags; not a collision verdict'}
