from phBot import *
from threading import Timer
from datetime import datetime
import QtBind
import phBotChat
import urllib.request
import urllib.error
import json
import re
import os
import shutil
import time

pName = 'xAutoDungeonRotation'
pVersion = '3.0.7'

GITHUB_OWNER = "maherbkh"
GITHUB_REPO = "xAutoDungeonRotation"
GITHUB_RELEASES_LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_UA = "xAutoDungeonRotation/phBot-plugin"

# Cached tag from releases/latest (invalidated after a successful self-update)
_release_tag_cache = None

def _invalidate_release_cache():
    global _release_tag_cache
    _release_tag_cache = None

def get_latest_release_tag(force_refresh=False):
    """Tag name of the latest published GitHub Release (e.g. v3.0.7)."""
    global _release_tag_cache
    if not force_refresh and _release_tag_cache:
        return _release_tag_cache
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_LATEST_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": GITHUB_UA},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip()
        if tag:
            _release_tag_cache = tag
            return tag
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        pass
    return None

def tag_to_version(tag):
    """Release tag -> version string for compare (leading 'v' stripped)."""
    t = str(tag).strip()
    if t.lower().startswith("v"):
        t = t[1:].strip()
    return t

def raw_file_at_release_tag(relpath, tag):
    path = relpath.lstrip("/")
    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{tag}/{path}"

