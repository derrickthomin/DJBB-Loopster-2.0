import shutil
import sys
import os
import time
import subprocess
from distutils.dir_util import copy_tree

# ------ USER SETTINGS ------

NUKE = True  # If true, use nuke.uf2 first

# Update these depending on the device

# # Mini Slider
# NUKE_FP = "/Users/derrickthomin/Downloads/flash_nuke.uf2"
# UF2_FP = "/Users/derrickthomin/Downloads/adafruit-circuitpython-raspberry_pi_pico-en_US-8.1.0.uf2" 
# SRC_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/Mini Midi Slider/Production/src"

# RGB Loopster
NUKE_FP = "/Users/derrickthomin/Downloads/flash_nuke.uf2"
UF2_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/uf2 current/adafruit-circuitpython-raspberry_pi_pico-en_US-8.2.6.uf2"
SRC_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/src"
MPY_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/scripts/mpy_library"

# Backup
# SRC_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Backup/src"

# ---------------------------

RPI_INIT_FP = "/Volumes/RPI-RP2"
RPI_CIRCUITPYTHON_PATH = "/Volumes/CIRCUITPY"
TIMEOUT_THRESHOLD = 100  # seconds

def update_mpy_files():
    """Run mpymaker.py to ensure all .mpy files are up to date"""
    # mpymaker.py is in the scripts folder (parent of mpy_library)
    scripts_folder = os.path.dirname(MPY_FOLDER_FP)
    mpymaker_path = os.path.join(scripts_folder, "mpymaker.py")
    
    # Check if mpymaker script exists
    if not os.path.exists(mpymaker_path):
        print("Warning: mpymaker.py not found. Skipping .mpy file updates.")
        return False
    
    print("\nUpdating .mpy files to ensure they're current...")
    try:
        # Change to the scripts directory so the script runs in correct context
        current_dir = os.getcwd()
        os.chdir(scripts_folder)
        
        # Run mpymaker.py with "all" option to update all .mpy files
        result = subprocess.run(
            [sys.executable, "mpymaker.py"],
            input=b"all\n",  # Automatically select "all" option
            capture_output=True
        )
        
        # Return to original directory
        os.chdir(current_dir)
        
        if result.returncode == 0:
            print("All .mpy files successfully updated.")
            return True
        else:
            print("Warning: Error updating .mpy files.")
            print(f"mpymaker.py output: {result.stdout.decode('utf-8')}")
            print(f"mpymaker.py error: {result.stderr.decode('utf-8')}")
            return False
    except Exception as e:
        print(f"Error running mpymaker.py: {e}")
        return False

# Files that must always remain as .py (never convert to .mpy)
MPY_EXCLUDE_FILES = ['code', 'boot', 'useraddons']

