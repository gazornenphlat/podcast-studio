"""Content Scheduler – system tray launcher.

Runs the web GUI + reminder loop in the background and puts an icon in the
system tray (Windows notification area / macOS menu bar / Linux tray).

Run:   pythonw tray.py      (Windows – no console window)
       python3 tray.py      (macOS / Linux)
"""
import os, socket, subprocess, sys, threading, time, webbrowser

from PIL import Image, ImageDraw

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import app as core


# ---------------- icon ----------------
def make_icon(alert=False):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 8, 60, 60), 9, fill=(37, 99, 235))      # calendar body
    d.rounded_rectangle((4, 8, 60, 22), 9, fill=(29, 78, 216))      # header band
    d.rectangle((4, 16, 60, 22), fill=(29, 78, 216))
    for x in (19, 45):                                               # rings
        d.rounded_rectangle((x - 3, 2, x + 3, 15), 2, fill=(255, 255, 255))
    d.line((18, 40, 28, 50, 47, 30), fill=(255, 255, 255), width=6, joint="curve")   # check mark
    if alert:                                                         # red badge = reminders waiting
        d.ellipse((38, 0, 64, 26), fill=(220, 38, 38), outline=(255, 255, 255), width=3)
    return img

ICON_OK, ICON_ALERT = make_icon(False), make_icon(True)


# ---------------- helpers ----------------
def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

def open_gui(*_): webbrowser.open(core.local_url())

def open_folder(*_):
    path = core.BASE
    if sys.platform.startswith("win"): os.startfile(path)
    elif sys.platform == "darwin": subprocess.Popen(["open", path])
    else: subprocess.Popen(["xdg-open", path])

def notify(icon, title, msg):
    try: icon.notify(msg, title)
    except Exception: pass            # not every Linux tray supports balloons

def open_reminders():
    with core.LOCK: d = core.load_data()
    return [r for r in d["reminders"] if r["status"] == "open" and not r.get("snoozed_until")]

def in_background(fn, done_msg):
    def run(icon, _item):
        def work():
            try: fn(); notify(icon, "Content Scheduler", done_msg)
            except Exception as ex: notify(icon, "Content Scheduler - error", str(ex))
        threading.Thread(target=work, daemon=True).start()
    return run

def run_check(): core.daily_check()
def test_reminder():
    errs = core.send_channels("Test reminder", "Content Scheduler is working.")
    if errs: raise RuntimeError("; ".join(errs))
def backup_now():
    with core.LOCK: core.save_data(core.load_data()); core.backup(force=True)


# ---------------- status watcher ----------------
def watch(icon):
    seen = {r["id"] for r in open_reminders()}
    while True:
        try:
            rems = open_reminders()
            icon.icon = ICON_ALERT if rems else ICON_OK
            icon.title = f"Content Scheduler - {len(rems)} reminder(s) waiting" if rems else "Content Scheduler - all caught up"
            new = [r for r in rems if r["id"] not in seen]
            if new:
                notify(icon, new[-1]["title"] if len(new) == 1 else f"{len(new)} new reminders",
                       new[-1]["body"].split("\n")[0])
            seen = {r["id"] for r in rems}
            icon.update_menu()
        except Exception as ex:
            print("tray watch error:", ex)
        time.sleep(20)


def main():
    core.load_config()
    if port_in_use(core.CFG["app"]["port"]):     # already running → just open the window
        open_gui(); return

    import pystray            # imported only once we know we're the first instance
    core.start_background()
    threading.Thread(target=core.serve_forever, daemon=True).start()

    def reminders_label(_item):
        n = len(open_reminders())
        return f"{n} reminder(s) waiting" if n else "All caught up"

    def quit_app(icon, _item): icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Content Scheduler", open_gui, default=True),   # default = double/left click
        pystray.MenuItem(reminders_label, open_gui),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Run today's check now", in_background(run_check, "Today's check ran.")),
        pystray.MenuItem("Send test reminder", in_background(test_reminder, "Test reminder sent.")),
        pystray.MenuItem("Back up now", in_background(backup_now, "Backup saved.")),
        pystray.MenuItem("Open app folder (config.yaml)", open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("content_scheduler", ICON_OK, "Content Scheduler", menu)

    def setup(ic):
        ic.visible = True
        threading.Thread(target=watch, args=(ic,), daemon=True).start()
        if core.CFG["app"].get("open_browser_on_start"): open_gui()

    icon.run(setup)        # blocks on the main thread (required on macOS); Quit returns here
    os._exit(0)            # stop the web server + loop threads


if __name__ == "__main__":
    main()
