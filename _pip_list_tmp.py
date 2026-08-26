import importlib.metadata as m
for d in sorted(m.distributions(), key=lambda d: (d.metadata['Name'] or '').lower()):
    print(f"{d.metadata['Name']}=={d.version}")