def parse_pversion_from_source(py_code):
    m = re.search(r"^\s*pVersion\s*=\s*(['\"])([^'\"]+)\1", py_code, re.MULTILINE)
    if m:
        return m.group(2).strip()
    m = re.search(r"^\s*pVersion\s*=\s*([0-9.]+)\s*(?:#|$)", py_code, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None

def fetch_plugin_from_latest_release(force_refresh_tag=False):
    """
    Download xAutoDungeonRotation.py from the latest Release tag.
    Returns (remote_pVersion, full_source) or (None, None).
    """
    tag = get_latest_release_tag(force_refresh=force_refresh_tag)
    if not tag:
        return None, None
    url = raw_file_at_release_tag("xAutoDungeonRotation.py", tag)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": GITHUB_UA})
        with urllib.request.urlopen(req, timeout=45) as w:
            py_code = w.read().decode("utf-8")
    except Exception:
        return None, None
    ver = parse_pversion_from_source(py_code) or tag_to_version(tag)
    return ver, py_code

def fgw_star_script_url(star):
    """Raw URL for FGW shipwreck script on the same Release tag as the plugin."""
    tag = get_latest_release_tag()
    if not tag or star not in (1, 2, 3, 4):
        return None
    return raw_file_at_release_tag(f"FGW_SHIPWRECK_{star}_STAR.txt", tag)

# Legacy: update checker still expects pUrl set (used only for "defined" guard)
pUrl = GITHUB_RELEASES_LATEST_API
NewestVersion = 0

gui = QtBind.init(__name__, pName)

# -------------------------
# Globals
# -------------------------
ENABLED = False
paused = False
mode_state = {
    "HoW": {
        "timer_start": 0,
        "running": False,
        "duration": 3600,  # 3600 = 1 hour
        "current_index": 0
    },
    "FGW": {
        "timer_start": 0,
        "running": False,
        "duration": 3600,  # 3600 = 1 hour
        "current_index": 0
    }
}
TOWN_REGIONS = {25000, 26265, 23687, 27244, 26959, 22618}
rotation_order = []
rotation_data = {
    "HoW": [],
    "FGW": []
}
SPECIAL_ITEMS = ["BearBoo", "CuteBunny", "Fire-Bred", "Immortal", "Craft The Min", "Double Dragon", "Acid", "God of Fight", # HoW
    "Broken key", "Large tong", "Phantom harp", "Evil's heart", "Vindictive spirit's bead", "Hook hand", "Commander's patch", "Sereness's tears" #FGW
]
CURRENT_MODE = "HoW"

drop_data = {
    "HoW": {
        "counts": {name: 0 for name in SPECIAL_ITEMS},
        "total": 0
    },
    "FGW": {
        "counts": {name: 0 for name in SPECIAL_ITEMS},
        "total": 0
    }
}
seen_drop_uids = set()
_cbParty = False
_cbPlayer = False

# ===== HEADER BAR =====
QtBind.createLabel(gui, "══════════════════════════════", 5, 5)
QtBind.createLabel(gui, "══════════════════════════════", 5, 5)
QtBind.createLabel(gui, "  ⚡ FGW/HoW ROTATION MANAGER ⚡", 15, 18)
QtBind.createLabel(gui, "══════════════════════════════", 5, 32)
# ===== POSITION CONTROL PANEL =====

QtBind.createLabel(gui, "📍 Position control", 5, 50)
cmb_location = QtBind.createCombobox(gui, 110, 48, 100, 22)
QtBind.append(gui, cmb_location, "Location 1")
QtBind.append(gui, cmb_location, "Location 2")
QtBind.append(gui, cmb_location, "Location 3")

# FGW star on its own row (avoids overlap with BACK TO CENTER button)
QtBind.createLabel(gui, "FGW star (req.):", 8, 82)
cmb_fgw_star = QtBind.createCombobox(gui, 115, 78, 135, 22)
QtBind.append(gui, cmb_fgw_star, "— select star —")
QtBind.append(gui, cmb_fgw_star, "1 ★")
QtBind.append(gui, cmb_fgw_star, "2 ★★")
QtBind.append(gui, cmb_fgw_star, "3 ★★★")
QtBind.append(gui, cmb_fgw_star, "4 ★★★★")

cbModeHoW = QtBind.createCheckBox(gui, "cbModeHoW_clicked", "🟢 HoW", 30, 112)
cbModeFGW = QtBind.createCheckBox(gui, "cbModeFGW_clicked", "🔴 FGW", 30, 142)
QtBind.setChecked(gui, cbModeHoW, True)

btn = QtBind.createButton(gui, "save_selected", "💾 SAVE POSITION", 150, 110)
btn1 = QtBind.createButton(gui, "copy_selected", "🔙 BACK TO CENTER", 150, 140)
QtBind.createLabel(gui, "──────────────────────────────", 5, 172)
# ===== ROTATION ENGINE PANEL =====
QtBind.createLabel(gui, "🎯 Active locations:", 70, 182)
QtBind.createLabel(gui, "⚔️HoW", 55, 197)
QtBind.createLabel(gui, "🔥 FGW", 155, 197)

how_spot1 = QtBind.createCheckBox(gui, "cb_how1_clicked", "🔴 Inactive", 25, 212)
how_spot2 = QtBind.createCheckBox(gui, "cb_how2_clicked", "🔴 Inactive", 25, 232)
how_spot3 = QtBind.createCheckBox(gui, "cb_how3_clicked", "🔴 Inactive", 25, 252)

fgw_spot1 = QtBind.createCheckBox(gui, "cb_fgw1_clicked", "🔴 Inactive", 140, 212)
fgw_spot2 = QtBind.createCheckBox(gui, "cb_fgw2_clicked", "🔴 Inactive", 140, 232)
fgw_spot3 = QtBind.createCheckBox(gui, "cb_fgw3_clicked", "🔴 Inactive", 140, 252)

QtBind.createLabel(gui, "──────────────────────────────", 5, 277)

# ===== LIVE STATUS DASHBOARD =====
lblTime = QtBind.createLabel(gui, "⚔️ HoW: 00:00:00", 25, 292)
lblTime2 = QtBind.createLabel(gui, "🔥 FGW: 00:00:00", 160, 292)
btnStart = QtBind.createButton(gui, "btn_start_rotation", "✅ START", 25, 317)
btnStop = QtBind.createButton(gui, "btn_stop_rotation", "⛔ STOP", 120, 317)
btnPause = QtBind.createButton(gui, "btn_pause_rotation", "⏸ PAUSE", 200, 317)
QtBind.createLabel(gui, "══════════════════════════════", 5, 347)
# ===== Log =====
QtBind.createLabel(gui, "Plugin Log:", 280, 3)
lstLog = QtBind.createList(gui, 280, 25, 350, 260) 
# ===== RIGHT SIDE =====
vr = f"Version:{pVersion}"; QtBind.createLabel(gui, vr, 555, 5)
btnUpdate = QtBind.createButton(gui, "btn_update", "🔄 UPDATE 🔄", 630, 1)
QtBind.createLabel(gui, "<b>💼 Drops 💼</b>", 640, 28)
lstDrops = QtBind.createList(gui,632,45,88,140)
lblTotal = QtBind.createLabel(gui, 'Total Drops: 0', 635, 190)
QtBind.createLabel(gui, '<b>Notify:📞<b>', 635, 210)
cbParty = QtBind.createCheckBox(gui, "cbParty_clicked", "🔴 Party", 635, 225)
cbPlayer = QtBind.createCheckBox(gui, "cbPlayer_clicked", "🔴 Player", 635, 240)
player_not = QtBind.createLineEdit(gui,"",632,260,88,20)

def update_rotation(mode, index, ui_obj, checked):
    data = get_character_data()
    loc_name = f"Location {index}"
    
    if checked:
        filename = f"{data['name']}_{mode}_{loc_name.replace(' ','_')}.txt"
        filepath = os.path.join(getPath(), filename)
        if not os.path.exists(filepath):
            add_log(f"⚠️ Save the position for {loc_name} first!")
            QtBind.setChecked(gui, ui_obj, False)
            QtBind.setText(gui, ui_obj, f"🔴 Inactive")
            return
        QtBind.setText(gui, ui_obj, f"🟢 Active  ")
        if loc_name not in rotation_data[mode]:
            rotation_data[mode].append(loc_name)
    else:
        QtBind.setText(gui, ui_obj, f"🔴 Inactive")
        if loc_name in rotation_data[mode]:
            rotation_data[mode].remove(loc_name)
    rotation_data[mode].sort() # Keeps Locations 1, 2, 3 in order

# Optimized UI Handlers
def cb_how1_clicked(c): update_rotation("HoW", 1, how_spot1, c)
def cb_how2_clicked(c): update_rotation("HoW", 2, how_spot2, c)
def cb_how3_clicked(c): update_rotation("HoW", 3, how_spot3, c)
def cb_fgw1_clicked(c): update_rotation("FGW", 1, fgw_spot1, c)
def cb_fgw2_clicked(c): update_rotation("FGW", 2, fgw_spot2, c)
def cb_fgw3_clicked(c): update_rotation("FGW", 3, fgw_spot3, c)

def get_mode():
    return CURRENT_MODE

FGW_STAR_UI_TO_INT = {"1 ★": 1, "2 ★★": 2, "3 ★★★": 3, "4 ★★★★": 4}

def get_selected_fgw_star():
    """Returns 1–4 if a real FGW star is chosen; None if placeholder (required not met)."""
    label = QtBind.text(gui, cmb_fgw_star).strip()
    return FGW_STAR_UI_TO_INT.get(label)

def cbParty_clicked(checked):
    global _cbParty
    _cbParty = checked
    if _cbParty:
        QtBind.setText(gui, cbParty, "🟢 Party")
    else:
        QtBind.setText(gui, cbParty, "🔴 Party")

def cbPlayer_clicked(checked):
    global _cbPlayer
    player_name = QtBind.text(gui, player_not).strip()
    
    if checked and not player_name:
        add_log("⚠ Enter player name first.")
        QtBind.setChecked(gui, cbPlayer, False)
        QtBind.setText(gui, cbPlayer, "🔴 Player")
        _cbPlayer = False
        return
    _cbPlayer = checked
    if _cbPlayer:
        QtBind.setText(gui, cbPlayer, f"🟢 {player_name}")
        QtBind.move(gui, player_not, 1000, 0)
    else:
        QtBind.setText(gui, cbPlayer, "🔴 Player")
        QtBind.move(gui, player_not, 632, 260)

def cbModeHoW_clicked(checked):
    global CURRENT_MODE
    if not checked:
        # Prevent unchecking active mode
        QtBind.setChecked(gui, cbModeHoW, True)
        return
    if checked:
        CURRENT_MODE = "HoW"
        QtBind.setChecked(gui, cbModeFGW, False)
        QtBind.setText(gui, cbModeHoW, "🟢 HoW")
        QtBind.setText(gui, cbModeFGW, "🔴 FGW")

def cbModeFGW_clicked(checked):
    global CURRENT_MODE
    if not checked:
        # Prevent unchecking active mode
        QtBind.setChecked(gui, cbModeFGW, True)
        return
    if checked:
        CURRENT_MODE = "FGW"
        QtBind.setChecked(gui, cbModeHoW, False)
        QtBind.setText(gui, cbModeFGW, "🟢 FGW")
        QtBind.setText(gui, cbModeHoW, "🔴 HoW")

# =========================
# GAME STATE
# =========================
def is_ingame():
    return get_character_data() is not None
    
def getPath():
    return get_config_dir()+pName+"\\"

def _in_town():
    try:
        pos = get_position() or {}
        r = int(pos.get("region", 0) or 0)
        if r == 0:
            ch = get_character_data() or {}
            r = int(ch.get("region", 0) or 0)
        return r in TOWN_REGIONS
    except:
        return False
# -------------------------
# Helpers
# -------------------------
log_buffer = []
MAX_LOGS = 15

def add_log(text):
    global log_buffer
    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"[{timestamp}] {text}"

    log_buffer.append(entry)
    if len(log_buffer) > MAX_LOGS:
        log_buffer.pop(0)
        
    QtBind.clear(gui, lstLog)
    for line in log_buffer:
        QtBind.append(gui, lstLog, line)

def compare_version(current, remote):
    def _parts(ver):
        out = []
        for x in str(ver).strip().split("."):
            try:
                out.append(int(x))
            except ValueError:
                out.append(0)
        return tuple(out)
    return _parts(current) < _parts(remote)

def btn_update():
    global pVersion
    add_log("🔎 Checking GitHub Releases (latest)…")
    latest_version, new_code = fetch_plugin_from_latest_release(force_refresh_tag=True)
    if not latest_version or not new_code:
        add_log("❌ No release / could not download plugin. Create a GitHub Release with the .py and tags.")
        return
    if not compare_version(pVersion, latest_version):
        add_log("✔ Plugin already up to date.")
        return
    try:
        current_file = os.path.realpath(__file__)
        backup_file = current_file + ".bkp"
        # Create backup
        shutil.copyfile(current_file, backup_file)
        # Overwrite current plugin
        with open(current_file, "w", encoding="utf-8") as f:
            f.write(new_code)
        _invalidate_release_cache()
        add_log(f"✅ Updated successfully to v{latest_version} (from latest Release)")
        add_log("♻ Please reload the plugin.")
    except Exception as e:
        add_log("❌ Update failed:")
        add_log(str(e))

def get_dimension_hole_count(mode):
    inventory = get_inventory()
    target_servername = "ITEM_JUPITER_FGW_3" if mode == "HoW" else "ITEM_ETC_TELEPORT_HOLE_WRECK_100_110_LEVEL_4" 
    total_count = 0
    
    if inventory and 'items' in inventory:
        for item in inventory['items']:
            if isinstance(item, dict):
                s_name = item.get('servername', '')
                display_name = item.get('name', '')
                
                if s_name == target_servername:
                    qty = item.get('quantity', 0)
                    total_count += qty
                    #add_log("✅ Found {0} by ID: {1} (x{2})".format(mode, display_name, qty))
                elif mode == "FGW" and "shipwreck" in display_name.lower():
                    qty = item.get('quantity', 0)
                    total_count += qty
                    #add_log("✅ Found FGW by Name: {0} (x{1})".format(display_name, qty))
    return total_count > 0, total_count

def dropps():
    mode = get_mode()
    drops = get_drops()
    if not drops:
        return

    new_drop_detected = False

    for uid, drop in drops.items():
        if uid in seen_drop_uids:
            continue

        seen_drop_uids.add(uid)
        item_name = drop.get('name', '')
        quantity = drop.get('quantity', 1)

        for name in SPECIAL_ITEMS:
            if name.lower() in item_name.lower():
                drop_data[mode]["counts"][name] += quantity
                drop_data[mode]["total"] += quantity
                new_drop_detected = True
                break

    # If a new item was added, refresh the UI list to show combined totals
    if new_drop_detected:
        QtBind.clear(gui, lstDrops)
        counts = drop_data[mode]["counts"]
        for name, count in counts.items():
            if count > 0:
                QtBind.append(gui, lstDrops, f"{name} x{count}")
        
        QtBind.setText(
            gui,
            lblTotal,
            f"{mode} Total: {drop_data[mode]['total']}"
        )

def finished():
    global CURRENT_MODE
    mode = get_mode()
    player_name = QtBind.text(gui, player_not).strip()
    counts = drop_data[mode]["counts"]
    total = drop_data[mode]["total"]

    report_parts = [f"{k} x{v}" for k, v in counts.items() if v > 0]
    report_text = " | ".join(report_parts)

    message = f"{mode} Drops -> {report_text}" if total > 0 else f"{mode} Completed - 0 drops."
    add_log(message)
    
    if _cbParty: phBotChat.Party(message)
    if _cbPlayer and player_name: phBotChat.Private(player_name, message)

    # --- MODE SWITCH LOGIC WITH QUANTITY LOGGING ---
    next_mode = "FGW" if mode == "HoW" else "HoW"
    
    if len(rotation_data[next_mode]) > 0:
        has_item, count = get_dimension_hole_count(next_mode)
        
        if has_item:
            CURRENT_MODE = next_mode
            mode_state[CURRENT_MODE]["running"] = True
            add_log(f"🔄 Switching to {CURRENT_MODE} (Inventory: {count} left)")
        else:
            add_log(f"⚠️ Missing {next_mode} Hole! (Count: 0). Staying in {mode}.")
    else:
        add_log(f"⚠️ {next_mode} has no locations selected. Staying in {mode}.")
    
    # Synchronize UI
    is_how = (CURRENT_MODE == "HoW")
    QtBind.setChecked(gui, cbModeHoW, is_how)
    QtBind.setChecked(gui, cbModeFGW, not is_how)
    QtBind.setText(gui, cbModeHoW, "🟢 HoW" if is_how else "🔴 HoW")
    QtBind.setText(gui, cbModeFGW, "🟢 FGW" if not is_how else "🔴 FGW")
    
    

def btn_pause_rotation():
    global paused
    mode = get_mode()
    if not mode_state[mode]["timer_start"]:
        add_log("⚠ We didn't even started ...  🤔 Nothing is running.")
        return
    paused = not paused
    if paused:

        add_log("⏸ Rotation paused.")
    else:
        add_log("▶ Rotation resumed.")
        if get_remaining(mode) <= 0:
            add_log("⏳ Time was over during pause."); add_log("⏳ Continuing rotation...")

def format_time(seconds):
    seconds = int(seconds); hours = seconds // 3600; minutes = (seconds % 3600) // 60;  secs = seconds % 60
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)

