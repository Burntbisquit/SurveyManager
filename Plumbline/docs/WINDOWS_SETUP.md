# Plumbline on Windows - setup guide

*Written for someone who has never used a command line.*

> **Honest note.** Plumbline was written and tested on Linux. I have **not** been able to run it on a Windows PC.
> What I did check: the whole test suite passes on Python 3.14; pip's resolver finds ready-made Windows (64-bit)
> builds of every library for it; the Python download links work; and I rehearsed the typed setup in Step 3
> (virtual environment, `pip install`, editable install, health check) on Linux with Python 3.14.
> If something fails anyway, copy the text from the PowerShell window and send it to me - on a first Windows run that is normal.

## The short version

1. **Python 3.14 (64-bit)** - or 3.13 - installed, with `py` and `python` working in PowerShell (Step 1).
   3.14 is the version Plumbline is tested on and the one the scripts pick when it is available.
2. **Get the project folder** - download the workspace and extract it (Step 2).
3. **Set it up** - type five commands in PowerShell (Step 3), or double-click `install_windows.bat`.
4. **Start it** - double-click `Plumbline.bat` (Step 4).

You need Windows 10 or 11 (64-bit), an internet connection for step 3, and about 1 GB of disk space.

---

## Step 1 - Python, `py` and `python`

### 1a. See what you have

Open PowerShell (Start menu, type `powershell`, press Enter) and run these one at a time:

```powershell
py --list
python --version
py -3.14 -c "import sys; print(sys.executable)"
```

| You see | It means |
|---|---|
| `py --list` prints a line with `3.14` (or `3.13`) | `py` works |
| `python --version` prints `Python 3.14.x` | `python` works |
| the third command prints a path | that is where Python lives, and it shows *how* it was installed (below) |

**If the first two work, PATH is fine - go to Step 2.**

Plumbline needs **Python 3.13 or newer**. **3.14 is recommended** - it is what this release is built and
tested against, and the setup scripts prefer it. 3.13 also passes the whole test suite, so it works too;
3.12 and older do not, and 3.15 is not supported yet (PySide6 has no build for it).
If `py --list` shows no `3.14` line, go to 1d. Other versions installed next to 3.14 do no harm - `py -3.14` always picks the right one.

The path from the third command tells you which of the next two sections applies:

