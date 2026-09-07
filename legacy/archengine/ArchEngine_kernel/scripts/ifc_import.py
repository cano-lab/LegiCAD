#!/usr/bin/env python3
import sys, json, os

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.placement
    IFC_AVAILABLE = True
except ImportError:
    IFC_AVAILABLE = False

SCALE = 0.00328084  # mm to feet (for IFC properties)
SCALE_GEOM = 3.28084    # meters to feet (ifcopenshell.geom returns meters)
SCALE_M2_FT2 = 10.7639  # m2 to ft2

def get_placement(element):
    try:
        if hasattr(element, 'ObjectPlacement') and element.ObjectPlacement:
            m = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
            # IFC: X=right, Y=depth, Z=up -> Our: X=right, Y=up, Z=depth
            # Negate Z to fix mirror image
            # Placement matrix is in IFC file units (mm)
            return [float(m[0][3])*SCALE, float(m[2][3])*SCALE, -float(m[1][3])*SCALE]
    except: pass
    return [0.0, 0.0, 0.0]

def get_wall_direction(element):
    """Get wall direction from placement matrix. Returns ('x'|'z', sign)."""
    try:
        if hasattr(element, 'ObjectPlacement') and element.ObjectPlacement:
            m = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
            # X-axis of placement matrix indicates wall direction
            dir_x = m[0][0]  # Component along global X
            dir_z = -m[1][0]  # Component along global Y (our Z after swap, negated)
            if abs(dir_x) > abs(dir_z):
                return ('x', 1 if dir_x >= 0 else -1)
            else:
                return ('z', 1 if dir_z >= 0 else -1)
    except: pass
    return ('x', 1)

def get_props(element):
    props = {}
    try:
        if hasattr(element, 'IsDefinedBy'):
            for rel in element.IsDefinedBy:
                if rel.is_a('IfcRelDefinesByProperties'):
                    pset = rel.RelatingPropertyDefinition
                    if pset.is_a('IfcPropertySet'):
                        for p in pset.HasProperties:
                            if p.is_a('IfcPropertySingleValue') and p.NominalValue:
                                v = p.NominalValue.wrappedValue
                                if isinstance(v, (int,float)):
                                    props[p.Name.lower()] = float(v) * SCALE
                    elif pset.is_a('IfcElementQuantity'):
                        for q in pset.Quantities:
                            if q.is_a('IfcQuantityLength'):
                                props[q.Name.lower()] = float(q.LengthValue) * SCALE
                            elif q.is_a('IfcQuantityArea'):
                                props[q.Name.lower()] = float(q.AreaValue) * SCALE_M2_FT2
    except: pass
    return props

def get_geom(ifc, elem):
    try:
        s = ifcopenshell.geom.settings()
        s.set(s.USE_WORLD_COORDS, True)
        shape = ifcopenshell.geom.create_shape(s, elem)
        v = shape.geometry.verts
        if not v: return None
        # ifcopenshell.geom returns meters, convert to feet
        pts = [(v[i]*SCALE_GEOM, v[i+1]*SCALE_GEOM, v[i+2]*SCALE_GEOM) for i in range(0,len(v),3)]
        return {
            'min': [min(p[0] for p in pts), min(p[2] for p in pts), min(p[1] for p in pts)],
            'max': [max(p[0] for p in pts), max(p[2] for p in pts), max(p[1] for p in pts)],
        }
    except: return None

def get_mesh(ifc, elem):
    """Extract actual mesh geometry (vertices and faces) from IFC element"""
    try:
        s = ifcopenshell.geom.settings()
        s.set(s.USE_WORLD_COORDS, True)
        shape = ifcopenshell.geom.create_shape(s, elem)
        v = shape.geometry.verts
        f = shape.geometry.faces
        if not v or not f: return None

        # Convert vertices: IFC (X,Y,Z) -> Our (X, Z, -Y) in feet
        vertices = []
        for i in range(0, len(v), 3):
            x = v[i] * SCALE_GEOM
            y = v[i+2] * SCALE_GEOM  # IFC Z -> our Y (height)
            z = -v[i+1] * SCALE_GEOM  # IFC Y -> our Z (negated)
            vertices.append([x, y, z])

        # Faces are triangle indices
        faces = []
        for i in range(0, len(f), 3):
            faces.append([f[i], f[i+1], f[i+2]])

        return {'vertices': vertices, 'faces': faces}
    except:
        return None

