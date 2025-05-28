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
MPY_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/scripts/mpymaker"

# Backup
#SRC_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Backup/src"

# ---------------------------

RPI_INIT_FP = "/Volumes/RPI-RP2"
RPI_CIRCUITPYTHON_PATH = "/Volumes/CIRCUITPY"
TIMEOUT_THRESHOLD = 60  # seconds

def update_mpy_files():
    """Run mpymaker.py to ensure all .mpy files are up to date"""
    mpymaker_path = os.path.join(MPY_FOLDER_FP, "mpymaker.py")
    
    # Check if mpymaker directory and script exist
    if not os.path.exists(MPY_FOLDER_FP) or not os.path.exists(mpymaker_path):
        print("Warning: mpymaker folder or mpymaker.py not found. Skipping .mpy file updates.")
        return False
    
    print("\nUpdating .mpy files to ensure they're current...")
    try:
        # Change to the mpymaker directory so the script runs in correct context
        current_dir = os.getcwd()
        os.chdir(MPY_FOLDER_FP)
        
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

def get_all_available_mpy_files():
    """Get a list of all available .mpy files in the mpymaker folder"""
    mpy_files = []
    
    if os.path.exists(MPY_FOLDER_FP):
        for file in os.listdir(MPY_FOLDER_FP):
            if file.endswith('.mpy'):
                base_name = file.split('.')[0]
                mpy_files.append(base_name)
    
    return mpy_files

def copy_files_to_device(src_folder, dest_folder, mpy_files=None):
    """
    Copy files from src_folder to dest_folder.
    If mpy_files list is provided, substitute .py files with .mpy versions from the mpymaker folder.
    """
    if not mpy_files:
        # Traditional copy - just copy everything
        print(f"Copying all files from {src_folder} to {dest_folder}")
        copy_tree(src_folder, dest_folder)
        return True
    
    # Custom copy with .mpy substitution
    mpy_files_clean = []
    for file in mpy_files:
        # Strip extension if present
        base_name = file.split('.')[0]
        mpy_files_clean.append(base_name)
    
    print(f"Will use .mpy versions for these files: {', '.join(mpy_files_clean)}")
    
    # Get .mpy files available in the mpymaker folder (use configured MPY_FOLDER_FP)
    available_mpy_files = {}
    mpy_folder = MPY_FOLDER_FP
    if os.path.exists(mpy_folder):
        for file in os.listdir(mpy_folder):
            if file.endswith('.mpy'):
                base_name = file.split('.')[0]
                available_mpy_files[base_name] = os.path.join(mpy_folder, file)
    
    # Walk through source directory and copy files
    for root, dirs, files in os.walk(src_folder):
        # Skip mpymaker and .vscode directories
        if any(folder in root.split(os.sep) for folder in ["mpymaker", ".vscode"]):
            continue
        
        # Create corresponding directory in destination
        rel_path = os.path.relpath(root, src_folder)
        dest_dir = os.path.join(dest_folder, rel_path) if rel_path != '.' else dest_folder
        
        # Create destination directory if it doesn't exist
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        # Copy files, substituting .mpy versions when specified
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_dir, file)
            
            # Check if this file should be substituted with .mpy version
            base_name = file.split('.')[0]
            # never substitute core code and useraddons
            if file.endswith('.py') and base_name in mpy_files_clean and base_name in available_mpy_files \
               and base_name not in ('code','useraddons','boot'):
                # Use .mpy version instead
                mpy_file = available_mpy_files[base_name]
                dest_mpy_file = os.path.join(dest_dir, f"{base_name}.mpy")
                print(f"Using {os.path.basename(mpy_file)} instead of {file}")
                shutil.copy2(mpy_file, dest_mpy_file)
            else:
                # Copy original file
                shutil.copy2(src_file, dest_file)
    
    return True

def flash_device(mpy_files=None):
    # Always update .mpy files first
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
            success = copy_files_to_device(SRC_FOLDER_FP, RPI_CIRCUITPYTHON_PATH, mpy_files)
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
        
        # Prompt for MPY file substitution
        use_mpy = input("Swap to mpy files? (y/n, default: n): ").strip().lower()
        
        mpy_files = None
        if use_mpy == 'y':
            mpy_input = input("Enter files to convert to .mpy (comma delimited, 'all' for all files, no extension required): ").strip()
            
            if mpy_input.lower() == 'all':
                # Use all available .mpy files
                mpy_files = get_all_available_mpy_files()
                print(f"Using all {len(mpy_files)} available .mpy files")
            elif mpy_input:
                # Use specific files
                mpy_files = [f.strip() for f in mpy_input.split(',')]
        
        print("Connect the device and press Enter to start...")
        input()  # Wait for user to press Enter
        
        if flash_device(mpy_files):
            print("Device flashed successfully. You can connect another device.")
        else:
            print("Flashing failed. Please check the device and try again.")

if __name__ == "__main__":
    main()