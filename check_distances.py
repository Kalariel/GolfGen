import json, math

d = json.load(open('output/course.json'))
ch = d.get('clubhouse', d['routing'].get('clubhouse', {}))
cx, cy = ch.get('x', 0), ch.get('y', 0)
print(f"Clubhouse at ({cx}, {cy})\n")

for h in d['routing']['holes']:
    gx, gy = h['green']['x'], h['green']['y']
    dist = math.hypot(gx - cx, gy - cy)
    marker = ""
    if h['id'] in (9, 18):
        marker = " RETURN"
    elif dist < 40:
        marker = " CLOSE!"
    print(f"H{h['id']:2d} g=({gx:5.0f},{gy:5.0f}) d={dist:5.0f}{marker}")