* it contains `\AppData\Local\Python\` (no `Programs` in it) or `\WindowsApps\` - **Python install manager** (python.org's
  current default download, or the Microsoft Store). Read 1b.
* it contains `\AppData\Local\Programs\Python\` or `\Program Files\Python` - **classic installer**. Read 1c.
* nothing printed, or an error - look at Start, **Installed apps**, search "python". *Python Install Manager* means 1b;
  *Python 3.14.x (64-bit)* means 1c; nothing at all means 1d.

### 1b. Installed with the Python install manager: do not edit PATH

The manager provides `python` and `py` itself, through Windows "app execution aliases", so there is nothing to add to PATH
(editing PATH by hand can even get in its way). If one of the commands fails:

1. Start menu, type **Manage app execution aliases**, press Enter.
2. Find the **Python (default)** entries (`python.exe`, `python3.exe`) and the **Python install manager** entries (`py.exe`,
   `pymanager.exe`). Make sure they are **On**. If they already are, switch them **Off** and **On** again to refresh them.
3. If the list also has `python.exe` / `python3.exe` entries called **App Installer**, switch those **Off** - that is the
   Microsoft Store shortcut that grabs the command.
4. Close PowerShell, open a new one, and repeat 1a.

If `py` says *"can't open file"*, the old "Python launcher" is hiding the new `py`: Start, **Installed apps**, search
"Python launcher", **Uninstall**.

When the manager installs a Python it may offer to add `%LocalAppData%\Python\bin` to PATH. That is optional (it only adds
names like `python3.14.exe`); you can say no.

### 1c. Installed with the classic installer: add Python to PATH

The classic installer has a box **Add python.exe to PATH** on its first screen. If it was not ticked, fix it one of two ways.

**Easiest:** Start, **Installed apps**, find *Python 3.14.x (64-bit)*, click the three dots, **Modify**, **Modify**, **Next**,
tick **Add Python to environment variables**, **Install**.

**By hand:**

1. Start menu, type `environment variables`, choose **Edit environment variables for your account**.
2. In the top box (*User variables*) click **Path**, then **Edit**.
3. Click **New**, type the first line below, then **New** again for each of the others:

   ```
   %LocalAppData%\Programs\Python\Python314\
   %LocalAppData%\Programs\Python\Python314\Scripts\
   %LocalAppData%\Programs\Python\Launcher\
   ```

   The third line makes `py` work; skip it if `py --list` already worked. If Python was
   installed for all users, the folders are `C:\Program Files\Python314\` and `C:\Program Files\Python314\Scripts\`.
4. Click **OK**, then **OK** again. Close PowerShell, open a new one, and repeat 1a.

`%LocalAppData%` is Windows' shortcut for `C:\Users\<you>\AppData\Local`. To check that a folder exists, paste it into the
address bar of File Explorer.

If typing `python` still opens the Microsoft Store: in the Path list select your Python lines and click **Move Up** until
they are above the `...\WindowsApps` line, or switch the *App Installer* `python.exe` aliases off (1b, point 3).

### 1d. No Python yet

Download the **64-bit** installer, run it, tick **Add python.exe to PATH**, click **Install Now**, and at the end click
**Disable path length limit** if you see it (answer Yes to the Windows question):

* Python 3.14.8: <https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe>
  (or the release page, <https://www.python.org/downloads/release/python-3148/>: scroll to *Files*, choose *Windows installer (64-bit)*)

(python.org's default button now downloads the *Python install manager* instead; that works too - after installing it, type
`py install 3.14` in PowerShell - and then you need no PATH steps at all.)
On a Windows-on-ARM laptop (Snapdragon) still choose the 64-bit (AMD64) installer.

---

## Step 2 - Get the project folder

1. In this workspace use the **download** option for the whole workspace. You get one `.zip` file.
2. Optional, but it avoids a security warning later: right-click the zip, choose **Properties**, tick **Unblock** at the bottom
   (if you see it), click **OK**.
3. Right-click the zip, choose **Extract All...**, then **Extract**.
4. Open the new folder. Keep opening folders named `plumbline` until you can see `README.md`, `pyproject.toml`,
   `requirements.txt` and `Plumbline.bat` side by side. That is the **project folder**.

**Where to put it:** somewhere short, like `C:\Users\<your name>\plumbline`. Avoid very deep folders and cloud-synced ones
(OneDrive, Desktop, Documents): the install is slow there and very long paths can make it fail.
Do not move or rename the folder after step 3 (if you do, just repeat Step 3).

## Step 3 - Set it up by typing

Open PowerShell **in the project folder**: in File Explorer open the folder (the one with `README.md`), click the address
bar, type `powershell`, press Enter. The prompt should end with `...\plumbline>`.

Run these one at a time and wait for the prompt to come back before the next one.

```powershell
py -3.14 -m venv .venv
```

Makes a private environment in a new `.venv` folder. A few seconds; it prints nothing when it works.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Downloads and installs the libraries: about 250 MB, several minutes, and a lot of scrolling text is normal. It ends with
`Successfully installed ...`.

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Installs Plumbline itself into that environment. `-e` ("editable") means it keeps using the files in your folder, so scripts and
plugins you add take effect. `--no-deps` because the libraries are already in.

```powershell
.\.venv\Scripts\python.exe -m plumbline doctor
```

The health check. Every library should say `ok`, and it ends with *Everything Plumbline needs is installed and working.*

```powershell
.\.venv\Scripts\python.exe -m plumbline
```

Opens Plumbline.

**Why `.\.venv\Scripts\python.exe` and not just `python`?** That is the private environment's own Python, so the command works
no matter what PATH says, and `.\` is how PowerShell is told "the file in this folder". Many guides "activate" the environment
instead; see the optional part below.

**Optional - activate the environment.** After this, `python` and `pip` in that PowerShell window mean the private ones:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

The first line (needed once; answer `Y`) allows PowerShell to run local scripts - Windows blocks them by default with
*"running scripts is disabled on this system"*. When it worked the prompt starts with `(.venv)`. Type `deactivate` to leave.

### Shortcut: double-click

`install_windows.bat` does the same four setup commands in one go (it finds Python 3.14, or 3.13, through `py`). Double-click it, wait
for *All done*. Windows may ask *"Are you sure you want to run this?"* or show a blue *"Windows protected your PC"* box: click
**Run**, or **More info** then **Run anyway** (the file is plain text; right-click, **Edit** to read it first).

## Step 4 - Start Plumbline

Double-click **`Plumbline.bat`** (it works with the `.venv` you just made), or type `.\Plumbline.bat` in PowerShell.

* A black window opens, then the Plumbline window. The very first start can take up to a minute (Windows checks the new files
  and the plotting library builds a font list). Later starts are quick.
* **Leave the black window open.** It is Plumbline's engine - closing it closes the program - and it is where error messages appear.
* In the Welcome window click **Open the sample project (synthetic site)**, then follow the *10-minute tour* in `README.md`.
* Handy: drag a `.plb` project onto `Plumbline.bat` to open it. To start it from the desktop, right-click `Plumbline.bat`, choose
  **Send to**, then **Desktop (create shortcut)** (on Windows 11: **Show more options** first).

---

## Troubleshooting

| What you see | What it means and what to do |
|---|---|
| `'py' is not recognized`, or typing `python` opens the Microsoft Store | Step 1 (1b or 1c, depending on how Python was installed). |
| `py` says *"can't open file"* | The old Python launcher is hiding the new one - see 1b. |
| *"running scripts is disabled on this system"* | Only when activating (`Activate.ps1`). Skip activation and use `.\.venv\Scripts\python.exe`, or run the `Set-ExecutionPolicy` line from Step 3. |
| Red text: *"Could not find a version that satisfies the requirement ..."* | Almost always the wrong Python: older than 3.13, newer than 3.14, or 32-bit. Check `py --list` and use 3.14 (or 3.13), 64-bit. |
| *"Read timed out"*, *"Connection ..."*, *SSL* errors | Something is blocking the download (firewall, proxy, flaky Wi-Fi). Try another network, or ask IT to allow `pypi.org` and `files.pythonhosted.org`. Then run the failed command again - pip carries on. |
| *"No such file or directory"* with a very long path, or *"Windows Long Path support"* | The folder is too deep. Move the project to something short like `C:\plumbline`, make sure you clicked **Disable path length limit** when installing Python, delete the `.venv` folder (`Remove-Item -Recurse -Force .venv`), and repeat Step 3. |
| *"DLL load failed while importing ..."* (QtCore, shapely, anything) | Microsoft's Visual C++ runtime is missing. Install <https://aka.ms/vs/17/release/vc_redist.x64.exe>, restart Windows, then run the `doctor` command again. |
| Very slow first start, or antivirus pops up | It is scanning the freshly installed files. Wait a minute. Adding the project folder to the antivirus exclusions helps. |
| QGIS, PostGIS or similar is installed and coordinate systems or GIS files misbehave | Those programs sometimes set `PROJ_LIB` / `GDAL_DATA` for the whole PC. `Plumbline.bat` clears them for Plumbline. If you start Plumbline by typing, clear them first: `Remove-Item Env:PROJ_LIB, Env:PROJ_DATA, Env:GDAL_DATA, Env:GDAL_DRIVER_PATH -ErrorAction SilentlyContinue`. The `doctor` command tells you if any are set. |
| The window opens but something is broken | Run the `doctor` command (Step 3, or `.\Plumbline.bat doctor`) and send me its output plus any red text. |

**Start over cleanly:** delete the `.venv` folder (`Remove-Item -Recurse -Force .venv`) and repeat Step 3.
Your settings, plugins and imagery cache live in `C:\Users\<you>\.plumbline` and are not touched.

**Uninstall:** delete the project folder and `C:\Users\<you>\.plumbline`. (Python itself is under *Installed apps*.)

---

## Quick answers

### What is PATH? Does it have to do with .py files?

No - they are two separate things.

* **PATH** is a Windows setting: a list of folders that Windows searches when you type a program's name in a terminal.
  "Add python.exe to PATH" adds Python's folder to that list, so typing `python` works from any folder.
  (The Python install manager has no such box: it provides `python` and `py` through app execution aliases instead - see 1b.)
* **.py files** are just text files that contain Python code. Which program opens them when you double-click is a different
  setting (a *file association*); the Python installer sets that up by itself.

To check PATH, open a **new** PowerShell window (one that was already open before you installed Python does not know about it)
and type `python --version`. A version number means it is set. *"Python was not found; run without arguments to install from
the Microsoft Store"* or *"'python' is not recognized"* means it is not (the Store message comes from a Windows shortcut, not
from a real Python). More detail: `where.exe python` lists what Windows finds, and
`$env:Path -split ';' | Select-String python` shows the PATH entries that mention Python.

You may not need `python` on PATH at all: the typed setup uses `py` and the environment's own `python.exe`.

### Is Plumbline.bat the "portable" version? Is anything installed?

Plumbline itself is not installed: there is no installer, nothing is added to the Start menu or the registry, and no administrator
rights are needed. The project folder is the program, and deleting it removes it (plus the settings folder, below).
`Plumbline.bat` is only a small text file - open it in Notepad to see - that starts the program from that folder.

It is **not** a fully portable stand-alone `.exe`, though:

* Python 3.13 or newer must be installed on the computer (3.14 recommended). The `.venv` folder (Plumbline's private set of libraries) depends on it.
* Do not copy or move the folder and expect it to work. After moving it on the same PC, repeat Step 3.
  For a second PC: copy the project folder there (without `.venv`) and do Steps 1 and 3 on that PC.
* Your settings, plugins and imagery cache live in `C:\Users\<you>\.plumbline`, outside the folder.

A true double-click `Plumbline.exe` with Python bundled inside (nothing to install) is possible later, but it has to be built on a
Windows machine, and it is worth doing only after this setup is confirmed to work.

---

## A command-line crash course

You do not need this for the setup above, but it helps to know what the commands in `README.md` and in my messages mean.

### What is bash, and what do I use on Windows?

A **command line** (also called a *terminal* or *shell*) is a window where you type an instruction and press Enter instead of
clicking. **bash** is the one used on Linux and Mac. On Windows the same idea is called **PowerShell** (or the older
**Command Prompt**). You do not need bash for Plumbline.

### Open one in the right folder

1. Open the project folder in File Explorer.
2. Click the address bar (the box showing the folder's path), type `powershell`, press **Enter**.

A window opens showing something like `PS C:\Users\you\plumbline>`. That is the *prompt*: it shows where you are. Type after it.
Don't type the `PS C:\...>` part when copying examples.

### The commands that cover most things

| To do this | bash (Linux / Mac) | PowerShell (Windows) |
|---|---|---|
| Show where you are | `pwd` | `pwd` |
| List what is here | `ls` | `dir` (`ls` works too) |
| Go into a folder | `cd name` | `cd name` |
| Go up one folder | `cd ..` | `cd ..` |
| Make a folder | `mkdir name` | `mkdir name` |
| Copy a file | `cp a b` | `copy a b` |
| Show a text file | `cat file` | `type file` |
| Clear the screen | `clear` | `cls` |
| Run a program in this folder | `./prog` | `.\prog` |
| Stop whatever is running | Ctrl+C | Ctrl+C |

Tips that save a lot of frustration:

* Press **Tab** to finish a name (type `cd plum` then Tab). Press the **Up arrow** to bring back the last command.
* A path with spaces needs quotes: `cd "C:\Users\Jane Doe\My Jobs"`.
* To paste, right-click in the window. **Ctrl+C does not copy there - it stops the running command.**
* In PowerShell you must type `.\` before a program in the current folder: `.\Plumbline.bat`, not `Plumbline.bat`.
* Anything after a `#` is a comment for humans. You can leave it out.

### Plumbline's commands

Run these from PowerShell opened in the project folder:

```powershell
.\Plumbline.bat                                   # open the program
.\Plumbline.bat job.plb                           # open a project (or import a CSV / DXF / LandXML / GIS file)
.\Plumbline.bat doctor                            # check the installation; send me the output if anything is wrong
.\Plumbline.bat info job.plb                      # print a summary of a project
.\Plumbline.bat export-dxf job.plb out.dxf        # write a DXF without opening the window
.\Plumbline.bat run myscript.py job.plb --save out.plb     # run a Python script on a project
.\Plumbline.bat sample sample_data                # (re)write the sample files
```

`README.md` shows the same things as `python -m plumbline ...`. `Plumbline.bat` simply runs that inside Plumbline's own private
Python environment, so you can use either idea: `.\.venv\Scripts\python.exe -m plumbline doctor` and `.\Plumbline.bat doctor`
do the same job.

### Want real bash on Windows?

Not needed for Plumbline. If you ever want it: install *Git for Windows* (it includes **Git Bash**), or run `wsl --install` in
PowerShell for a complete Linux inside Windows.
