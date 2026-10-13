"""
Build script to compile FocusShield into a single standalone .exe
"""

import subprocess
import sys
import os
import shutil

def build():
    print("=== Starting FocusShield .exe Build ===")
    
    # Clean previous builds
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
                print(f"Cleaned {folder}/")
            except Exception as e:
                print(f"Warning: Could not remove {folder}: {e}")

    # PyInstaller command
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name=FocusShield",
        "--icon=app_icon.ico",
        "--add-data=app_icon.ico;.",
        "--collect-all=customtkinter",
        "--clean",
        "gui.py"
    ]
    
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        exe_path = os.path.abspath(os.path.join("dist", "FocusShield.exe"))
        print("\n" + "="*50)
        print(f"[SUCCESS] Build Complete!")
        print(f"Executable created at: {exe_path}")
        print("="*50 + "\n")
        
        # Copy Restore_Internet.bat to dist/ as well so the user has the complete package in dist/
        dist_folder = os.path.abspath("dist")
        shutil.copy("Restore_Internet.bat", os.path.join(dist_folder, "Restore_Internet.bat"))
        print(f"Copied Restore_Internet.bat to dist/")
        
        # Also copy to root folder
        try:
            shutil.copy(exe_path, "FocusShield.exe")
            print("Copied FocusShield.exe to workspace root.")
        except Exception as e:
            print(f"Note: Could not copy to root (may be in use): {e}")
    else:
        print("\n[ERROR] Build failed with exit code:", result.returncode)

if __name__ == "__main__":
    build()