def copy_files_to_device(src_folder, dest_folder, use_mpy=False):
    """
    Copy files from src_folder to dest_folder.
    If use_mpy is True, use .mpy versions for all .py files EXCEPT those in MPY_EXCLUDE_FILES.
    .mpy files are saved to the /lib directory, excluded .py files and non-.py files stay in their normal locations.
    """
    if not use_mpy:
        # Traditional copy - just copy everything
        print(f"Copying all files from {src_folder} to {dest_folder}")
        copy_tree(src_folder, dest_folder)
        return True
    
    print(f"Using .mpy files for all modules EXCEPT: {', '.join(MPY_EXCLUDE_FILES)}")
    print("(.mpy files will be saved to /lib directory)")
    
    # Get .mpy files available in the mpy_library folder
    available_mpy_files = {}
    if os.path.exists(MPY_FOLDER_FP):
        for file in os.listdir(MPY_FOLDER_FP):
            if file.endswith('.mpy'):
                base_name = file.split('.')[0]
                available_mpy_files[base_name] = os.path.join(MPY_FOLDER_FP, file)
    
    # Create lib directory for .mpy files
    lib_dir = os.path.join(dest_folder, 'lib')
    if not os.path.exists(lib_dir):
        os.makedirs(lib_dir)
    
    # Walk through source directory and copy files
    for root, dirs, files in os.walk(src_folder):
        # Skip .vscode and other non-essential directories
        if any(folder in root.split(os.sep) for folder in [".vscode", "__pycache__"]):
            continue
        
        # Create corresponding directory in destination
        rel_path = os.path.relpath(root, src_folder)
        dest_dir = os.path.join(dest_folder, rel_path) if rel_path != '.' else dest_folder
        
        # Create destination directory if it doesn't exist
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        # Copy files
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_dir, file)
            base_name = file.split('.')[0]
            
            # Handle .py files
            if file.endswith('.py'):
                if base_name in MPY_EXCLUDE_FILES:
                    # Always copy these as .py
                    print(f"Copying {file} (excluded from .mpy conversion)")
                    shutil.copy2(src_file, dest_file)
                elif base_name in available_mpy_files:
                    # Use .mpy version instead - save to lib directory
                    mpy_file = available_mpy_files[base_name]
                    dest_mpy_file = os.path.join(lib_dir, f"{base_name}.mpy")
                    print(f"Using {base_name}.mpy (saved to /lib) instead of {file}")
                    shutil.copy2(mpy_file, dest_mpy_file)
                else:
                    # No .mpy available, copy original .py
                    print(f"Copying {file} (no .mpy available)")
                    shutil.copy2(src_file, dest_file)
            else:
                # Non-.py files (json, bin, etc.) - always copy
                shutil.copy2(src_file, dest_file)
    
    return True

def flash_device(use_mpy=False):
    # Update .mpy files first if we're using them
    if use_mpy:
        update_mpy_files()
    
    time_prev = time.monotonic()

    # Nuke if needed
    if NUKE:
        try:
            shutil.copy(NUKE_FP, RPI_INIT_FP)
        except Exception as e:
            print(f"no folder named RPI-RP2 found {e}")
            return False

        print("Nuking...")

    # Copy UF2 to device
    ready_for_copy = False
    print("Waiting for RPI-RP2 to mount...")
    while not ready_for_copy:
        try:
            shutil.copy(UF2_FP, RPI_INIT_FP)
            ready_for_copy = True
            print("copied uf2 to RPI-RP2")
            time_prev = time.monotonic()
        except:
            print("Retrying in 2s...")
            time.sleep(2)

        if time.monotonic() - time_prev > TIMEOUT_THRESHOLD:
            print("Timeout")
            return False

    time.sleep(10)

    # Copy src files to CIRCUITPY
    success = False
    print("Waiting for CIRCUITPY to mount...")
    time_prev = time.monotonic()
    while not success:
        try:
            success = copy_files_to_device(SRC_FOLDER_FP, RPI_CIRCUITPYTHON_PATH, use_mpy)
            if success:
                print("Success")
            time_prev = time.monotonic()
        except Exception as e:
            print(f"Retrying in 2s... Error: {e}")
            time.sleep(2)

        if time.monotonic() - time_prev > TIMEOUT_THRESHOLD * 2:
            print("Timeout")
            return False

    return True

def main():
    while True:
        print("\nReady to flash a new device.")
        
        # Prompt for MPY file substitution - simplified to y/n
        use_mpy_input = input("Use .mpy files? (y/n, default: n): ").strip().lower()
        use_mpy = (use_mpy_input == 'y')
        
        if use_mpy:
            print(f"Will use .mpy for all files EXCEPT: {', '.join(MPY_EXCLUDE_FILES)}")
        else:
            print("Will use .py files only (no .mpy conversion)")
        
        print("\nConnect the device and press Enter to start...")
        input()  # Wait for user to press Enter
        
        if flash_device(use_mpy):
            print("Device flashed successfully. You can connect another device.")
        else:
            print("Flashing failed. Please check the device and try again.")

if __name__ == "__main__":
    main()