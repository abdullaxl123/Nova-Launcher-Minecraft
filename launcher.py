import sys
import os

# Set DPI awareness before any window is created - prevents Win 11 startup stall
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import customtkinter as ctk
import minecraft_launcher_lib as mll
import threading
import json
import os
import sys
import subprocess
import requests
import webbrowser
import uuid
import shutil
from tkinter import messagebox, StringVar, filedialog
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
APP_DIR     = Path(os.getenv("APPDATA", Path.home())) / ".nova_launcher"
PROFILES_DIR = APP_DIR / "profiles"
ACCOUNTS_F  = APP_DIR / "accounts.json"
SETTINGS_F  = APP_DIR / "settings.json"
PROFILES_F  = APP_DIR / "profiles.json"
APP_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "#0d0f14"
PANEL     = "#13161e"
CARD      = "#1a1e28"
ACCENT    = "#00e5a0"
ACCENT2   = "#00b8ff"
ACCENT3   = "#a78bfa"   # purple for profiles
DANGER    = "#ff4466"
TEXT      = "#e8eaf0"
SUBTEXT   = "#6b7280"
BORDER    = "#252a38"

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        # Back up corrupted file so the user doesn't lose data silently
        backup = path.with_suffix(path.suffix + ".corrupt")
        try:
            path.rename(backup)
        except Exception:
            pass
        print(f"[NovaLauncher] WARNING: {path.name} was corrupted ({e}). "
              f"Backed up to {backup.name} and reset to defaults.")
        return default

def save_json(path, data):
    # Write to a temp file first, then replace - avoids corrupt writes on crash
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if path.exists():
            path.unlink()
        tmp.rename(path)
    except Exception as e:
        print(f"[NovaLauncher] WARNING: failed to save {path.name}: {e}")

# ── Account storage ───────────────────────────────────────────────────────────
class AccountManager:
    def __init__(self):
        data = load_json(ACCOUNTS_F, {"accounts": [], "active": None})
        self.accounts = data.get("accounts", [])
        self.active   = data.get("active", None)

    def save(self):
        save_json(ACCOUNTS_F, {"accounts": self.accounts, "active": self.active})

    def add_offline(self, username):
        acc = {"type": "offline", "username": username, "uuid": str(uuid.uuid4()), "id": str(uuid.uuid4())}
        self.accounts.append(acc)
        if not self.active:
            self.active = acc["id"]
        self.save()
        return acc

    def add_microsoft(self, profile):
        existing = next((a for a in self.accounts if a.get("uuid") == profile["uuid"]), None)
        if existing:
            existing.update(profile)
        else:
            self.accounts.append(profile)
        if not self.active:
            self.active = profile["id"]
        self.save()

    def remove(self, acc_id):
        self.accounts = [a for a in self.accounts if a["id"] != acc_id]
        if self.active == acc_id:
            self.active = self.accounts[0]["id"] if self.accounts else None
        self.save()

    def get_active(self):
        return next((a for a in self.accounts if a["id"] == self.active), None)

    def set_active(self, acc_id):
        self.active = acc_id
        self.save()

# ── Profile Manager ───────────────────────────────────────────────────────────
class ProfileManager:
    def __init__(self):
        data = load_json(PROFILES_F, {"profiles": [], "active": None})
        self.profiles = data.get("profiles", [])
        self.active   = data.get("active", None)
        # Migrate: ensure all profiles have required fields
        for p in self.profiles:
            p.setdefault("software", "vanilla")
            p.setdefault("ram", 2048)
            p.setdefault("mods", [])
            p.setdefault("modpack_name", "")
            p.setdefault("java", "")
            p.setdefault("width", 1280)
            p.setdefault("height", 720)

    def save(self):
        save_json(PROFILES_F, {"profiles": self.profiles, "active": self.active})

    def create(self, name, version, software="vanilla", ram=2048):
        pid = str(uuid.uuid4())
        profile_dir = PROFILES_DIR / pid
        profile_dir.mkdir(parents=True, exist_ok=True)
        # Create standard MC subdirectories
        for sub in ["mods", "screenshots", "saves", "resourcepacks", "shaderpacks", "logs"]:
            (profile_dir / sub).mkdir(exist_ok=True)
        p = {
            "id": pid,
            "name": name,
            "version": version,
            "software": software,   # vanilla / fabric / forge
            "ram": ram,
            "mods": [],             # list of mod file names inside profile mods dir
            "modpack_name": "",
            "java": "",
            "width": 1280,
            "height": 720,
            "created": str(__import__("datetime").datetime.now().isoformat()),
        }
        self.profiles.append(p)
        if not self.active:
            self.active = pid
        self.save()
        return p

    def delete(self, pid):
        profile_dir = PROFILES_DIR / pid
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
        self.profiles = [p for p in self.profiles if p["id"] != pid]
        if self.active == pid:
            self.active = self.profiles[0]["id"] if self.profiles else None
        self.save()

    def get(self, pid):
        return next((p for p in self.profiles if p["id"] == pid), None)

    def get_active(self):
        return self.get(self.active) if self.active else None

    def set_active(self, pid):
        self.active = pid
        self.save()

    def update(self, pid, **kwargs):
        p = self.get(pid)
        if p:
            p.update(kwargs)
            self.save()

    def get_dir(self, pid):
        return PROFILES_DIR / pid

    def add_mod(self, pid, src_path):
        """Copy a mod jar into the profile's mods directory."""
        src = Path(src_path)
        dest = PROFILES_DIR / pid / "mods" / src.name
        shutil.copy2(src, dest)
        p = self.get(pid)
        if src.name not in p["mods"]:
            p["mods"].append(src.name)
        self.save()
        return src.name

    def remove_mod(self, pid, mod_name):
        dest = PROFILES_DIR / pid / "mods" / mod_name
        if dest.exists():
            dest.unlink()
        p = self.get(pid)
        if mod_name in p["mods"]:
            p["mods"].remove(mod_name)
        self.save()

    def get_mods(self, pid):
        mods_dir = PROFILES_DIR / pid / "mods"
        if not mods_dir.exists():
            return []
        return [f.name for f in mods_dir.iterdir() if f.suffix in (".jar", ".zip")]

# ── Settings ──────────────────────────────────────────────────────────────────
class Settings:
    def __init__(self):
        data = load_json(SETTINGS_F, {})
        self.java   = data.get("java", "")

    def save(self):
        save_json(SETTINGS_F, {"java": self.java})

# ── Microsoft Auth (Authorization Code + localhost redirect) ─────────────────
# Prism Launcher's client ID supports localhost redirect URIs and XboxLive.signin.
# We spin up a local HTTP server, catch the redirect, and complete the auth chain.
CLIENT_ID    = "c36a9775-bcd5-4b46-9f2e-d8a3e25e5f38"

def ms_do_auth(log_cb, success_cb, error_cb, code_cb=None):
    """
    MS OAuth Authorization Code flow.
    Opens the Microsoft login page in the browser. After the user logs in,
    Microsoft redirects to the desktop redirect URI. We intercept that final
    redirect URL by asking the user to paste it — OR via a local server trick
    using the live.com desktop redirect which returns a blank page we detect.
    """
    import time as _time
    import requests
    import urllib.parse
    import http.server
    import socketserver
    import socket

    try:
        # Find a free local port and spin up a redirect-catching server
        with socket.socket() as _s:
            _s.bind(("127.0.0.1", 0))
            port = _s.getsockname()[1]
        redirect_uri = f"http://127.0.0.1:{port}"

        # Build login URL pointing to our local server
        params = urllib.parse.urlencode({
            "client_id":     CLIENT_ID,
            "response_type": "code",
            "redirect_uri":  redirect_uri,
            "scope":         "XboxLive.signin offline_access",
            "prompt":        "select_account",
        })
        login_url = f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?{params}"

        auth_code_holder = [None]
        error_holder     = [None]

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if "code" in params:
                    auth_code_holder[0] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"""<!DOCTYPE html><html>
                        <body style="background:#0d0f14;color:#00e5a0;font-family:sans-serif;
                        display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
                        <div style="text-align:center">
                        <h1>Login Successful!</h1>
                        <p style="color:#aaa">You can close this tab and return to Nova Launcher.</p>
                        </div></body></html>""")
                elif "error" in params:
                    err = params.get("error_description", params.get("error", ["Unknown"]))[0]
                    error_holder[0] = err
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(f"<html><body><h2>Error</h2><p>{err}</p></body></html>".encode())
                else:
                    self.send_response(200)
                    self.end_headers()
            def log_message(self, *_): pass

        httpd = socketserver.TCPServer(("127.0.0.1", port), _Handler)
        httpd.timeout = 300

        log_cb("Opening Microsoft login in your browser...")
        webbrowser.open(login_url)
        if code_cb:
            code_cb(login_url)

        # Wait for the redirect
        while auth_code_holder[0] is None and error_holder[0] is None:
            httpd.handle_request()
        httpd.server_close()

        if error_holder[0]:
            raise Exception(f"Login failed: {error_holder[0]}")
        if not auth_code_holder[0]:
            raise Exception("Login timed out — please try again.")

        log_cb("Login received - completing authentication...")
        ms_exchange_code(auth_code_holder[0], log_cb, success_cb, error_cb, redirect_uri=redirect_uri)
        return

    except Exception as e:
        error_cb(str(e))


