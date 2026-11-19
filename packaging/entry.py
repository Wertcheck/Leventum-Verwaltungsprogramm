"""Einstiegspunkt des gebündelten Programms (PyInstaller). `LeventumServer.exe` (Konsole) startet den Browser-Modus, `Leventum.exe` das Fenster."""
import sys
from pathlib import Path

from leventum.desktop import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if Path(sys.executable).stem.lower().endswith("server") and "--browser" not in args:
        args = ["--browser", *args]
    main(args)