def get_elapsed(mode):
    return time.time() - mode_state[mode]["timer_start"]

def get_remaining(mode):
    remaining = mode_state[mode]["duration"] - get_elapsed(mode)
    return max(0, remaining)


def btn_start_rotation():
    global rotation_order, ENABLED
    
    ENABLED = True
    mode = get_mode()
    
    has_item, count = get_dimension_hole_count(mode)
    rotation_order = rotation_data[mode]

    if not rotation_order:
        add_log("❌ No active locations selected.")
        return
    if mode == "FGW" and get_selected_fgw_star() is None:
        add_log("❌ FGW: select a star level (required) before starting.")
        return
    if not has_item:
        add_log(f"❌ Cannot Start: You have 0 {mode} Dimension Holes!")
        return
    if mode_state[mode]["running"]:
        add_log("⚠ Rotation already running.")
        return

    # Start from the current saved index for this mode
    idx = mode_state[mode]["current_index"]

    # Safety check if locations were removed
    if idx >= len(rotation_order):
        idx = 0
        mode_state[mode]["current_index"] = 0
    start_training(rotation_order[idx])
    

    add_log("▶ Rotation started.")

def btn_stop_rotation():
    global ENABLED, paused
    stop_bot()
    paused = False
    ENABLED = False

# Reset everything
    for mode in ["HoW", "FGW"]:
        mode_state[mode]["timer_start"] = 0
        mode_state[mode]["running"] = False
        mode_state[mode]["current_index"] = 0

    QtBind.setText(gui, lblTime, "⚔️ HoW: 00:00:00")
    QtBind.setText(gui, lblTime2, "🔥 FGW: 00:00:00")
    add_log("⛔ FULL STOP executed. All timers and rotations stopped.")