def ms_exchange_code(auth_code, log_cb, success_cb, error_cb, redirect_uri=None):
    """Exchange an auth code for tokens and complete the full auth chain."""
    import time as _time
    import requests

    try:
        log_cb("Completing authentication...")

        # Step 1: Exchange code for MS tokens
        resp = requests.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            data={
                "client_id":    CLIENT_ID,
                "redirect_uri": redirect_uri,
                "grant_type":   "authorization_code",
                "code":         auth_code,
                "scope":        "XboxLive.signin offline_access",
            },
            timeout=15,
        )
        resp.raise_for_status()
        tj = resp.json()
        ms_access_token      = tj["access_token"]
        ms_refresh_token_val = tj.get("refresh_token", "")

        log_cb("Microsoft login received - authenticating with Xbox...")

        # Step 3: Xbox Live auth
        xbl = requests.post(
            "https://user.auth.xboxlive.com/user/authenticate",
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName":   "user.auth.xboxlive.com",
                    "RpsTicket":  f"d={ms_access_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType":    "JWT",
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        xbl.raise_for_status()
        xbl_j   = xbl.json()
        xbl_token = xbl_j["Token"]
        uhs       = xbl_j["DisplayClaims"]["xui"][0]["uhs"]

        # Step 4: XSTS token
        xsts = requests.post(
            "https://xsts.auth.xboxlive.com/xsts/authorize",
            json={
                "Properties": {
                    "SandboxId":  "RETAIL",
                    "UserTokens": [xbl_token],
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType":    "JWT",
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        xsts.raise_for_status()
        xsts_token = xsts.json()["Token"]

        # Step 5: Minecraft login
        mc_resp = requests.post(
            "https://api.minecraftservices.com/authentication/login_with_xbox",
            json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        mc_resp.raise_for_status()
        mc_access_token = mc_resp.json()["access_token"]

        # Step 6: Check ownership
        own = requests.get(
            "https://api.minecraftservices.com/entitlements/mcstore",
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=15,
        )
        own.raise_for_status()
        items = own.json().get("items", [])
        if not any(i.get("name") in ("product_minecraft", "game_minecraft") for i in items):
            raise Exception("This Microsoft account doesn't own Minecraft Java Edition.")

        # Step 7: Get profile
        prof = requests.get(
            "https://api.minecraftservices.com/minecraft/profile",
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=15,
        )
        prof.raise_for_status()
        pj = prof.json()

        account = {
            "type":             "microsoft",
            "username":         pj["name"],
            "uuid":             pj["id"],
            "access_token":     mc_access_token,
            "ms_refresh_token": ms_refresh_token_val,
            "token_expiry":     _time.time() + 86400,
            "id":               str(uuid.uuid4()),
        }
        log_cb(f"Logged in as {pj['name']}!")
        success_cb(account)

    except Exception as e:
        error_cb(str(e))


def ms_refresh_token(ms_refresh_tok):
    """Exchange a stored refresh_token for fresh MS + Minecraft tokens."""
    import time as _time
    import requests

    # Step 1: Refresh the MS OAuth token
    resp = requests.post(
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        data={
            "client_id":     CLIENT_ID,
            "grant_type":    "refresh_token",
            "refresh_token": ms_refresh_tok,
            "scope":         "XboxLive.signin offline_access",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise Exception("Session fully expired - please log in again.")
    tj = resp.json()
    ms_access_token      = tj["access_token"]
    new_refresh_token    = tj.get("refresh_token", ms_refresh_tok)

    # Step 2: Xbox Live
    xbl = requests.post(
        "https://user.auth.xboxlive.com/user/authenticate",
        json={
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": f"d={ms_access_token}"},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=15,
    )
    xbl.raise_for_status()
    xbl_j = xbl.json()
    xbl_token = xbl_j["Token"]
    uhs       = xbl_j["DisplayClaims"]["xui"][0]["uhs"]

    # Step 3: XSTS
    xsts = requests.post(
        "https://xsts.auth.xboxlive.com/xsts/authorize",
        json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT",
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=15,
    )
    xsts.raise_for_status()
    xsts_token = xsts.json()["Token"]

    # Step 4: Minecraft
    mc_resp = requests.post(
        "https://api.minecraftservices.com/authentication/login_with_xbox",
        json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    mc_resp.raise_for_status()
    mc_access_token = mc_resp.json()["access_token"]

    return {
        "access_token":     mc_access_token,
        "ms_refresh_token": new_refresh_token,
        "token_expiry":     _time.time() + 86400,
    }

# ═══════════════════════════════════════════════════════════════════════════════
#  UI Widgets
# ═══════════════════════════════════════════════════════════════════════════════

def styled_frame(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, **kw)

def label(parent, text, size=13, weight="normal", color=TEXT, **kw):
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(family="Segoe UI", size=size, weight=weight),
                        text_color=color, **kw)

def btn(parent, text, cmd, color=ACCENT, hover=None, width=120, size=13, **kw):
    hover = hover or color
    return ctk.CTkButton(parent, text=text, command=cmd, fg_color=color, hover_color=hover,
                         text_color="#0d0f14" if color == ACCENT else TEXT,
                         font=ctk.CTkFont(family="Segoe UI", size=size, weight="bold"),
                         corner_radius=8, width=width, **kw)

def danger_btn(parent, text, cmd, **kw):
    return btn(parent, text, cmd, color=DANGER, hover="#cc2244", **kw)

def soft_btn(parent, text, cmd, **kw):
    return btn(parent, text, cmd, color=BORDER, hover=CARD, **kw)

# ═══════════════════════════════════════════════════════════════════════════════
#  Profile Editor Dialog
# ═══════════════════════════════════════════════════════════════════════════════

class ProfileEditorDialog(ctk.CTkToplevel):
    """Create or edit a profile."""

    SOFTWARE_LABELS = {
        "vanilla": "⬜  Vanilla",
        "fabric":  "🟦  Fabric",
        "forge":   "🟧  Forge",
    }

    def __init__(self, parent, profiles: ProfileManager, versions: list,
                 profile=None, on_save=None):
        super().__init__(parent)
        self.profiles  = profiles
        self.versions  = versions
        self.profile   = profile   # None = create mode
        self.on_save   = on_save
        self.title("Edit Profile" if profile else "New Profile")
        self.geometry("560x640")
        self.minsize(520, 600)
        self.configure(fg_color=PANEL)
        self.grab_set()
        self._build()
        if profile:
            self._populate(profile)

    def _build(self):
        # Title
        label(self, "Edit Profile" if self.profile else "New Profile",
              size=20, weight="bold").pack(anchor="w", padx=24, pady=(20, 4))
        label(self, "Each profile has its own isolated Minecraft folder.",
              size=11, color=SUBTEXT).pack(anchor="w", padx=24)

        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x", padx=24, pady=12)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=0)

        def field_row(lbl_text):
            f = ctk.CTkFrame(scroll, fg_color="transparent")
            f.pack(fill="x", pady=(0, 12))
            label(f, lbl_text, size=11, color=SUBTEXT).pack(anchor="w", pady=(0, 4))
            return f

        # Profile name
        r = field_row("PROFILE NAME")
        self.name_entry = ctk.CTkEntry(r, placeholder_text="e.g. Fabric 1.21 Modded",
                                       fg_color=CARD, border_color=BORDER, text_color=TEXT,
                                       font=ctk.CTkFont("Segoe UI", 13), height=36)
        self.name_entry.pack(fill="x")

        # Version
        r2 = field_row("MINECRAFT VERSION")
        ver_vals = [v["id"] for v in self.versions] if self.versions else ["Loading..."]
        self.version_var = StringVar(value=ver_vals[0] if ver_vals else "")
        self.version_menu = ctk.CTkOptionMenu(
            r2, variable=self.version_var, values=ver_vals,
            fg_color=CARD, button_color=ACCENT, button_hover_color="#00c480",
            dropdown_fg_color=CARD, dropdown_hover_color=BORDER,
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=8, height=36
        )
        self.version_menu.pack(fill="x")

        # Software chooser
        r3 = field_row("SOFTWARE")
        sf = ctk.CTkFrame(r3, fg_color="transparent")
        sf.pack(fill="x")
        self.software_var = StringVar(value="vanilla")
        for val, lbl_text in [("vanilla", "⬜  Vanilla"), ("fabric", "🟦  Fabric"), ("forge", "🟧  Forge")]:
            colors = {
                "vanilla": (BORDER, CARD, TEXT),
                "fabric":  (ACCENT2, "#0090d0", TEXT),
                "forge":   ("#e07830", "#c06020", TEXT),
            }
            fg, hv, tc = colors[val]
            rb = ctk.CTkRadioButton(
                sf, text=lbl_text, variable=self.software_var, value=val,
                fg_color=ACCENT, hover_color="#00c480",
                font=ctk.CTkFont("Segoe UI", 13)
            )
            rb.pack(side="left", padx=(0, 20), pady=4)

        # RAM
        r4 = field_row("RAM ALLOCATION (MB)")
        ram_row = ctk.CTkFrame(r4, fg_color="transparent")
        ram_row.pack(fill="x")
        self.ram_var = StringVar(value="2048")
        self.ram_slider_var = ctk.DoubleVar(value=2048)
        self.ram_entry = ctk.CTkEntry(ram_row, textvariable=self.ram_var, width=80,
                                      fg_color=CARD, border_color=BORDER, text_color=TEXT,
                                      font=ctk.CTkFont("Segoe UI", 13))
        self.ram_entry.pack(side="right")
        label(ram_row, "MB", size=12, color=SUBTEXT).pack(side="right", padx=4)
        self.ram_slider = ctk.CTkSlider(
            ram_row, from_=512, to=16384, number_of_steps=31,
            variable=self.ram_slider_var,
            button_color=ACCENT, button_hover_color="#00c480", progress_color=ACCENT,
            command=self._on_slider
        )
        self.ram_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.ram_entry.bind("<FocusOut>", self._on_ram_entry)
        self.ram_entry.bind("<Return>",   self._on_ram_entry)

        # Quick RAM presets
        preset_row = ctk.CTkFrame(r4, fg_color="transparent")
        preset_row.pack(fill="x", pady=(4, 0))
        for mb in [1024, 2048, 4096, 8192]:
            soft_btn(preset_row, f"{mb//1024}GB" if mb >= 1024 else f"{mb}M",
                     lambda m=mb: self._set_ram(m), width=56, size=12, height=28).pack(side="left", padx=2)

        # Resolution
        r5 = field_row("WINDOW RESOLUTION")
        res_row = ctk.CTkFrame(r5, fg_color="transparent")
        res_row.pack(fill="x")
        self.w_var = StringVar(value="1280")
        self.h_var = StringVar(value="720")
        ctk.CTkEntry(res_row, textvariable=self.w_var, width=80,
                     fg_color=CARD, border_color=BORDER, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 12)).pack(side="left")
        label(res_row, "×", size=14, color=SUBTEXT).pack(side="left", padx=6)
        ctk.CTkEntry(res_row, textvariable=self.h_var, width=80,
                     fg_color=CARD, border_color=BORDER, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 12)).pack(side="left")

        # Java override
        r6 = field_row("JAVA EXECUTABLE  (optional, leave blank for auto)")
        self.java_var = StringVar(value="")
        java_row = ctk.CTkFrame(r6, fg_color="transparent")
        java_row.pack(fill="x")
        ctk.CTkEntry(java_row, textvariable=self.java_var, placeholder_text="Auto-detect",
                     fg_color=CARD, border_color=BORDER, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 12)).pack(side="left", fill="x", expand=True)
        soft_btn(java_row, "Browse", self._browse_java, width=70, size=12).pack(side="right", padx=(6, 0))

        # Mods / Modpack section (only visible when editing existing profile)
        if self.profile:
            ctk.CTkFrame(scroll, height=1, fg_color=BORDER).pack(fill="x", pady=12)

            # Tab toggle row
            tab_row = ctk.CTkFrame(scroll, fg_color="transparent")
            tab_row.pack(fill="x", pady=(0, 6))
            label(tab_row, "CONTENT", size=11, color=SUBTEXT).pack(side="left")

            self._content_tab = StringVar(value="mods")
            self._tab_mods_btn = ctk.CTkButton(
                tab_row, text="Individual Mods", width=130, height=28, corner_radius=6,
                fg_color=ACCENT, hover_color="#00c480", text_color="#0d0f14",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                command=lambda: self._switch_content_tab("mods")
            )
            self._tab_mods_btn.pack(side="left", padx=(12, 4))
            self._tab_pack_btn = ctk.CTkButton(
                tab_row, text="Modpack", width=100, height=28, corner_radius=6,
                fg_color=BORDER, hover_color=CARD, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                command=lambda: self._switch_content_tab("modpack")
            )
            self._tab_pack_btn.pack(side="left", padx=4)

            # --- Mods panel ---
            self._mods_panel = ctk.CTkFrame(scroll, fg_color="transparent")
            self._mods_panel.pack(fill="x")

            mod_hdr = ctk.CTkFrame(self._mods_panel, fg_color="transparent")
            mod_hdr.pack(fill="x", pady=(0, 4))
            label(mod_hdr, "Add individual .jar mod files for this profile.", size=11, color=SUBTEXT).pack(side="left")
            btn(mod_hdr, "+ Add Mod", self._add_mod, width=95, size=11, height=28).pack(side="right")

            self.mods_frame = ctk.CTkScrollableFrame(self._mods_panel, fg_color=CARD, corner_radius=8, height=140)
            self.mods_frame.pack(fill="x")
            self._refresh_mods()

            # --- Modpack panel ---
            self._modpack_panel = ctk.CTkFrame(scroll, fg_color="transparent")
            # (not packed until tab is switched to it)

            mp_desc = label(self._modpack_panel,
                            "Import a modpack ZIP (e.g. CurseForge or Modrinth export).\nAll files will be extracted into this profile's folder.",
                            size=11, color=SUBTEXT)
            mp_desc.pack(anchor="w", pady=(0, 8))

            mp_card = ctk.CTkFrame(self._modpack_panel, fg_color=CARD, corner_radius=8)
            mp_card.pack(fill="x")

            # Current modpack display
            cur_pack = self.profile.get("modpack_name", "")
            self._modpack_name_lbl = label(mp_card,
                                           f"Current: {cur_pack}" if cur_pack else "No modpack imported",
                                           size=12, color=ACCENT if cur_pack else SUBTEXT)
            self._modpack_name_lbl.pack(anchor="w", padx=14, pady=(12, 4))

            mp_btn_row = ctk.CTkFrame(mp_card, fg_color="transparent")
            mp_btn_row.pack(anchor="w", padx=14, pady=(0, 12))
            btn(mp_btn_row, "Import Modpack ZIP", self._import_modpack,
                width=160, size=12, height=32, color=ACCENT2, hover="#0090d0").pack(side="left", padx=(0, 8))
            if cur_pack:
                danger_btn(mp_btn_row, "Clear Modpack", self._clear_modpack,
                           width=120, size=12, height=32).pack(side="left")

        # Buttons row
        ctk.CTkFrame(self, height=1, fg_color=BORDER).pack(fill="x", padx=24, pady=(12, 0))
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=12)
        soft_btn(btn_row, "Cancel", self.destroy, width=100).pack(side="right", padx=(6, 0))
        btn(btn_row, "Save Profile", self._save, width=130).pack(side="right")

    def _on_slider(self, val):
        # Snap to nearest 512 and update BOTH entry and slider to same value
        mb = int(round(float(val) / 512)) * 512
        mb = max(512, min(16384, mb))
        self.ram_slider_var.set(mb)   # keep slider at snapped position
        self.ram_var.set(str(mb))     # keep entry in sync

    def _on_ram_entry(self, *_):
        try:
            mb = int(self.ram_var.get())
            mb = max(512, min(16384, mb))
            self.ram_slider_var.set(mb)
            self.ram_var.set(str(mb))
        except ValueError:
            pass

    def _set_ram(self, mb):
        self.ram_var.set(str(mb))
        self.ram_slider_var.set(mb)

    def _browse_java(self):
        path = filedialog.askopenfilename(
            title="Select Java Executable",
            filetypes=[("Java", "java.exe java"), ("All files", "*")]
        )
        if path:
            self.java_var.set(path)

    def _switch_content_tab(self, tab):
        self._content_tab.set(tab)
        if tab == "mods":
            self._tab_mods_btn.configure(fg_color=ACCENT, text_color="#0d0f14")
            self._tab_pack_btn.configure(fg_color=BORDER, text_color=TEXT)
            self._modpack_panel.pack_forget()
            self._mods_panel.pack(fill="x")
        else:
            self._tab_pack_btn.configure(fg_color=ACCENT2, text_color="#0d0f14")
            self._tab_mods_btn.configure(fg_color=BORDER, text_color=TEXT)
            self._mods_panel.pack_forget()
            self._modpack_panel.pack(fill="x")

    def _import_modpack(self):
        path = filedialog.askopenfilename(
            title="Select Modpack ZIP",
            filetypes=[("Modpack ZIP", "*.zip"), ("All files", "*")]
        )
        if not path:
            return
        src = Path(path)
        profile_dir = self.profiles.get_dir(self.profile["id"])
        pid = self.profile["id"]

        self._modpack_name_lbl.configure(text=f"Extracting {src.name}...", text_color=SUBTEXT)
        # Disable button while extracting so user can't double-click
        for w in self.winfo_children():
            try: w.configure(state="disabled")
            except Exception: pass

        def _do_extract():
            try:
                shutil.unpack_archive(str(src), str(profile_dir))
                self.profiles.update(pid, modpack_name=src.name)
                self.after(0, lambda: (
                    self._modpack_name_lbl.configure(
                        text=f"Current: {src.name}", text_color=ACCENT),
                    messagebox.showinfo("Modpack Imported",
                                        f"'{src.name}' extracted into profile folder.")
                ))
            except Exception as e:
                self.after(0, lambda err=str(e): (
                    self._modpack_name_lbl.configure(text="Import failed", text_color=DANGER),
                    messagebox.showerror("Import Error", err)
                ))
            finally:
                # Re-enable all widgets
                self.after(0, lambda: [
                    w.configure(state="normal")
                    for w in self.winfo_children()
                    if hasattr(w, "configure")
                ])

        threading.Thread(target=_do_extract, daemon=True).start()

    def _clear_modpack(self):
        if messagebox.askyesno("Clear Modpack",
                               "This will NOT delete extracted files, just clear the modpack label.\nContinue?"):
            self.profiles.update(self.profile["id"], modpack_name="")
            self._modpack_name_lbl.configure(text="No modpack imported", text_color=SUBTEXT)

    def _populate(self, p):
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, p["name"])
        if p["version"] in [v["id"] for v in self.versions]:
            self.version_var.set(p["version"])
        self.software_var.set(p.get("software", "vanilla"))
        self._set_ram(p.get("ram", 2048))
        self.w_var.set(str(p.get("width", 1280)))
        self.h_var.set(str(p.get("height", 720)))
        self.java_var.set(p.get("java", ""))

    def _refresh_mods(self):
        if not hasattr(self, "mods_frame"):
            return
        for w in self.mods_frame.winfo_children():
            w.destroy()
        mods = self.profiles.get_mods(self.profile["id"])
        if not mods:
            label(self.mods_frame, "No mods added - click '+ Add Mod' to add .jar files",
                  size=11, color=SUBTEXT).pack(pady=12)
            return
        for mod in mods:
            row = ctk.CTkFrame(self.mods_frame, fg_color="transparent", height=32)
            row.pack(fill="x", padx=4, pady=1)
            row.pack_propagate(False)
            label(row, "📦", size=12).pack(side="left", padx=(4, 6))
            label(row, mod, size=12).pack(side="left", fill="x", expand=True)
            danger_btn(row, "✕", lambda m=mod: self._remove_mod(m),
                       width=30, size=11, height=24).pack(side="right", padx=4)

    def _add_mod(self):
        paths = filedialog.askopenfilenames(
            title="Select Mod JARs",
            filetypes=[("Mod JARs", "*.jar"), ("ZIP mods", "*.zip"), ("All files", "*")]
        )
        for path in paths:
            self.profiles.add_mod(self.profile["id"], path)
        self._refresh_mods()

    def _remove_mod(self, mod_name):
        if messagebox.askyesno("Remove Mod", f"Remove '{mod_name}' from this profile?"):
            self.profiles.remove_mod(self.profile["id"], mod_name)
            self._refresh_mods()

    def _save(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a profile name."); return
        try:
            ram = int(self.ram_var.get())
            w   = int(self.w_var.get())
            h   = int(self.h_var.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "RAM and resolution must be numbers."); return

        if self.profile:
            self.profiles.update(
                self.profile["id"],
                name=name,
                version=self.version_var.get(),
                software=self.software_var.get(),
                ram=ram, width=w, height=h,
                java=self.java_var.get().strip(),
            )
        else:
            self.profiles.create(
                name=name,
                version=self.version_var.get(),
                software=self.software_var.get(),
                ram=ram,
            )
            p = self.profiles.profiles[-1]
            self.profiles.update(p["id"], width=w, height=h, java=self.java_var.get().strip())

        if self.on_save:
            self.on_save()
        self.destroy()

# ═══════════════════════════════════════════════════════════════════════════════
#  Main App
# ═══════════════════════════════════════════════════════════════════════════════

class NovaLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Nova Launcher")
        self.geometry("1100x680")
        self.minsize(900, 600)
        self.configure(fg_color=BG)
        self.config(cursor="arrow")  # ensure system cursor is always visible
        self.accounts  = AccountManager()
        self.profiles  = ProfileManager()
        self.settings  = Settings()
        self._versions_cache = []
        self._build_ui()
        self._load_versions()
        self._setup_drag_fix()

    def _setup_drag_fix(self):
        """Reduce UI lag while dragging on Windows using WM_ENTERSIZEMOVE hook."""
        if sys.platform != "win32":
            return
        try:
            import ctypes, ctypes.wintypes
            WM_ENTERSIZEMOVE = 0x0231
            WM_EXITSIZEMOVE  = 0x0232
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            old_proc = ctypes.windll.user32.GetWindowLongPtrW(hwnd, -4)
            WNDPROCTYPE = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.wintypes.HWND,
                ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
            def _proc(h, msg, wp, lp):
                if msg == WM_ENTERSIZEMOVE:
                    # Suspend tkinter's internal idle loop during drag
                    self.tk.call("tk", "busy", "hold", self._w)
                elif msg == WM_EXITSIZEMOVE:
                    try:
                        self.tk.call("tk", "busy", "forget", self._w)
                    except Exception:
                        pass
                    self.update_idletasks()
                return ctypes.windll.user32.CallWindowProcW(old_proc, h, msg, wp, lp)
            self._wndproc = WNDPROCTYPE(_proc)
            ctypes.windll.user32.SetWindowLongPtrW(
                hwnd, -4, ctypes.cast(self._wndproc, ctypes.c_void_p).value)
        except Exception:
            pass

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.sidebar = ctk.CTkFrame(self, width=200, fg_color=PANEL, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_f = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_f.pack(pady=(28, 20), padx=16, fill="x")
        label(logo_f, "⬡  NOVA", size=22, weight="bold", color=ACCENT).pack(anchor="w")
        label(logo_f, "Minecraft Launcher", size=11, color=SUBTEXT).pack(anchor="w")

        ctk.CTkFrame(self.sidebar, height=1, fg_color=BORDER).pack(fill="x", padx=14, pady=4)

        self._nav_btns = {}
        for name, icon in [("Play",      "▶"),
                            ("Profiles",  "◈"),
                            ("Versions",  "⬡"),
                            ("Accounts",  "👤"),
                            ("Settings",  "⚙"),
                            ("Skin",      "👕"),
                            ("Info",      "ℹ")]:
            b = ctk.CTkButton(
                self.sidebar, text=f"  {icon}  {name}", anchor="w",
                fg_color="transparent", hover_color=CARD,
                text_color=SUBTEXT, font=ctk.CTkFont("Segoe UI", 13),
                corner_radius=8, height=40,
                command=lambda n=name: self._switch(n)
            )
            b.pack(fill="x", padx=10, pady=2)
            self._nav_btns[name] = b

        self.status_lbl = label(self.sidebar, "Ready", size=11, color=SUBTEXT)
        self.status_lbl.pack(side="bottom", pady=12, padx=14, anchor="w")

        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.pack(side="right", fill="both", expand=True)

        self._pages = {}
        for name, builder in [("Play",     self._page_play),
                               ("Profiles", self._page_profiles),
                               ("Versions", self._page_versions),
                               ("Accounts", self._page_accounts),
                               ("Settings", self._page_settings),
                               ("Skin",     self._page_skin),
                               ("Info",     self._page_info)]:
            f = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
            builder(f)
            self._pages[name] = f

        self._switch("Play")

    def _switch(self, name):
        for n, f in self._pages.items():
            f.pack_forget()
            b = self._nav_btns[n]
            b.configure(text_color=SUBTEXT, fg_color="transparent")
        self._pages[name].pack(fill="both", expand=True)
        b = self._nav_btns[name]
        b.configure(text_color=ACCENT, fg_color=CARD)
        if name == "Accounts":
            self._refresh_accounts()
        if name == "Play":
            self._refresh_play()
        if name == "Profiles":
            self._refresh_profiles()

    # ── Play Page ─────────────────────────────────────────────────────────────
    def _page_play(self, f):
        # Hero
        hero = ctk.CTkFrame(f, fg_color=PANEL, corner_radius=16, height=180)
        hero.pack(fill="x", padx=24, pady=(24, 0))
        hero.pack_propagate(False)

        inner = ctk.CTkFrame(hero, fg_color="transparent")
        inner.place(relx=0.05, rely=0.5, anchor="w")
        label(inner, "Ready to Play", size=28, weight="bold").pack(anchor="w")
        self.play_sub = label(inner, "Select a profile and account below", size=13, color=SUBTEXT)
        self.play_sub.pack(anchor="w", pady=(4, 0))

        # Controls row
        ctrl = ctk.CTkFrame(f, fg_color="transparent")
        ctrl.pack(fill="x", padx=24, pady=16)

        # Profile selector
        pf = styled_frame(ctrl)
        pf.pack(side="left", padx=(0, 12), ipadx=8, ipady=8)
        label(pf, "PROFILE", size=10, color=SUBTEXT).pack(anchor="w", padx=12, pady=(8, 0))
        self.profile_var = StringVar(value="No profiles")
        self.profile_menu = ctk.CTkOptionMenu(
            pf, variable=self.profile_var, values=["No profiles"],
            fg_color=CARD, button_color=ACCENT3, button_hover_color="#8b68f0",
            dropdown_fg_color=CARD, dropdown_hover_color=BORDER,
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=8, width=260, height=36,
            command=self._on_profile_change
        )
        self.profile_menu.pack(padx=12, pady=(2, 10))

        # Profile info badge
        self.profile_info_lbl = label(pf, "", size=10, color=SUBTEXT)
        self.profile_info_lbl.pack(anchor="w", padx=14, pady=(0, 8))

        # Account selector
        af = styled_frame(ctrl)
        af.pack(side="left", padx=(0, 12), ipadx=8, ipady=8)
        label(af, "ACCOUNT", size=10, color=SUBTEXT).pack(anchor="w", padx=12, pady=(8, 0))
        self.play_acc_var = StringVar(value="No account")
        self.play_acc_menu = ctk.CTkOptionMenu(
            af, variable=self.play_acc_var, values=["No account"],
            fg_color=CARD, button_color=ACCENT2, button_hover_color="#0090d0",
            dropdown_fg_color=CARD, dropdown_hover_color=BORDER,
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=8, width=200, height=36,
            command=self._on_play_acc_change
        )
        self.play_acc_menu.pack(padx=12, pady=(2, 10))

        # Launch btn
        self.launch_btn = btn(ctrl, "▶  LAUNCH", self._launch, width=140, size=15, height=52)
        self.launch_btn.pack(side="left", pady=4)

        # Quick-edit profile button
        soft_btn(ctrl, "✎ Edit Profile", self._quick_edit_profile,
                 width=110, size=12, height=36).pack(side="left", padx=(8, 0), pady=4)

        # Progress
        prog_f = ctk.CTkFrame(f, fg_color="transparent")
        prog_f.pack(fill="x", padx=24)
        self.prog_bar = ctk.CTkProgressBar(prog_f, height=6, corner_radius=3,
                                           fg_color=BORDER, progress_color=ACCENT)
        self.prog_bar.set(0)
        self.prog_bar.pack(fill="x")
        self.prog_lbl = label(prog_f, "", size=11, color=SUBTEXT)
        self.prog_lbl.pack(anchor="w", pady=(4, 0))

        # Log
        log_f = styled_frame(f)
        log_f.pack(fill="both", expand=True, padx=24, pady=16)
        label(log_f, "CONSOLE", size=10, color=SUBTEXT).pack(anchor="w", padx=14, pady=(10, 0))
        self.log_box = ctk.CTkTextbox(log_f, fg_color="transparent", text_color=SUBTEXT,
                                      font=ctk.CTkFont("Consolas", 11), state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _refresh_play(self):
        # Profiles
        prof_names = [p["name"] for p in self.profiles.profiles]
        if not prof_names:
            self.profile_menu.configure(values=["No profiles - create one in Profiles"])
            self.profile_var.set("No profiles - create one in Profiles")
            self.profile_info_lbl.configure(text="")
        else:
            self.profile_menu.configure(values=prof_names)
            active = self.profiles.get_active()
            if active:
                self.profile_var.set(active["name"])
                self._update_profile_badge(active)
            else:
                self.profile_var.set(prof_names[0])

        # Accounts
        names = [f"{a['username']}  [{a['type']}]" for a in self.accounts.accounts]
        if not names:
            names = ["No account - add one in Accounts"]
        self.play_acc_menu.configure(values=names)
        active_acc = self.accounts.get_active()
        if active_acc:
            self.play_acc_var.set(f"{active_acc['username']}  [{active_acc['type']}]")
            self.play_sub.configure(text=f"Logged in as  {active_acc['username']}")
        else:
            self.play_acc_var.set(names[0])

    def _update_profile_badge(self, p):
        sw = p.get("software", "vanilla").title()
        ram = p.get("ram", 2048)
        ver = p.get("version", "?")
        mods_count = len(self.profiles.get_mods(p["id"]))
        mod_txt = f"  |  {mods_count} mod{'s' if mods_count != 1 else ''}" if mods_count else ""
        pack_name = p.get("modpack_name", "")
        pack_txt = f"  |  {pack_name}" if pack_name else ""
        self.profile_info_lbl.configure(text=f"{ver}  |  {sw}  |  {ram}MB RAM{mod_txt}{pack_txt}")

    def _on_profile_change(self, val):
        for p in self.profiles.profiles:
            if p["name"] == val:
                self.profiles.set_active(p["id"])
                self._update_profile_badge(p)
                break

    def _on_play_acc_change(self, val):
        for a in self.accounts.accounts:
            tag = f"{a['username']}  [{a['type']}]"
            if tag == val:
                self.accounts.set_active(a["id"])
                break

    def _quick_edit_profile(self):
        active = self.profiles.get_active()
        if not active:
            messagebox.showinfo("No Profile", "No profile selected.")
            return
        ProfileEditorDialog(self, self.profiles, self._versions_cache,
                            profile=active, on_save=self._refresh_play)

    def _log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status_lbl.configure(text=msg[:40])

    def _launch(self):
        acc = self.accounts.get_active()
        if not acc:
            messagebox.showwarning("No Account", "Add an account first in the Accounts tab.")
            return
        profile = self.profiles.get_active()
        if not profile:
            messagebox.showwarning("No Profile", "Create a profile first in the Profiles tab.")
            return
        ver = profile["version"]
        if not ver:
            messagebox.showwarning("No Version", "Profile has no version set.")
            return
        self.launch_btn.configure(state="disabled")
        # Refresh MS token in the background before launching
        threading.Thread(target=self._refresh_and_launch, args=(acc, profile), daemon=True).start()

    def _refresh_and_launch(self, acc, profile):
        """Refresh MS token if needed, then hand off to _launch_thread."""
        import time as _time
        if acc.get("type") == "microsoft":
            expiry = acc.get("token_expiry", 0)
            # Refresh if expired or expiring within the next 5 minutes
            if _time.time() > expiry - 300:
                refresh_tok = acc.get("ms_refresh_token", "")
                if refresh_tok:
                    self.after(0, self._log, "MS token expired - refreshing silently...")
                    try:
                        updates = ms_refresh_token(refresh_tok)
                        acc.update(updates)
                        # Persist the new tokens
                        self.accounts.save()
                        self.after(0, self._log, "Token refreshed OK.")
                    except Exception as e:
                        # Token refresh failed - force re-login
                        self.after(0, lambda err=str(e): (
                            self._log(f"Token refresh failed: {err}"),
                            messagebox.showwarning(
                                "Re-login Required",
                                f"Your Microsoft session expired and could not be refreshed automatically.\n\n"
                                f"Please remove this account in the Accounts tab and log in again.\n\nError: {err}"
                            )
                        ))
                        self.after(0, lambda: self.launch_btn.configure(state="normal"))
                        return
                else:
                    self.after(0, lambda: (
                        self._log("No refresh token stored - please re-add Microsoft account."),
                        messagebox.showwarning("Re-login Required",
                            "Your Microsoft session has expired.\n"
                            "Please remove and re-add your account in the Accounts tab.")
                    ))
                    self.after(0, lambda: self.launch_btn.configure(state="normal"))
                    return
        self._launch_thread(acc, profile)

    def _resolve_java(self, ver, mc_base, user_java, cb, launch_ver=None):
        """Return a java executable path, auto-installing via mll runtime if needed."""
        # 1. User explicitly set a java path — trust it
        if user_java:
            return user_java
        # 2. Always determine JVM from the BASE MC version number directly.
        #    Never rely on the fabric/forge loader JSON which may not be installed yet.
        #    1.20.5+ needs Java 21 (java-runtime-delta), older needs Java 17 (java-runtime-gamma)
        try:
            parts = ver.split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            needs_java21 = (major > 1) or (major == 1 and minor > 20) or \
                           (major == 1 and minor == 20 and patch >= 5)
            jvm_name = "java-runtime-delta" if needs_java21 else "java-runtime-gamma"
        except Exception:
            jvm_name = "java-runtime-gamma"

        self._log(f"Java: {'21 (delta)' if jvm_name == 'java-runtime-delta' else '17 (gamma)'} for MC {ver}")
        # 3. Check if it is already installed inside mc_base
        java_exe = mll.runtime.get_executable_path(jvm_name, str(mc_base))
        if java_exe and Path(java_exe).exists():
            self._log(f"Java runtime found: {jvm_name}")
            return java_exe
        # 4. Not installed — download it now
        self._log(f"Java runtime not found. Downloading {jvm_name} (one-time download)...")
        try:
            mll.runtime.install_jvm_runtime(jvm_name, str(mc_base), callback=cb)
            java_exe = mll.runtime.get_executable_path(jvm_name, str(mc_base))
            if java_exe and Path(java_exe).exists():
                self._log(f"Java installed: {java_exe}")
                return java_exe
        except Exception as je:
            self._log(f"Auto-install of {jvm_name} failed: {je}")
        # 5. Fall back to system java
        self._log("Falling back to system java...")
        return None   # mll will try PATH

    def _is_version_installed(self, ver_id, mc_base):
        """True if the version JSON and client jar already exist in mc_base."""
        ver_json = Path(mc_base) / "versions" / ver_id / f"{ver_id}.json"
        ver_jar  = Path(mc_base) / "versions" / ver_id / f"{ver_id}.jar"
        return ver_json.exists() and ver_jar.exists()

    def _launch_thread(self, acc, profile):
        try:
            pid      = profile["id"]
            ver      = profile["version"]
            software = profile.get("software", "vanilla")
            ram      = profile.get("ram", 2048)
            width    = profile.get("width", 1280)
            height   = profile.get("height", 720)
            user_java = profile.get("java", "") or self.settings.java

            game_dir = self.profiles.get_dir(pid)
            mc_base  = APP_DIR / "mc_shared"
            mc_base.mkdir(parents=True, exist_ok=True)

            self._log(f"[{profile['name']}] Starting ({software}, {ver})...")
            self.after(0, self.prog_bar.set, 0.05)

            self._prog_max = 1
            def set_status(s):  self.after(0, self._log, s)
            def set_max(mx):    self._prog_max = max(mx, 1)
            def set_prog(cur):  self.after(0, self.prog_bar.set, min(0.9, cur / self._prog_max))
            cb = {"setStatus": set_status, "setProgress": set_prog, "setMax": set_max}

            # --- Step 1: Vanilla base (skip if already installed) ---
            if self._is_version_installed(ver, mc_base):
                self._log(f"Vanilla {ver} already installed, skipping download.")
            else:
                self._log(f"Installing vanilla {ver}...")
                mll.install.install_minecraft_version(ver, str(mc_base), callback=cb)

            # --- Step 2: Pre-resolve loader IDs so Java version can be chosen correctly ---
            launch_ver = ver

            if software == "fabric":
                loader_ver = mll.fabric.get_latest_loader_version()
                fabric_id  = f"fabric-loader-{loader_ver}-{ver}"
                launch_ver = fabric_id
            elif software == "forge":
                try:
                    forge_ver = mll.forge.find_forge_version(ver)
                    if not forge_ver:
                        raise Exception(f"No Forge build found for Minecraft {ver}.")
                    launch_ver = mll.forge.forge_to_installed_version(forge_ver)
                except Exception as fge:
                    raise Exception(f"Forge setup failed: {fge}") from fge

            # --- Step 3: Auto-resolve Java using the loader version for correct JVM detection ---
            java = self._resolve_java(ver, mc_base, user_java, cb, launch_ver=launch_ver)

            # --- Step 4: Install Fabric / Forge loader if needed ---
            if software == "fabric":
                if self._is_version_installed(fabric_id, mc_base):
                    self._log(f"Fabric already installed: {fabric_id}")
                else:
                    self._log("Installing Fabric loader...")
                    try:
                        # Monkey-patch Popen to suppress any console windows
                        # that mll.fabric.install_fabric spawns internally
                        _orig_popen = subprocess.Popen
                        def _silent_popen(*a, **kw):
                            kw.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
                            kw.setdefault("stdout", subprocess.DEVNULL)
                            kw.setdefault("stderr", subprocess.DEVNULL)
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            si.wShowWindow = subprocess.SW_HIDE
                            kw.setdefault("startupinfo", si)
                            return _orig_popen(*a, **kw)
                        subprocess.Popen = _silent_popen
                        try:
                            mll.fabric.install_fabric(
                                ver, str(mc_base), loader_version=loader_ver,
                                callback=cb, java=java or None
                            )
                        finally:
                            subprocess.Popen = _orig_popen
                        self._log(f"Fabric installed: {fabric_id}")
                    except Exception as fe:
                        raise Exception(f"Fabric install failed: {fe}") from fe

            elif software == "forge":
                try:
                    forge_installed_id = launch_ver
                    if self._is_version_installed(forge_installed_id, mc_base):
                        self._log(f"Forge already installed: {forge_installed_id}")
                    else:
                        self._log(f"Installing Forge {forge_ver} (may take a few minutes)...")
                        if mll.forge.supports_automatic_install(forge_ver):
                            mll.forge.install_forge_version(
                                forge_ver, str(mc_base), callback=cb, java=java or None
                            )
                        else:
                            self._log("Older Forge: running installer manually...")
                            mll.forge.run_forge_installer(forge_ver, java=java or None)
                        self._log(f"Forge installed: {forge_installed_id}")
                except Exception as fge:
                    raise Exception(f"Forge install failed: {fge}") from fge

            # --- Step 4: Launch ---
            self._log("Building launch command...")
            opts = {
                "username":        acc["username"],
                "uuid":            acc.get("uuid", str(uuid.uuid4())),
                "token":           acc.get("access_token", "0"),
                "jvmArguments":    [f"-Xmx{ram}M", "-Xms512M"],
                "gameDirectory":   str(game_dir),
                "launcherName":    "NovaLauncher",
                "launcherVersion": "2.0",
            }
            if java:
                opts["executablePath"] = java
            if width and height:
                opts["customResolution"] = True
                opts["resolutionWidth"]  = str(width)
                opts["resolutionHeight"] = str(height)

            cmd = mll.command.get_minecraft_command(launch_ver, str(mc_base), opts)

            self._log(f"Launching {profile['name']} as {acc['username']}...")
            self.after(0, self.prog_bar.set, 1.0)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(cmd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=si,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            self._log(f"✓ Launched! ({software.title()}, {ram}MB, Java: {java or 'system'})")
        except Exception as e:
            self._log(f"✗ Error: {e}")
            self.after(0, messagebox.showerror, "Launch Error", str(e))
        finally:
            self.after(0, lambda: self.launch_btn.configure(state="normal"))

    # ── Profiles Page ─────────────────────────────────────────────────────────
    def _page_profiles(self, f):
        header = ctk.CTkFrame(f, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 4))
        label(header, "Profiles", size=22, weight="bold").pack(side="left")
        btn(header, "+  New Profile", self._new_profile, width=130, color=ACCENT3, hover="#8b68f0").pack(side="right")

        label(f, "Each profile has its own isolated mods, screenshots, saves and more.",
              size=12, color=SUBTEXT).pack(anchor="w", padx=24, pady=(0, 12))

        self.profiles_list_frame = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.profiles_list_frame.pack(fill="both", expand=True, padx=24, pady=(0, 24))

    def _refresh_profiles(self):
        for w in self.profiles_list_frame.winfo_children():
            w.destroy()

        if not self.profiles.profiles:
            empty = styled_frame(self.profiles_list_frame)
            empty.pack(fill="x", pady=4)
            label(empty, "No profiles yet", size=15, weight="bold").pack(pady=(20, 4))
            label(empty, "Click '+ New Profile' to create your first profile.", size=12, color=SUBTEXT).pack(pady=(0, 20))
            return

        for p in self.profiles.profiles:
            is_active = p["id"] == self.profiles.active
            card = ctk.CTkFrame(self.profiles_list_frame,
                                fg_color=CARD if not is_active else "#1e2535",
                                corner_radius=12, border_width=2 if is_active else 0,
                                border_color=ACCENT3 if is_active else BORDER)
            card.pack(fill="x", pady=4)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=16, pady=(12, 0))

            # Icon + name
            sw = p.get("software", "vanilla")
            icon = {"vanilla": "⬜", "fabric": "🟦", "forge": "🟧"}.get(sw, "⬜")
            label(top_row, icon, size=20).pack(side="left", padx=(0, 8))

            name_col = ctk.CTkFrame(top_row, fg_color="transparent")
            name_col.pack(side="left")
            label(name_col, p["name"], size=14, weight="bold",
                  color=ACCENT if is_active else TEXT).pack(anchor="w")

            # Badges row
            badges = ctk.CTkFrame(name_col, fg_color="transparent")
            badges.pack(anchor="w")
            for badge_text, badge_color in [
                (p.get("version", "?"), SUBTEXT),
                (sw.title(), ACCENT2 if sw == "fabric" else "#e07830" if sw == "forge" else SUBTEXT),
                (f"{p.get('ram', 2048)}MB", SUBTEXT),
            ]:
                lbl = ctk.CTkLabel(badges, text=badge_text,
                                   fg_color=PANEL, corner_radius=4,
                                   font=ctk.CTkFont("Segoe UI", 10),
                                   text_color=badge_color, padx=6, pady=2)
                lbl.pack(side="left", padx=(0, 4))

            # Mods badge
            mods = self.profiles.get_mods(p["id"])
            if mods:
                lbl = ctk.CTkLabel(badges, text=f"📦 {len(mods)} mod{'s' if len(mods) != 1 else ''}",
                                   fg_color=PANEL, corner_radius=4,
                                   font=ctk.CTkFont("Segoe UI", 10),
                                   text_color=ACCENT, padx=6, pady=2)
                lbl.pack(side="left", padx=(0, 4))

            # Modpack badge
            modpack_name = p.get("modpack_name", "")
            if modpack_name:
                lbl = ctk.CTkLabel(badges, text=f"🗂 {modpack_name}",
                                   fg_color=PANEL, corner_radius=4,
                                   font=ctk.CTkFont("Segoe UI", 10),
                                   text_color=ACCENT2, padx=6, pady=2)
                lbl.pack(side="left", padx=(0, 4))

            if is_active:
                ctk.CTkLabel(top_row, text="● ACTIVE",
                             text_color=ACCENT3, font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(side="left", padx=8)

            # Buttons
            btn_col = ctk.CTkFrame(top_row, fg_color="transparent")
            btn_col.pack(side="right")
            if not is_active:
                soft_btn(btn_col, "Set Active", lambda pid=p["id"]: self._set_active_profile(pid),
                         width=90, size=12, height=30).pack(side="left", padx=2)
            btn(btn_col, "▶ Play", lambda pid=p["id"]: self._play_profile(pid),
                width=75, size=12, height=30, color=ACCENT, hover="#00c480").pack(side="left", padx=2)
            soft_btn(btn_col, "✎ Edit", lambda pid=p["id"]: self._edit_profile(pid),
                     width=65, size=12, height=30).pack(side="left", padx=2)
            danger_btn(btn_col, "✕", lambda pid=p["id"]: self._delete_profile(pid),
                       width=36, size=12, height=30).pack(side="left", padx=2)

            # Folder path hint
            folder_row = ctk.CTkFrame(card, fg_color="transparent")
            folder_row.pack(fill="x", padx=16, pady=(4, 12))
            profile_dir = self.profiles.get_dir(p["id"])
            label(folder_row, f"📁 {profile_dir}", size=10, color=SUBTEXT).pack(side="left")
            soft_btn(folder_row, "Open Folder", lambda d=profile_dir: self._open_folder(d),
                     width=90, size=11, height=24).pack(side="left", padx=8)

    def _new_profile(self):
        ProfileEditorDialog(self, self.profiles, self._versions_cache,
                            on_save=self._refresh_profiles)

    def _edit_profile(self, pid):
        p = self.profiles.get(pid)
        if p:
            ProfileEditorDialog(self, self.profiles, self._versions_cache,
                                profile=p, on_save=self._refresh_profiles)

    def _set_active_profile(self, pid):
        self.profiles.set_active(pid)
        self._refresh_profiles()

    def _play_profile(self, pid):
        self.profiles.set_active(pid)
        self._switch("Play")

    def _delete_profile(self, pid):
        p = self.profiles.get(pid)
        if not p:
            return
        if messagebox.askyesno("Delete Profile",
                               f"Delete profile '{p['name']}'?\n\nThis will permanently remove its folder including mods, saves and screenshots."):
            self.profiles.delete(pid)
            self._refresh_profiles()

    def _open_folder(self, path):
        def _open():
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(p)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        threading.Thread(target=_open, daemon=True).start()

    # ── Versions Page ─────────────────────────────────────────────────────────
    def _page_versions(self, f):
        header = ctk.CTkFrame(f, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))
        label(header, "Minecraft Versions", size=22, weight="bold").pack(side="left")
        btn(header, "↻  Refresh", self._load_versions, width=110).pack(side="right")

        filt = ctk.CTkFrame(f, fg_color="transparent")
        filt.pack(fill="x", padx=24, pady=12)
        self.ver_filter = StringVar(value="release")
        for t, lbl_text in [("release", "Release"), ("snapshot", "Snapshot"), ("old_beta", "Old Beta"), ("all", "All")]:
            rb = ctk.CTkRadioButton(filt, text=lbl_text, variable=self.ver_filter, value=t,
                                    command=self._filter_versions,
                                    fg_color=ACCENT, hover_color="#00c480",
                                    font=ctk.CTkFont("Segoe UI", 12))
            rb.pack(side="left", padx=10)

        self.ver_frame = ctk.CTkScrollableFrame(f, fg_color=PANEL, corner_radius=12)
        self.ver_frame.pack(fill="both", expand=True, padx=24, pady=(0, 24))

    def _load_versions(self):
        self.status_lbl.configure(text="Loading versions...")
        threading.Thread(target=self._fetch_versions, daemon=True).start()

    def _fetch_versions(self):
        try:
            self._versions_cache = mll.utils.get_version_list()
            self.after(0, self._filter_versions)
        except Exception as e:
            self.after(0, self._log, f"Failed to load versions: {e}")

    def _filter_versions(self):
        for w in self.ver_frame.winfo_children():
            w.destroy()
        filt = self.ver_filter.get()
        versions = self._versions_cache
        if filt != "all":
            versions = [v for v in versions if v.get("type") == filt]

        mc_base = APP_DIR / "mc_shared"
        installed = set()
        ver_path = mc_base / "versions"
        if ver_path.exists():
            installed = {p.name for p in ver_path.iterdir() if p.is_dir()}

        for v in versions:
            vid    = v["id"]
            vtype  = v.get("type", "")
            is_inst = vid in installed

            row = ctk.CTkFrame(self.ver_frame, fg_color=CARD, corner_radius=8, height=44)
            row.pack(fill="x", padx=4, pady=2)
            row.pack_propagate(False)

            dot_color = ACCENT if is_inst else BORDER
            ctk.CTkLabel(row, text="●", text_color=dot_color, font=ctk.CTkFont(size=10)).pack(side="left", padx=(12, 6), pady=10)
            label(row, vid, size=13, weight="bold").pack(side="left", pady=10)
            label(row, vtype, size=11, color=SUBTEXT).pack(side="left", padx=8, pady=10)
            if is_inst:
                label(row, "Installed", size=11, color=ACCENT).pack(side="left", pady=10)

            # Use in profile button
            soft_btn(row, "Use in Profile", lambda v=vid: self._use_version_in_profile(v),
                     width=110, size=12, height=30).pack(side="right", padx=4, pady=7)

        self.status_lbl.configure(text=f"{len(versions)} versions loaded")

    def _use_version_in_profile(self, ver_id):
        active = self.profiles.get_active()
        if active:
            if messagebox.askyesno("Update Profile",
                                   f"Set version '{ver_id}' on profile '{active['name']}'?"):
                self.profiles.update(active["id"], version=ver_id)
                self.status_lbl.configure(text=f"Profile updated to {ver_id}")
                self._switch("Play")
        else:
            messagebox.showinfo("No Profile", "No active profile. Create one in the Profiles tab first.")

    # ── Accounts Page ─────────────────────────────────────────────────────────
    def _page_accounts(self, f):
        header = ctk.CTkFrame(f, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 12))
        label(header, "Account Manager", size=22, weight="bold").pack(side="left")

        add_row = ctk.CTkFrame(f, fg_color="transparent")
        add_row.pack(fill="x", padx=24, pady=(0, 16))

        ms_card = styled_frame(add_row)
        ms_card.pack(side="left", padx=(0, 12), ipadx=10, ipady=10)
        label(ms_card, "Microsoft Account", size=14, weight="bold", color=ACCENT2).pack(anchor="w", padx=14, pady=(12, 2))
        label(ms_card, "Login with Microsoft browser flow\n(may not work without Azure app)", size=11, color=SUBTEXT).pack(anchor="w", padx=14)
        btn(ms_card, "Add via Microsoft Login", self._add_ms, color=ACCENT2, hover="#0090d0", width=200).pack(padx=14, pady=(6, 4))
        btn(ms_card, "Add via Access Token", self._add_ms_token, color="#5a5a8a", hover="#7070aa", width=200).pack(padx=14, pady=(0, 10))

        off_card = styled_frame(add_row)
        off_card.pack(side="left", ipadx=10, ipady=10)
        label(off_card, "Offline Account", size=14, weight="bold", color=ACCENT).pack(anchor="w", padx=14, pady=(12, 2))
        label(off_card, "Play without authentication\n(offline / LAN only)", size=11, color=SUBTEXT).pack(anchor="w", padx=14)
        self.offline_entry = ctk.CTkEntry(off_card, placeholder_text="Username", width=180,
                                          fg_color=BG, border_color=BORDER, text_color=TEXT,
                                          font=ctk.CTkFont("Segoe UI", 12))
        self.offline_entry.pack(padx=14, pady=(8, 4))
        btn(off_card, "Add Offline Account", self._add_offline, width=180).pack(padx=14, pady=(0, 10))

        ctk.CTkFrame(f, height=1, fg_color=BORDER).pack(fill="x", padx=24, pady=8)
        label(f, "SAVED ACCOUNTS", size=10, color=SUBTEXT).pack(anchor="w", padx=24, pady=(0, 6))

        self.acc_list_frame = ctk.CTkScrollableFrame(f, fg_color=PANEL, corner_radius=12)
        self.acc_list_frame.pack(fill="both", expand=True, padx=24, pady=(0, 24))

    def _refresh_accounts(self):
        for w in self.acc_list_frame.winfo_children():
            w.destroy()
        if not self.accounts.accounts:
            label(self.acc_list_frame, "No accounts added yet.", size=13, color=SUBTEXT).pack(pady=30)
            return
        for acc in self.accounts.accounts:
            is_active = acc["id"] == self.accounts.active
            row = ctk.CTkFrame(self.acc_list_frame, fg_color=CARD, corner_radius=10, height=58)
            row.pack(fill="x", padx=4, pady=3)
            row.pack_propagate(False)

            dot = "●" if is_active else "○"
            ctk.CTkLabel(row, text=dot, text_color=ACCENT if is_active else SUBTEXT,
                         font=ctk.CTkFont(size=16)).pack(side="left", padx=(14, 8), pady=10)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", pady=10)
            label(info, acc["username"], size=14, weight="bold").pack(anchor="w")
            type_color = ACCENT2 if acc["type"] == "microsoft" else ACCENT
            label(info, acc["type"].title(), size=11, color=type_color).pack(anchor="w")

            if not is_active:
                btn(row, "Set Active", lambda aid=acc["id"]: self._set_active(aid),
                    color=BORDER, hover=CARD, width=90, size=12).pack(side="right", padx=6, pady=12)
            danger_btn(row, "Remove", lambda aid=acc["id"]: self._remove_acc(aid), width=80, size=12).pack(side="right", padx=(0, 6), pady=12)

    def _add_offline(self):
        username = self.offline_entry.get().strip()
        if not username:
            messagebox.showwarning("No Username", "Please enter a username."); return
        if len(username) < 3 or len(username) > 16:
            messagebox.showwarning("Invalid Username", "Username must be 3-16 characters."); return
        self.accounts.add_offline(username)
        self.offline_entry.delete(0, "end")
        self._refresh_accounts()
        self._log(f"Added offline account: {username}")

    def _add_ms(self):
        win = ctk.CTkToplevel(self)
        win.title("Microsoft Login")
        win.minsize(480, 360)
        win.resizable(True, True)
        win.configure(fg_color=PANEL)
        win.grab_set()
        win.update_idletasks()
        px = self.winfo_x() + self.winfo_width()  // 2 - 240
        py = self.winfo_y() + self.winfo_height() // 2 - 180
        win.geometry(f"480x360+{px}+{py}")

        label(win, "Microsoft Login", size=18, weight="bold").pack(pady=(24, 4))
        label(win, "Your browser will open — sign in, then come back here.",
              size=11, color=SUBTEXT).pack()

        status_card = ctk.CTkFrame(win, fg_color=CARD, corner_radius=12)
        status_card.pack(padx=24, pady=16, fill="x")
        status_lbl = label(status_card, "Opening browser...", size=13, color=ACCENT)
        status_lbl.pack(pady=(16, 16))

        log_box = ctk.CTkTextbox(
            win, height=100, fg_color=CARD, text_color=SUBTEXT,
            font=ctk.CTkFont("Consolas", 11), state="disabled",
            wrap="word", corner_radius=8
        )
        log_box.pack(fill="both", expand=True, padx=24, pady=(0, 4))

        cancel_btn = soft_btn(win, "Cancel", win.destroy, width=100)
        cancel_btn.pack(pady=(4, 16))

        def _log_append(msg):
            log_box.configure(state="normal")
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def on_success(acc):
            self.accounts.add_microsoft(acc)
            win.after(0, win.destroy)
            self.after(0, self._refresh_accounts)
            self.after(0, self._log, f"Added Microsoft account: {acc['username']}")

        def on_error(err):
            win.after(0, lambda: status_lbl.configure(text="Login failed", text_color=DANGER))
            win.after(0, lambda: _log_append(f"Error: {err}"))
            win.after(0, lambda: cancel_btn.configure(text="Close"))

        def on_log(msg):
            win.after(0, lambda m=msg: _log_append(m))

        def on_browser_open(login_url):
            win.after(0, lambda: status_lbl.configure(
                text="Waiting for you to sign in...", text_color=ACCENT))

        threading.Thread(
            target=ms_do_auth,
            args=(on_log, on_success, on_error, on_browser_open),
            daemon=True
        ).start()

    def _add_ms_token(self):
        """Add a Microsoft account by pasting an access token directly."""
        import time as _time
        import requests as _req

        win = ctk.CTkToplevel(self)
        win.title("Add Account via Token")
        win.minsize(480, 320)
        win.resizable(True, True)
        win.configure(fg_color=PANEL)
        win.grab_set()
        win.update_idletasks()
        px = self.winfo_x() + self.winfo_width()  // 2 - 240
        py = self.winfo_y() + self.winfo_height() // 2 - 160
        win.geometry(f"480x320+{px}+{py}")

        label(win, "Add Account via Token", size=18, weight="bold").pack(pady=(20, 2))
        label(win, "Paste your Minecraft access token below.\nGet it from your launcher's launcher_profiles.json\nor any Minecraft auth tool.",
              size=11, color=SUBTEXT).pack()

        token_card = ctk.CTkFrame(win, fg_color=CARD, corner_radius=12)
        token_card.pack(padx=24, pady=12, fill="x")
        label(token_card, "Access Token:", size=12).pack(anchor="w", padx=14, pady=(12, 2))
        token_var = StringVar()
        token_entry = ctk.CTkEntry(token_card, textvariable=token_var,
                                   placeholder_text="eyJhbGci...",
                                   fg_color=BG, border_color=BORDER, text_color=TEXT,
                                   font=ctk.CTkFont("Consolas", 11), height=36, show="")
        token_entry.pack(fill="x", padx=14, pady=(0, 12))

        status_lbl = label(win, "", size=11, color=SUBTEXT)
        status_lbl.pack()

        def _submit():
            token = token_var.get().strip()
            if not token:
                status_lbl.configure(text="Please paste a token first.", text_color=DANGER)
                return
            status_lbl.configure(text="Verifying token...", text_color=ACCENT)
            win.update()
            try:
                prof = _req.get(
                    "https://api.minecraftservices.com/minecraft/profile",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                if prof.status_code == 401:
                    status_lbl.configure(text="Token is invalid or expired.", text_color=DANGER)
                    return
                prof.raise_for_status()
                pj = prof.json()
                if "error" in pj:
                    status_lbl.configure(text=f"Error: {pj.get('errorMessage', pj['error'])}", text_color=DANGER)
                    return
                acc = {
                    "type":             "microsoft",
                    "username":         pj["name"],
                    "uuid":             pj["id"],
                    "access_token":     token,
                    "ms_refresh_token": "",
                    "token_expiry":     _time.time() + 86400,
                    "id":               str(uuid.uuid4()),
                }
                self.accounts.add_microsoft(acc)
                win.destroy()
                self._refresh_accounts()
                self._log(f"Added Microsoft account: {pj['name']}")
            except Exception as e:
                status_lbl.configure(text=f"Error: {e}", text_color=DANGER)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=8)
        btn(btn_row, "Add Account", _submit, color=ACCENT, hover="#00c47a", width=150).pack(side="left", padx=6)
        soft_btn(btn_row, "Cancel", win.destroy, width=100).pack(side="left", padx=6)

    def _set_active(self, aid):
        self.accounts.set_active(aid)
        self._refresh_accounts()

    def _remove_acc(self, aid):
        if messagebox.askyesno("Remove Account", "Remove this account?"):
            self.accounts.remove(aid)
            self._refresh_accounts()

    # ── Settings Page ─────────────────────────────────────────────────────────
    def _page_settings(self, f):
        label(f, "Settings", size=22, weight="bold").pack(anchor="w", padx=24, pady=(24, 16))

        scroll = ctk.CTkScrollableFrame(f, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        def section(title):
            ctk.CTkFrame(scroll, height=1, fg_color=BORDER).pack(fill="x", pady=(16, 8))
            label(scroll, title, size=10, color=SUBTEXT).pack(anchor="w")

        def row(lbl_text, widget_builder):
            r = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=10, height=52)
            r.pack(fill="x", pady=3)
            r.pack_propagate(False)
            label(r, lbl_text, size=13).pack(side="left", padx=16, pady=10)
            widget_builder(r)

        section("JAVA")
        self.java_var = StringVar(value=self.settings.java)
        def build_java(r):
            e = ctk.CTkEntry(r, textvariable=self.java_var, width=260, placeholder_text="Auto-detect",
                             fg_color=BG, border_color=BORDER, text_color=TEXT,
                             font=ctk.CTkFont("Segoe UI", 12))
            e.pack(side="right", padx=16)
        row("Default Java Executable", build_java)

        section("DATA")
        info_card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=10)
        info_card.pack(fill="x", pady=3)
        label(info_card, f"Launcher data: {APP_DIR}", size=11, color=SUBTEXT).pack(anchor="w", padx=16, pady=4)
        label(info_card, f"Profiles dir:  {PROFILES_DIR}", size=11, color=SUBTEXT).pack(anchor="w", padx=16, pady=4)
        label(info_card, f"Shared MC:     {APP_DIR / 'mc_shared'}", size=11, color=SUBTEXT).pack(anchor="w", padx=16, pady=(4, 12))
        soft_btn(info_card, "Open Data Folder", lambda: self._open_folder(APP_DIR), width=150).pack(anchor="w", padx=16, pady=(0, 12))

        btn(scroll, "Save Settings", self._save_settings, width=160).pack(anchor="w", pady=16)

    def _save_settings(self):
        self.settings.java = self.java_var.get().strip()
        self.settings.save()
        self.status_lbl.configure(text="Settings saved ✓")


    def _page_skin(self, f):
        """Skin picker with 2D flat preview and slim/normal toggle."""
        from tkinter import Canvas
        import json as _json

        SKIN_F = APP_DIR / "skin.json"

        def _load_state():
            try:
                return _json.loads(SKIN_F.read_text())
            except Exception:
                return {"path": None, "slim": False}

        def _save_state(path, slim):
            SKIN_F.write_text(_json.dumps({"path": str(path) if path else None, "slim": slim}))

        state = _load_state()
        _skin_path = [Path(state["path"]) if state["path"] else None]
        _slim      = [bool(state["slim"])]

        # ── Header ────────────────────────────────────────────────────────────
        label(f, "Skin", size=22, weight="bold").pack(anchor="w", padx=24, pady=(24, 4))

        # Notice banner
        notice = ctk.CTkFrame(f, fg_color="#2a1f0a", corner_radius=8)
        notice.pack(fill="x", padx=24, pady=(0, 16))
        label(notice,
              "⚠  Skins are client-side only. Other players will not see your skin unless "
              "they are on the same server with a skin mod, or you are using a skin server.",
              size=11, color="#f0a030", wraplength=700).pack(anchor="w", padx=14, pady=10)

        body = ctk.CTkFrame(f, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24)

        # ── Left: controls ────────────────────────────────────────────────────
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="y", padx=(0, 24))

        ctrl_card = ctk.CTkFrame(left, fg_color=CARD, corner_radius=12)
        ctrl_card.pack(fill="x", pady=(0, 12))

        label(ctrl_card, "Skin File", size=13, weight="bold").pack(anchor="w", padx=16, pady=(14, 4))
        path_lbl = label(ctrl_card, "No skin selected", size=11, color=SUBTEXT)
        path_lbl.pack(anchor="w", padx=16, pady=(0, 8))

        def _pick():
            from tkinter import filedialog
            p = filedialog.askopenfilename(
                title="Select Skin PNG",
                filetypes=[("PNG Image", "*.png")],
                parent=f.winfo_toplevel()
            )
            if p:
                _skin_path[0] = Path(p)
                path_lbl.configure(text=Path(p).name)
                _save_state(_skin_path[0], _slim[0])
                _redraw()

        btn(ctrl_card, "Browse PNG...", _pick, width=180).pack(anchor="w", padx=16, pady=(0, 14))

        # Arm style
        label(ctrl_card, "Arm Style", size=13, weight="bold").pack(anchor="w", padx=16, pady=(4, 6))
        arm_var = StringVar(value="Slim" if _slim[0] else "Normal")
        seg = ctk.CTkSegmentedButton(ctrl_card, values=["Normal", "Slim"],
                                     variable=arm_var,
                                     fg_color=BG, selected_color=ACCENT,
                                     selected_hover_color="#00c47a",
                                     unselected_color=PANEL,
                                     text_color=TEXT, width=180)
        seg.pack(anchor="w", padx=16, pady=(0, 14))

        def _on_arm_change(val):
            _slim[0] = (val == "Slim")
            _save_state(_skin_path[0], _slim[0])
            _redraw()
        seg.configure(command=_on_arm_change)

        # Info
        info_card = ctk.CTkFrame(left, fg_color=CARD, corner_radius=12)
        info_card.pack(fill="x")
        label(info_card, "How to use", size=12, weight="bold").pack(anchor="w", padx=16, pady=(12, 4))
        label(info_card,
              "1. Pick your 64×64 skin PNG\n"
              "2. Choose Normal or Slim arms\n"
              "3. Use CustomSkinLoader mod\n"
              "   for others to see your skin",
              size=11, color=SUBTEXT, justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # ── Right: skin viewer canvas ─────────────────────────────────────────
        right = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12)
        right.pack(side="left", fill="both", expand=True)

        label(right, "Preview", size=13, weight="bold").pack(pady=(14, 4))

        canvas = Canvas(right, bg="#1a1d24", highlightthickness=0, width=220, height=340)
        canvas.pack(pady=(0, 14))

        SCALE = 4  # each MC pixel = 4 canvas pixels

        def _draw_placeholder():
            canvas.delete("all")
            # Draw a simple steve silhouette outline as placeholder
            W, H = 220, 340
            cx = W // 2
            # head
            canvas.create_rectangle(cx-16, 20, cx+16, 52, outline=SUBTEXT, fill="#2a2d34", width=1)
            canvas.create_text(cx, 36, text="?", fill=SUBTEXT, font=("Segoe UI", 18, "bold"))
            # body
            canvas.create_rectangle(cx-12, 56, cx+12, 100, outline=SUBTEXT, fill="#2a2d34", width=1)
            # left arm
            aw = 6 if not _slim[0] else 5
            canvas.create_rectangle(cx-12-aw*2, 56, cx-12, 100, outline=SUBTEXT, fill="#2a2d34", width=1)
            # right arm
            canvas.create_rectangle(cx+12, 56, cx+12+aw*2, 100, outline=SUBTEXT, fill="#2a2d34", width=1)
            # left leg
            canvas.create_rectangle(cx-12, 104, cx, 148, outline=SUBTEXT, fill="#2a2d34", width=1)
            # right leg
            canvas.create_rectangle(cx, 104, cx+12, 148, outline=SUBTEXT, fill="#2a2d34", width=1)
            canvas.create_text(cx, 180, text="No skin selected", fill=SUBTEXT,
                               font=("Segoe UI", 10))

        def _draw_skin(img):
            """Draw a flat front-facing skin preview from the PIL image."""
            try:
                from PIL import Image as PILImage, ImageTk
            except ImportError:
                canvas.delete("all")
                canvas.create_text(110, 170, text="Pillow not installed.\npip install Pillow",
                                   fill=SUBTEXT, font=("Segoe UI", 11), justify="center")
                return

            canvas.delete("all")
            S = SCALE
            cx = 110  # canvas center x
            oy = 10   # y offset from top

            skin = img.convert("RGBA")
            W, H = skin.size
            if W < 64 or H < 32:
                canvas.create_text(110, 170, text="Invalid skin size", fill=SUBTEXT,
                                   font=("Segoe UI", 11))
                return

            is64x64 = (H >= 64)

            def paste_region(sx, sy, sw, sh, dx, dy, flip=False):
                """Crop a region from skin and draw it on canvas at (dx,dy)."""
                region = skin.crop((sx, sy, sx+sw, sy+sh))
                if flip:
                    region = region.transpose(PILImage.FLIP_LEFT_RIGHT)
                region = region.resize((sw*S, sh*S), PILImage.NEAREST)
                tk_img = ImageTk.PhotoImage(region)
                canvas._skin_imgs = getattr(canvas, "_skin_imgs", [])
                canvas._skin_imgs.append(tk_img)
                canvas.create_image(dx, dy, anchor="nw", image=tk_img)

            arm_w = 3 if _slim[0] else 4  # slim = 3px wide, normal = 4px

            # Head front face: skin[8,8 -> 16,16]
            paste_region(8, 8, 8, 8,  cx - 4*S, oy)
            # Hat layer
            paste_region(40, 8, 8, 8, cx - 4*S, oy)

            # Body front: skin[20,20 -> 28,32]  (8 wide, 12 tall)
            paste_region(20, 20, 8, 12, cx - 4*S, oy + 8*S)

            # Right arm front (player's right = left on screen)
            paste_region(44, 20, arm_w, 12, cx - (4+arm_w)*S, oy + 8*S)

            # Left arm front - mirrored from right if old skin format
            if is64x64:
                paste_region(36, 52, arm_w, 12, cx + 4*S, oy + 8*S)
            else:
                paste_region(44, 20, arm_w, 12, cx + 4*S, oy + 8*S, flip=True)

            # Right leg front
            paste_region(4, 20, 4, 12, cx - 4*S, oy + 20*S)

            # Left leg front - mirrored if old format
            if is64x64:
                paste_region(20, 52, 4, 12, cx, oy + 20*S)
            else:
                paste_region(4, 20, 4, 12, cx, oy + 20*S, flip=True)

        def _redraw():
            canvas._skin_imgs = []
            if not _skin_path[0] or not _skin_path[0].exists():
                _draw_placeholder()
                return
            try:
                from PIL import Image as PILImage
                img = PILImage.open(_skin_path[0])
                _draw_skin(img)
            except ImportError:
                _draw_placeholder()
            except Exception as e:
                canvas.delete("all")
                canvas.create_text(110, 170, text=f"Error: {e}", fill=DANGER,
                                   font=("Segoe UI", 10), width=200, justify="center")

        # Load saved skin on open
        if _skin_path[0] and _skin_path[0].exists():
            path_lbl.configure(text=_skin_path[0].name)
        _redraw()

    def _page_info(self, f):
        label(f, "Info", size=22, weight="bold").pack(anchor="w", padx=24, pady=(24, 20))

        # Made by card
        made_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        made_card.pack(padx=24, pady=(0, 16), fill="x")
        label(made_card, "Made by 1 person", size=15, weight="bold").pack(anchor="w", padx=20, pady=(18, 4))
        label(made_card, "NovaLauncher is a solo project built from scratch.", size=11, color=SUBTEXT).pack(anchor="w", padx=20, pady=(0, 18))

        # Contacts card
        contacts_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        contacts_card.pack(padx=24, fill="x")
        label(contacts_card, "Contact", size=15, weight="bold").pack(anchor="w", padx=20, pady=(18, 12))

        def contact_row(icon, platform, value):
            row = ctk.CTkFrame(contacts_card, fg_color=PANEL, corner_radius=8)
            row.pack(fill="x", padx=20, pady=(0, 10))
            ctk.CTkLabel(row, text=f" {icon}  {platform}", text_color=SUBTEXT,
                         font=ctk.CTkFont("Segoe UI", 12), width=100, anchor="w").pack(side="left", padx=(12, 0), pady=12)
            ctk.CTkLabel(row, text=value, text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 13, "bold"), anchor="w").pack(side="left", padx=8, pady=12)

        contact_row("💬", "Discord", "abdulladark")
        contact_row("✉", "Email", "abdullawaleed1977@gmail.com")

        ctk.CTkFrame(contacts_card, height=1, fg_color="transparent").pack(pady=4)


if __name__ == "__main__":
    app = NovaLauncher()
    app.mainloop()
