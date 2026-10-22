# Double-click this file on Windows to start Content Scheduler in the system tray
# with no command window (.pyw files run with pythonw.exe).
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here); sys.path.insert(0, here)

# pythonw has no console: send any output/errors to a log file instead of losing them
log = open(os.path.join(here, "tray.log"), "a", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr = log

import tray
tray.main()
