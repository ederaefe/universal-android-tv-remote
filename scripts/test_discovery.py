import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import remote

devs = remote.discover_network_devices()
print(f"Total discovered devices: {len(devs)}")
for d in devs:
    print(f"- {d['ip']:16} [{d['badge']:11}] {d['description']} (Score: {d['score']})")

if devs:
    top = devs[0]
    if top.get("is_android"):
        print(f"\nRecommended Android target: {top['ip']}")
