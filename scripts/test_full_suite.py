import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import remote

def test_discovery():
    print("[TEST] Running discover_network_devices()...")
    devices = remote.discover_network_devices()
    assert isinstance(devices, list), "discover_network_devices must return a list"
    assert len(devices) > 0, "Should discover at least one network host from ARP table"
    print(f"  Discovered {len(devices)} devices.")
    has_recommended = False
    for d in devices:
        assert "ip" in d
        assert "badge" in d
        assert "score" in d
        assert "description" in d
        if d.get("adb_ready"):
            has_recommended = True
            print(f"  -> Found ADB Ready device: {d['ip']} (Score: {d['score']}, Badge: {d['badge']})")
    assert has_recommended, "Should detect at least 1 ADB-ready device on the network (e.g. 192.168.1.117)"
    print("  [PASS] Network discovery and heuristic classification verified.")

def test_html_integrity():
    print("[TEST] Checking index.html UI integrity...")
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Ensure mouse references are completely gone
    assert "mouseMode" not in html, "mouseMode should be removed"
    assert "toggleMouse" not in html, "toggleMouse should be removed"
    assert "cfgMouseDevice" not in html, "cfgMouseDevice should be removed"
    assert "btnMouseToggle" not in html, "btnMouseToggle should be removed"

    # Ensure network device UI elements are present
    assert "btnRunScan" in html, "btnRunScan should be present"
    assert "scanResultArea" in html, "scanResultArea should be present"
    assert "runSubnetScan" in html, "runSubnetScan function should be present"
    assert "connectToIp" in html, "connectToIp function should be present"
    assert "selectIpForConfig" in html, "selectIpForConfig function should be present"
    assert "saveAndConnect" in html, "saveAndConnect function should be present"
    assert "network-device-card" in html, "network-device-card CSS should be present"
    print("  [PASS] HTML UI elements & clean state verified.")

def test_remote_py_integrity():
    print("[TEST] Checking remote.py API and methods...")
    with open("remote.py", "r", encoding="utf-8") as f:
        code = f.read()

    assert "physical_mouse_worker" not in code
    assert "get_cursor_pos" not in code
    assert "send_relative_mouse" not in code
    assert "send_mouse_click" not in code
    assert "/mouse_rel" not in code
    assert "discover_network_devices" in code
    assert "get_arp_neighbors" in code
    print("  [PASS] remote.py methods and API integrity verified.")

if __name__ == "__main__":
    test_discovery()
    test_html_integrity()
    test_remote_py_integrity()
    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