def start_training(location_name):
    mode = get_mode()
    has_item, count = get_dimension_hole_count(mode)
    
    if not has_item:
        add_log(f"⚠️ Missing {mode} Dimension Holes in inventory!❌")
        return False
        
    if load_training_script(location_name):
        add_log(f"🟢 Bot started. Using {location_name}")
    else:
        add_log(f"🔴🔴🔴 Opps, Seems we cant can't start.")

def load_training_script(location_name):
    data = get_character_data()
    if not data:
        add_log("❌ Not in game.")
        return False

    name = data['name']
    mode = get_mode()
    filename = f"{name}_{mode}_{location_name.replace(' ','_')}.txt"
    filepath = os.path.join(getPath(), filename)

    if not os.path.exists(filepath):
        add_log(f"❌ Script not found: {mode} {location_name}")
        return False

    stop_bot()
    set_training_script(filepath)
    Timer(1.0, start_bot).start()
    return True

def entering():
    global mode_state, seen_drop_uids, drop_data
    
    mode = get_mode()
    
    if mode_state[mode]["running"]:
        add_log("⏱Going back. Maybe we missed some mobs !?")
        return

   # start_mode_timer(mode)
    mode_state[mode]["timer_start"] = time.time()
    mode_state[mode]["running"] = True
    seen_drop_uids = set()

    drop_data[mode]["counts"] = {name: 0 for name in SPECIAL_ITEMS}
    drop_data[mode]["total"] = 0

    QtBind.clear(gui, lstDrops)
    QtBind.setText(gui, lblTotal, f"{mode} Total: 0")
    add_log(f"⏱ Entered through the portal. ⏱")


