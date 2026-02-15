
import json
import math
from pathlib import Path

def dist(p1, p2):
    return math.sqrt((p1['x'] - p2['x'])**2 + (p1['y'] - p2['y'])**2)

# Helper functions for geometric checks
def cross_product(o, a, b):
    return (a['x'] - o['x']) * (b['y'] - o['y']) - (a['y'] - o['y']) * (b['x'] - o['x'])

def segments_intersect(p1, p2, p3, p4):
    d1 = cross_product(p3, p4, p1)
    d2 = cross_product(p3, p4, p2)
    d3 = cross_product(p1, p2, p3)
    d4 = cross_product(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False

def point_to_segment_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
    t = max(0, min(1, t))
    return math.hypot(px - (x1 + t*dx), py - (y1 + t*dy))

def verify(path: str):
    print(f"Verifying {path}...")
    with open(path, 'r') as f:
        data = json.load(f)
    
    holes = data['routing']['holes']
    config = data['metadata']['config']
    width = config['width']
    height = config['height']
    margin = 15
    
    # 1. Bounds Check
    violations = 0
    for h in holes:
        for wp in h['waypoints']:
            x, y = wp['x'], wp['y']
            if x < margin or x > width - margin or y < margin or y > height - margin:
                print(f"  VIOLATION: Hole {h['id']} OOB at ({x}, {y})")
                violations += 1
    
    if violations == 0:
        print("  Bounds Check: PASSED")
    else:
        print(f"  Bounds Check: FAILED ({violations} violations)")

    # 2. Clubhouse Return
    h1_tee = holes[0]['tee']
    h9_green = holes[8]['green']
    h10_tee = holes[9]['tee']
    h18_green = holes[17]['green']
    
    d1 = dist(h9_green, h10_tee)
    d2 = dist(h18_green, h1_tee)
    
    print(f"  Hole 9 Green -> Hole 10 Tee: {d1:.1f}")
    if d1 < 50:
        print("  Return 1 Check: PASSED")
    else:
        print("  Return 1 Check: FAILED (Too far)")
        
    print(f"  Hole 18 Green -> Hole 1 Tee: {d2:.1f}")
    if d2 < 50:
        print("  Return 2 Check: PASSED")
    else:
        print("  Return 2 Check: FAILED (Too far)")

    # 3. Collision Checks
    segments = []
    for h in holes:
        wps = h['waypoints']
        w = h['fairway_width']
        for i in range(len(wps)-1):
            segments.append({
                'p1': wps[i], 'p2': wps[i+1], 'w': w, 'hid': h['id']
            })
            
    crossings = 0
    placements = 0
    
    for i in range(len(segments)):
        s1 = segments[i]
        for j in range(i+1, len(segments)):
            s2 = segments[j]
            if s1['hid'] == s2['hid']: continue # Ignore self-intersection for now
            
            if dist(s1['p1'], s2['p1']) > 200: continue
            
            if segments_intersect(s1['p1'], s1['p2'], s2['p1'], s2['p2']):
                print(f"  VIOLATION: Crossing between Hole {s1['hid']} and {s2['hid']}")
                crossings += 1
                
    # Check Tee/Green on other fairways
    for h in holes:
        tee = h['tee']
        green = h['green']
        hid = h['id']
        
        for seg in segments:
            if seg['hid'] == hid: continue
            
            d_tee = point_to_segment_dist(tee['x'], tee['y'], 
                                          seg['p1']['x'], seg['p1']['y'], 
                                          seg['p2']['x'], seg['p2']['y'])
            if d_tee < seg['w']/2 + 5:
                print(f"  VIOLATION: Hole {hid} Tee on Hole {seg['hid']} Fairway")
                placements += 1
                
            d_green = point_to_segment_dist(green['x'], green['y'], 
                                          seg['p1']['x'], seg['p1']['y'], 
                                          seg['p2']['x'], seg['p2']['y'])
            if d_green < seg['w']/2 + 5: # rough approx radius
                print(f"  VIOLATION: Hole {hid} Green on Hole {seg['hid']} Fairway")
                placements += 1

    if crossings == 0:
        print("  Crossing Check: PASSED")
    else:
        print(f"  Crossing Check: FAILED ({crossings} crossings)")

    if placements == 0:
        print("  Placement Check: PASSED")
    else:
        print(f"  Placement Check: FAILED ({placements} bad placements)")
        
if __name__ == "__main__":
    verify("output/course.json")
