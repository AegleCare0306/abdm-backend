# Local Dev Environment Setup — Aegle Care EMR (ABDM Backend)

For anyone setting this up fresh on a Windows laptop (Aayush's or a teammate's).

---

## One-Time Setup

Do these once per machine.

### 1. Create the conda environment
```
conda create -n aegle-care python=3.12 -y
```

### 2. Activate it and install dependencies
```
conda activate aegle-care
cd path\to\repo
pip install -r requirements.txt
```

### 3. Install ngrok

Do **not** use `winget install` or `conda install` — both caused issues (winget's copy needed `ngrok update`, which corrupted the binary; antivirus quarantined it repeatedly). Install manually instead:

1. Download the Windows amd64 zip from https://ngrok.com/download
2. Extract `ngrok.exe` into `C:\ngrok\`
3. Add `C:\ngrok` to your **User PATH**: `Win+R` → `sysdm.cpl` → Advanced → Environment Variables → User variables → `Path` → Edit → New → `C:\ngrok`
4. Open a **new** Command Prompt and confirm: `ngrok version` (should be ≥ 3.20.0)

### 4. Exclude `C:\ngrok` from antivirus scanning

Antivirus (K7, Defender, etc.) may quarantine `ngrok.exe` on sight. Add a folder exclusion before it gets deleted again:

- **K7:** Setting → Real Time Protection → Manage Exclusions → Add Entry → Add Folder → `C:\ngrok`
- **Windows Defender:** Virus & threat protection → Manage settings → Exclusions → Add a folder → `C:\ngrok`

If `ngrok.exe` already got quarantined, restore it from the antivirus's quarantine list (check "add to exclusion before restore" if offered).

### 5. Add your ngrok authtoken
```
ngrok config add-authtoken <your-authtoken-from-ngrok-dashboard>
```

### 6. Set up the ngrok config file

Find the path with `ngrok config check` (typically `C:\Users\<you>\AppData\Local\ngrok\ngrok.yml`). Edit it to:

```yaml
version: "2"
authtoken: <your-token>
tunnels:
  aegle:
    proto: http
    addr: 8000
    domain: <your-static-domain>.ngrok-free.dev
```

(Free ngrok accounts get one permanent, randomly-assigned static domain — use whatever yours is.)

### 7. Install ngrok as a Windows service

Open Command Prompt **as Administrator** (Start → cmd → right-click → Run as administrator). Confirm elevation with `net session` (no error = elevated), then:

```
ngrok service install --config "C:\Users\<you>\AppData\Local\ngrok\ngrok.yml"
ngrok service start
```

Verify:
```
sc query ngrok
```
Should show `STATE: RUNNING`. It's registered `AUTO_START` by default, so it'll come up on its own on every boot — no need to repeat this step.

### 8. Update `server/config.py` if your domain differs

`CALLBACK_URL` is hardcoded there. If your assigned ngrok domain doesn't match what's already in the file, update it and re-register via `update_bridge_url()`.

---

## Every Time You Start Your System

Nothing manual for ngrok — it's a background service set to auto-start on boot. You only need to:

### 1. Activate the conda env
```
conda activate aegle-care
```

### 2. Start the FastAPI server
```
cd path\to\repo
uvicorn server.main:app --reload
```

That's it. Check `http://127.0.0.1:8000/health` locally, or your ngrok static domain externally, to confirm both are up.

### Quick sanity checks if something seems off
- `sc query ngrok` — confirms the tunnel service is running
- `http://127.0.0.1:4040` — ngrok's local dashboard, shows the active tunnel and domain