start = "walk,6428,1108,0"
URL_HOW = "https://raw.githubusercontent.com/nmilchev/xPosRotate/refs/heads/main/SCRIPT_HOW.txt"

def get_remote_script(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": GITHUB_UA})
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        add_log(f"❌ GitHub Error: {e}")
        return None

def copy_selected():
    line = "path,25000,6428,1108,0"
    add_log("📍 GOING BACK TO Jangan CENTER:")
    start_script(line)

def save_selected():
    data = get_character_data()
    if not data:
        return
        
    name = data['name']
    selected = QtBind.text(gui, cmb_location)
    mode = get_mode()

    if not selected:
        add_log("❌ No location selected!")
        return

    if mode == "FGW":
        star = get_selected_fgw_star()
        if star is None:
            add_log("❌ FGW: select a star level (required) before saving.")
            return
        script_url = fgw_star_script_url(star)
        if not script_url:
            add_log("❌ FGW: could not resolve latest GitHub Release (needed for script URLs).")
            return
        script_body = get_remote_script(script_url)
    else:
        script_body = get_remote_script(URL_HOW)

    if not script_body:
        add_log("❌ Could not download training script body.")
        return

    p = get_position()
    line = f"path,{p['region']},{int(p['x'])},{int(p['y'])},{int(p['z'])}"

    filename = f"{name}_{mode}_{selected.replace(' ','_')}.txt"
    filepath = os.path.join(getPath(), filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(start + "\n" + line + "\n" + script_body)

    if mode == "FGW":
        add_log(f"💾 Saved FGW ★{star} for {selected}")
    else:
        add_log(f"💾 Saved {mode} position for {selected}")

# -------------------------
# Event Loop
# -------------------------
def event_loop():
    global rotation_order
    
    if not ENABLED: 
        #add_log("⏱ DEBUG not enabled")
        return 
        
    QtBind.setText(gui, lblTime, f"⚔️ HoW: {format_time(get_remaining("HoW"))}")
    QtBind.setText(gui, lblTime2, f"🔥 FGW: {format_time(get_remaining("FGW"))}")
    
    mode = get_mode()
    if not mode_state[mode]["running"]: 
        return 
    dropps()
    
    if get_remaining(mode) <= 0 and _in_town():
        if paused:
            return
            
        add_log("⏱ It's time to move on. Changing script.")
        
        mode_state[mode]["running"] = False
        rotation_order = rotation_data[mode]
        
        if not rotation_order:
            add_log("⚠ No active locations.")
            return
        # 3. Get and increment ONLY this mode's index
        idx = mode_state[mode]["current_index"]
        new_idx = (idx + 1) % len(rotation_order)
        mode_state[mode]["current_index"] = new_idx
            
        # 4. Start the next script in the sequence for THIS mode
        next_loc = rotation_order[new_idx]
        add_log(f"🔁 {mode} sequence: Moving to {next_loc}")
        start_training(next_loc)
    return 


# ------------------------
# External Call Function
# ------------------------
def get_hole(a): 
    entering()
    return True
def report(a): 
    finished()
    return True

def check():
    global pVersion
    add_log("🔎 Checking GitHub Releases (latest)…")
    tag = get_latest_release_tag(force_refresh=True)
    if not tag:
        add_log("⚠ No published Release found (updates/FGW scripts use Releases).")
        return
    latest_version = tag_to_version(tag)
    if compare_version(pVersion, latest_version):
        add_log("🔔 There is a new version on GitHub Releases 🔔")
    else:
        add_log("✔ Plugin already up to date.")
        return

if os.path.exists(getPath()):
    check()
else:
    # Creating configs folder
    os.makedirs(getPath())
    check()
    add_log('Plugin: '+pName+' folder has been created')
