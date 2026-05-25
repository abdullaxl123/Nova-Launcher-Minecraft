# Nova Launcher v1.1

A Minecraft Java Edition launcher
If it gets false detected its because its a pyinstaller or because i have no signature

## Features

- **Profiles** each profile has its own folder containing mods, saves, screenshots, resource packs, shader packs and logs
- **Software chooser** Vanilla, Fabric or Forge per profile
- **Per-profile RAM** set RAM allocation independently per profile with a slider
- **Mod manager** add/remove `.jar` mod files directly from the profile editor
- **Shared asset cache** Minecraft versions, assets and libraries are downloaded once and shared across all profiles
- **Microsoft & offline accounts**
- **Play tab** profile dropdown instead of version dropdown; badge shows version, software, RAM and mod count

## Profile Isolation

Each profile lives at:
```
%APPDATA%\.nova_launcher\profiles\<profile-id>\
    mods\
    saves\
    screenshots\
    resourcepacks\
    shaderpacks\
    logs\
```

Minecraft versions/assets/libraries are shared at:
```
%APPDATA%\.nova_launcher\mc_shared\
```

## Setup

```
pip install -r requirements.txt
python launcher.py
```

## Build EXE

```
BUILD_EXE.bat
```