def from_props(elem, etype):
    pos = get_placement(elem)
    p = get_props(elem)
    h = p.get('height', p.get('grossheight', 10))
    w = p.get('width', p.get('grosswidth', 1))
    d = p.get('depth', p.get('thickness', 0.67))
    l = p.get('length', p.get('grosslength', 10))

    # Try to get area-based length for walls
    area = p.get('grosssidearea', p.get('netsidearea', 0))
    if area > 0 and h > 0:
        l = area / h

    h,w,d,l = max(h,0.5), max(w,0.3), max(d,0.3), max(l,1)

    if etype=='door':
        return {'min':pos, 'max':[pos[0]+w, pos[1]+h, pos[2]+d]}
    elif etype=='window':
        return {'min':pos, 'max':[pos[0]+w, pos[1]+h, pos[2]+d]}
    elif etype=='roof':
        # For roofs, use area to estimate dimensions
        area = p.get('grossarea', p.get('netarea', 100))
        side = area ** 0.5 if area > 0 else 10
        half = side / 2
        return {'min':[pos[0]-half, pos[1], pos[2]-half], 'max':[pos[0]+half, pos[1]+max(d,0.5), pos[2]+half]}
    elif etype=='column':
        return {'min':pos, 'max':[pos[0]+w, pos[1]+h, pos[2]+d]}
    elif etype=='wall':
        axis, sign = get_wall_direction(elem)
        # For walls, 'width' in IFC is the wall thickness
        thickness = w if w < l else d  # Use width as thickness if it's smaller than length
        if axis == 'z':
            if sign > 0:
                return {'min':pos, 'max':[pos[0]+thickness, pos[1]+h, pos[2]+l]}
            else:
                return {'min':[pos[0], pos[1], pos[2]-l], 'max':[pos[0]+thickness, pos[1]+h, pos[2]]}
        else:
            if sign > 0:
                return {'min':pos, 'max':[pos[0]+l, pos[1]+h, pos[2]+thickness]}
            else:
                return {'min':[pos[0]-l, pos[1], pos[2]], 'max':[pos[0], pos[1]+h, pos[2]+thickness]}
    elif etype=='slab':
        # For slabs, use area to estimate dimensions, centered on placement
        area = p.get('grossarea', p.get('netarea', 100))
        side = area ** 0.5 if area > 0 else 10
        half = side / 2
        return {'min':[pos[0]-half, pos[1], pos[2]-half], 'max':[pos[0]+half, pos[1]+max(d,0.5), pos[2]+half]}
    else:
        return {'min':pos, 'max':[pos[0]+l, pos[1]+d, pos[2]+w]}

def get_mat(elem):
    try:
        for a in elem.HasAssociations:
            if a.is_a('IfcRelAssociatesMaterial'):
                m = a.RelatingMaterial
                if m.is_a('IfcMaterial'):
                    n = m.Name.lower()
                    if 'steel' in n: return 'steel'
                    if 'conc' in n: return 'concrete'
                    if 'wood' in n: return 'wood'
    except: pass
    return 'concrete'

