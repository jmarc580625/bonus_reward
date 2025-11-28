# bonus_reward

`bonus_reward` is a small automation script that claims the **daily bonus** on  
[https://video.a2e.ai/](https://video.a2e.ai/) using Google Chrome and Selenium.

The script:

- Starts or reuses a Chrome instance with **remote debugging**.
- Attaches a Selenium WebDriver to that instance.
- Navigates to the site and checks whether you are logged in.
- Finds and clicks the **daily bonus trigger**.
- Handles the **bonus claim dialog**:
  - Logs the next available time when the bonus is still on cooldown.
  - Clicks the primary claim button when the bonus is available.
- Logs all actions to `logs/bonus_reward_logs.txt`.

---

## Repository layout

```text
bonus_reward/
├─ bonus_reward.py        # Main Python script
├─ bonus_reward.ps1       # PowerShell wrapper
├─ drivers/               # Driver files (third‑party component)
└─ README.md              # This file
```
---
## Requirements

- Windows
- Python 3.9 or newer
- Google Chrome (installed)
- ChromeDriver matching your Chrome version

Python packages:

- `selenium`

All Python packages are installed with `pip` inside a virtual environment as described below.

---
## Selenium driver (ChromeDriver)
ChromeDriver is a third‑party component and is not shipped by this project.

1. Install Google Chrome.
2. Read Selenium’s official documentation about browser drivers:
https://www.selenium.dev/documentation/webdriver/getting_started/install_drivers/
3. Download the ChromeDriver version matching your Chrome version.
4. Extract the executable to:
```text
drivers/chromedriver-win64/chromedriver.exe
```
5. In `bonus_reward.py`, make sure the driver path points to this location, for example:
```python
self.driver_path = "drivers/chromedriver-win64/chromedriver.exe"
```

---
## Creating and using a virtual environment
The virtual environment is *not* part of this project. It is created and managed separately.

From the project root (`bonus_reward/`):

1. Create a virtual environment:
```powershell
python -m venv venv
```
2. Activate the virtual environment (PowerShell):
```powershell
.\venv\Scripts\Activate.ps1
```
3. Upgrade pip and install dependencies:
```powershell
python -m pip install --upgrade pip
pip install selenium
```
4. Deactivate when finished:
```powershell
deactivate
```
All further commands in this README assume an activated virtual environment.

---
## Running the script
### Run with Python
From the project root with the virtual environment active:

```powershell
python .\bonus_reward.py
```
Example output:

```text
2025-11-27 12:15:02 [INFO] bonus_reward - Option force_restart=False
2025-11-27 12:15:02 [INFO] bonus_reward - Port 9222 is open; Reusing existing Chrome instance through this debug port
2025-11-27 12:15:04 [INFO] bonus_reward - Navigated to https://video.a2e.ai/
2025-11-27 12:15:08 [INFO] bonus_reward - Claim dialog is not visible; opening via trigger
2025-11-27 12:15:09 [INFO] bonus_reward - Claim dialog is open
...
```
### Run with PowerShell wrapper
```powershell
.\bonus_reward.ps1
```
The wrapper runs 
bonus_reward.py
 and appends a completion line to the log:

```text
2025-11-27 12:15:12 [INFO] bonus_reward.ps1 - Script completed successfully
```

---
## Runtime behaviour
### Chrome control
The script uses a remote‑debugging port (by default 9222) to attach Selenium to Chrome.

Two options control Chrome lifecycle (configured in `bonus_reward.py`):

- `force_restart`
  - True → existing Chrome using the debug port is terminated, a new Chrome instance is started.
  - False → an existing Chrome instance on the debug port is reused when available.
- `stop_chrome_on_exit`
  - True → Chrome is stopped when the script exits.
  - False → Chrome remains running after the script completes.

### Login handling
- The script checks for the presence of the site login button.
- When login is required, the script asks the user to perform a manual login, stops and leaves Chrome open.
- Successful manual login is a prerequisite for the script to succeed.

### Bonus dialog handling
- The script first checks whether the daily bonus dialog is already visible.
- When it is not visible, it opens the dialog via the bonus trigger and waits for the dialog element
(`<div role="dialog" class="... modal-checkIn ...">`) to appear.
- The wait timeout is:
  - 5 seconds when `force_restart=True`.
  - 15 seconds when `force_restart=False` to better tolerate background‑tab throttling.
- The claim button is located using stable CSS classes (primary action button), not by visible text, so it works across different interface languages.
- When the dialog contains a cooldown message, the next available time is parsed and logged:
```text
[WARNING] bonus_reward - Daily cannot be claimed before YYYY-MM-DD HH:MM:SS
```
- When no cooldown is present, the script clicks the primary claim button via JavaScript and logs success.

---
## Logs
All activity is written to `logs/bonus_reward_logs.txt`.

Example entries:

```text
2025-11-27 12:15:08 [INFO] bonus_reward - Claim dialog is not visible; opening via trigger
2025-11-27 12:15:09 [INFO] bonus_reward - Claim dialog is open
2025-11-27 12:15:09 [INFO] bonus_reward - Looking for claim button
2025-11-27 12:15:09 [INFO] bonus_reward - Clicking claim button via JavaScript
2025-11-27 12:15:09 [INFO] bonus_reward - Daily bonus claim sequence completed successfully
2025-11-27 12:15:12 [INFO] bonus_reward.ps1 - Script completed successfully
```

This file is the main source of information for diagnosing selector changes, timing issues, or login problems.

---
## Scheduling
The script can be started automatically on Windows using *Task Scheduler*.

Typical setup:

Program: `python`
Arguments: `bonus_reward.py`
Start in: `d:\bonus_reward`

Alternatively:

- Program: `powershell.exe`
- Arguments: `-File d:\bonus_reward\bonus_reward.ps1`
- Configure `force_restart` and `stop_chrome_on_exit` in `bonus_reward.py` to match the intended unattended behaviour.

---
## Disclaimer
This project automates interaction with a third‑party website.
Use it responsibly and in accordance with the website’s terms of service.
Google Chrome and ChromeDriver are third‑party products; consult their respective licenses and documentation.