def convert(ifc_path, out):
    if not os.path.exists(ifc_path):
        print(f'File not found: {ifc_path}', file=sys.stderr)
        return
    ifc = ifcopenshell.open(ifc_path)
    proj = ifc.by_type('IfcProject')
    name = proj[0].Name if proj else 'IFC Import'
    elems = []

    for b in ifc.by_type('IfcBeam'):
        g = get_geom(ifc, b) or from_props(b, 'beam')
        if g:
            dx,dy,dz = g['max'][0]-g['min'][0], g['max'][1]-g['min'][1], g['max'][2]-g['min'][2]
            cx,cy,cz = (g['min'][0]+g['max'][0])/2, (g['min'][1]+g['max'][1])/2, (g['min'][2]+g['max'][2])/2
            if dx>=dz:
                elems.append({'type':0,'start':[g['min'][0],cy,cz],'end':[g['max'][0],cy,cz],'width':max(dz,0.3),'depth':max(dy,0.3),'material':get_mat(b),'stress':0,'deflection':0,'failed':False})
            else:
                elems.append({'type':0,'start':[cx,cy,g['min'][2]],'end':[cx,cy,g['max'][2]],'width':max(dx,0.3),'depth':max(dy,0.3),'material':get_mat(b),'stress':0,'deflection':0,'failed':False})

    for c in ifc.by_type('IfcColumn'):
        g = get_geom(ifc, c) or from_props(c, 'column')
        if g:
            cx,cz = (g['min'][0]+g['max'][0])/2, (g['min'][2]+g['max'][2])/2
            elems.append({'type':1,'start':[cx,g['min'][1],cz],'end':[cx,g['max'][1],cz],'width':max(g['max'][0]-g['min'][0],0.3),'depth':max(g['max'][2]-g['min'][2],0.3),'material':get_mat(c),'stress':0,'deflection':0,'failed':False})

    # Process walls - extract actual mesh geometry
    for w in ifc.by_type('IfcWall'):
        mesh = get_mesh(ifc, w)
        g = get_geom(ifc, w) or from_props(w, 'wall')
        if g:
            axis, sign = get_wall_direction(w)
            dx = g['max'][0] - g['min'][0]
            dz = g['max'][2] - g['min'][2]
            thickness = min(dx, dz) if min(dx, dz) > 0.1 else 0.67

            if axis == 'z':
                elem = {
                    'type': 3,
                    'start': g['min'],
                    'end': [g['min'][0] + thickness, g['max'][1], g['max'][2]],
                    'width': thickness,
                    'depth': max(dx, dz),
                    'material': get_mat(w),
                    'stress': 0, 'deflection': 0, 'failed': False
                }
            else:
                elem = {
                    'type': 3,
                    'start': g['min'],
                    'end': [g['max'][0], g['max'][1], g['min'][2] + thickness],
                    'width': max(dx, dz),
                    'depth': thickness,
                    'material': get_mat(w),
                    'stress': 0, 'deflection': 0, 'failed': False
                }
            if mesh:
                elem['mesh'] = mesh
            elems.append(elem)

    # Process doors (type 6) - extract actual mesh geometry
    for d in ifc.by_type('IfcDoor'):
        mesh = get_mesh(ifc, d)
        g = get_geom(ifc, d) or from_props(d, 'door')
        if g:
            dx = g['max'][0] - g['min'][0]
            dy = g['max'][1] - g['min'][1]
            dz = g['max'][2] - g['min'][2]
            elem = {
                'type': 6,
                'start': [g['min'][0], g['min'][1], -g['max'][2]],
                'end': [g['max'][0], g['max'][1], -g['min'][2]],
                'width': max(dx, dz),
                'depth': min(dx, dz) if min(dx, dz) > 0.1 else 0.3,
                'material': 'door',
                'stress': 0, 'deflection': 0, 'failed': False
            }
            if mesh:
                # Mesh vertices already transformed in get_mesh()
                elem['mesh'] = mesh
            elems.append(elem)

    # Process windows (type 7) - extract actual mesh geometry
    for w in ifc.by_type('IfcWindow'):
        mesh = get_mesh(ifc, w)
        g = get_geom(ifc, w) or from_props(w, 'window')
        if g:
            dx = g['max'][0] - g['min'][0]
            dy = g['max'][1] - g['min'][1]
            dz = g['max'][2] - g['min'][2]
            elem = {
                'type': 7,
                'start': [g['min'][0], g['min'][1], -g['max'][2]],
                'end': [g['max'][0], g['max'][1], -g['min'][2]],
                'width': max(dx, dz),
                'depth': min(dx, dz) if min(dx, dz) > 0.1 else 0.2,
                'material': 'glass',
                'stress': 0, 'deflection': 0, 'failed': False
            }
            if mesh:
                # Mesh vertices already transformed in get_mesh()
                elem['mesh'] = mesh
            elems.append(elem)

    # Process roofs (type 8) - extract actual mesh geometry
    for r in ifc.by_type('IfcRoof'):
        mesh = get_mesh(ifc, r)
        g = get_geom(ifc, r) or from_props(r, 'roof')
        if g:
            elem = {
                'type': 8,  # Roof
                'start': g['min'],
                'end': g['max'],
                'width': g['max'][0] - g['min'][0],
                'depth': g['max'][1] - g['min'][1],
                'material': 'roof',
                'stress': 0, 'deflection': 0, 'failed': False
            }
            if mesh:
                elem['mesh'] = mesh  # Include actual geometry
            elems.append(elem)

    # Create floor from wall footprint - simpler approach with 2 sections
    walls = [e for e in elems if e['type'] == 3]
    if walls:
        # Get overall bounds
        all_pts = []
        for w in walls:
            all_pts.append((w['start'][0], w['start'][2]))
            all_pts.append((w['end'][0], w['end'][2]))

        min_x = min(p[0] for p in all_pts)
        max_x = max(p[0] for p in all_pts)
        min_z = min(p[1] for p in all_pts)
        max_z = max(p[1] for p in all_pts)

        # Find vertical wall that divides left/right sections (longest one near center)
        divider_x = None
        divider_z_max = None
        best_length = 0
        for w in walls:
            sx, sz = w['start'][0], w['start'][2]
            ex, ez = w['end'][0], w['end'][2]
            mid_x = (sx + ex) / 2
            wall_length = abs(ez - sz)
            # Look for vertical wall near center - prefer longer walls
            if wall_length > abs(ex - sx) and min_x + 10 < mid_x < max_x - 10:
                if wall_length > best_length:
                    best_length = wall_length
                    divider_x = mid_x
                    divider_z_max = max(sz, ez)

        if divider_x is not None:
            # Left section floor (full height)
            elems.append({
                'type': 2,
                'start': [min_x, 0, min_z],
                'end': [divider_x, 0, max_z],
                'width': 0, 'depth': 0.5, 'material': 'concrete',
                'stress': 0, 'deflection': 0, 'failed': False
            })
            # Right section floor (only up to divider height)
            elems.append({
                'type': 2,
                'start': [divider_x, 0, min_z],
                'end': [max_x, 0, divider_z_max if divider_z_max else max_z],
                'width': 0, 'depth': 0.5, 'material': 'concrete',
                'stress': 0, 'deflection': 0, 'failed': False
            })
        else:
            # Single floor
            elems.append({
                'type': 2,
                'start': [min_x, 0, min_z],
                'end': [max_x, 0, max_z],
                'width': 0, 'depth': 0.5, 'material': 'concrete',
                'stress': 0, 'deflection': 0, 'failed': False
            })

    # Center all elements around origin
    if elems:
        all_x = [e['start'][0] for e in elems] + [e['end'][0] for e in elems]
        all_z = [e['start'][2] for e in elems] + [e['end'][2] for e in elems]
        cx = (min(all_x) + max(all_x)) / 2
        cz = (min(all_z) + max(all_z)) / 2
        for e in elems:
            e['start'][0] -= cx
            e['start'][2] -= cz
            e['end'][0] -= cx
            e['end'][2] -= cz
            # Also offset mesh vertices if present
            if 'mesh' in e:
                for v in e['mesh']['vertices']:
                    v[0] -= cx
                    v[2] -= cz

    with open(out, 'w') as f:
        json.dump({'name':name,'elements':elems}, f, indent=2)
    print(f'Exported {len(elems)} elements (centered)')

if __name__=='__main__':
    if len(sys.argv)<2:
        print('Usage: ifc_import.py <in.ifc> [out.json]')
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else 'output.json')
