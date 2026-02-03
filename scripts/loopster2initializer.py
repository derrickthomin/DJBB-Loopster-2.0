import shutil
import sys
import os
import time
import subprocess

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

# Frozen UF2 settings
BUILD_FROZEN_PATH = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/z_frozentest"
FROZEN_UF2_OUTPUT_DIR = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/uf2 current"
FROZEN_UF2_NAME = "loopster.uf2"

# Backup
# SRC_FOLDER_FP = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Backup/src"

# ---------------------------

RPI_INIT_FP = "/Volumes/RPI-RP2"
RPI_CIRCUITPYTHON_PATH = "/Volumes/CIRCUITPY"
TIMEOUT_THRESHOLD = 100  # seconds

# Import build_frozen module
sys.path.insert(0, BUILD_FROZEN_PATH)
try:
    import build_frozen
    BUILD_FROZEN_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import build_frozen module: {e}")
    BUILD_FROZEN_AVAILABLE = False

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

def get_frozen_uf2_path():
    """Return the full path to the frozen UF2 file"""
    return os.path.join(FROZEN_UF2_OUTPUT_DIR, FROZEN_UF2_NAME)

def check_frozen_uf2_exists():
    """Check if the frozen UF2 file already exists"""
    return os.path.exists(get_frozen_uf2_path())

def build_or_get_frozen_uf2():
    """
    Handle frozen UF2 logic: check if exists, prompt to rebuild, build if needed.
    Returns tuple: (uf2_path, frozen_modules) or (None, None) if failed.
    """
    if not BUILD_FROZEN_AVAILABLE:
        print("ERROR: build_frozen module not available. Cannot use frozen UF2.")
        return None, None
    
    frozen_uf2_path = get_frozen_uf2_path()
    existing_uf2 = check_frozen_uf2_exists()
    
    should_build = False
    
    if existing_uf2:
        print(f"Found existing frozen UF2: {frozen_uf2_path}")
        rebuild_input = input("Rebuild frozen UF2? (y/n, default: n): ").strip().lower()
        should_build = (rebuild_input == 'y')
    else:
        print(f"No existing frozen UF2 found at: {frozen_uf2_path}")
        print("Will build frozen UF2...")
        should_build = True
    
    if should_build:
        print("\nBuilding frozen UF2 firmware...")
        print("(This may take a few minutes and may prompt for disk mounting)")
        
        result = build_frozen.build_frozen_firmware(
            src_folder=SRC_FOLDER_FP,
            output_dir=FROZEN_UF2_OUTPUT_DIR,
            output_name=FROZEN_UF2_NAME
        )
        
        if result['success']:
            print(f"Frozen UF2 built successfully: {result['uf2_path']}")
            return result['uf2_path'], result['frozen_modules']
        else:
            print("ERROR: Failed to build frozen UF2")
            return None, None
    else:
        # Use existing UF2 - get frozen modules list from build_frozen module
        print("Using existing frozen UF2")
        frozen_modules = build_frozen.FREEZE_MODULES
        return frozen_uf2_path, frozen_modules

def copy_files_to_device(src_folder, dest_folder, use_mpy=False, frozen_modules=None):
    """
    Copy files from src_folder to dest_folder.
    If use_mpy is True, use .mpy versions for all .py files EXCEPT those in MPY_EXCLUDE_FILES.
    .mpy files are saved to the /lib directory, excluded .py files and non-.py files stay in their normal locations.
    If frozen_modules is provided, skip any .py file that's in the frozen_modules list (already in firmware).
    """
    # Convert frozen_modules filenames to base names for comparison
    frozen_base_names = set()
    if frozen_modules:
        for f in frozen_modules:
            # Handle both 'module.py' and 'module' formats
            base = f.replace('.py', '') if f.endswith('.py') else f
            frozen_base_names.add(base)
        print(f"Frozen modules (will skip): {', '.join(sorted(frozen_base_names))}")
    
    if not use_mpy and not frozen_modules:
        # Traditional copy - just copy everything (ORIGINAL BEHAVIOR)
        print(f"Copying all files from {src_folder} to {dest_folder}")
        shutil.copytree(src_folder, dest_folder, dirs_exist_ok=True)
        return True
    
    if frozen_modules:
        print(f"Using frozen UF2 - only copying filesystem files and lib/ folder")
    elif use_mpy:
        print(f"Using .mpy files for all modules EXCEPT: {', '.join(MPY_EXCLUDE_FILES)}")
        print("(.mpy files will be saved to /lib directory)")
    
    # Get .mpy files available in the mpy_library folder
    available_mpy_files = {}
    if os.path.exists(MPY_FOLDER_FP):
        for file in os.listdir(MPY_FOLDER_FP):
            if file.endswith('.mpy'):
                base_name = file.split('.')[0]
                available_mpy_files[base_name] = os.path.join(MPY_FOLDER_FP, file)
    
    # Create lib directory for .mpy files and adafruit libraries
    lib_dir = os.path.join(dest_folder, 'lib')
    if not os.path.exists(lib_dir):
        os.makedirs(lib_dir)
    
    # Walk through source directory and copy files
    for root, dirs, files in os.walk(src_folder):
        # Skip .vscode and other non-essential directories
        if any(folder in root.split(os.sep) for folder in [".vscode", "__pycache__"]):
            continue
        
        # Determine if we're in the lib directory
        rel_path = os.path.relpath(root, src_folder)
        is_lib_folder = rel_path.startswith('lib') or rel_path == 'lib'
        
        # Create corresponding directory in destination
        dest_dir = os.path.join(dest_folder, rel_path) if rel_path != '.' else dest_folder
        
        # Create destination directory if it doesn't exist
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        # Copy files
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_dir, file)
            base_name = file.split('.')[0]
            
            # If using frozen modules, check if this file should be skipped
            if frozen_modules and not is_lib_folder:
                if file.endswith('.py') and base_name in frozen_base_names:
                    print(f"Skipping {file} (frozen in firmware)")
                    continue
            
            # Handle .py files
            if file.endswith('.py'):
                if frozen_modules:
                    # When using frozen UF2, copy remaining .py files directly (like boot.py, code.py)
                    print(f"Copying {file}")
                    shutil.copy2(src_file, dest_file)
                elif base_name in MPY_EXCLUDE_FILES:
                    # Always copy these as .py
                    print(f"Copying {file} (excluded from .mpy conversion)")
                    shutil.copy2(src_file, dest_file)
                elif use_mpy and base_name in available_mpy_files:
                    # Use .mpy version instead - save to lib directory
                    mpy_file = available_mpy_files[base_name]
                    dest_mpy_file = os.path.join(lib_dir, f"{base_name}.mpy")
                    print(f"Using {base_name}.mpy (saved to /lib) instead of {file}")
                    shutil.copy2(mpy_file, dest_mpy_file)
                else:
                    # No .mpy available or not using mpy, copy original .py
                    print(f"Copying {file} (no .mpy available)")
                    shutil.copy2(src_file, dest_file)
            else:
                # Non-.py files (json, bin, mpy, etc.) - always copy
                shutil.copy2(src_file, dest_file)
    
    return True

def flash_device(use_mpy=False, use_frozen=False, frozen_modules=None, frozen_uf2_path=None):
    # Update .mpy files first if we're using them
    if use_mpy:
        update_mpy_files()
    
    # Determine which UF2 to use
    uf2_to_flash = frozen_uf2_path if use_frozen else UF2_FP
    
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
            shutil.copy(uf2_to_flash, RPI_INIT_FP)
            ready_for_copy = True
            print(f"copied {os.path.basename(uf2_to_flash)} to RPI-RP2")
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
            success = copy_files_to_device(SRC_FOLDER_FP, RPI_CIRCUITPYTHON_PATH, use_mpy, frozen_modules)
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
        
        # Initialize frozen UF2 variables
        use_frozen = False
        frozen_modules = None
        frozen_uf2_path = None
        
        # Prompt for frozen UF2 first (default: no)
        use_frozen_input = input("Use frozen UF2? (y/n, default: n): ").strip().lower()
        use_frozen = (use_frozen_input == 'y')
        
        if use_frozen:
            if not BUILD_FROZEN_AVAILABLE:
                print("ERROR: build_frozen module not available. Falling back to standard UF2.")
                use_frozen = False
            else:
                frozen_uf2_path, frozen_modules = build_or_get_frozen_uf2()
                if frozen_uf2_path is None:
                    print("Failed to get frozen UF2. Falling back to standard UF2.")
                    use_frozen = False
                    frozen_modules = None
        
        # Only ask about .mpy if NOT using frozen UF2
        use_mpy = False
        if not use_frozen:
            # Prompt for MPY file substitution - simplified to y/n (ORIGINAL BEHAVIOR)
            use_mpy_input = input("Use .mpy files? (y/n, default: n): ").strip().lower()
            use_mpy = (use_mpy_input == 'y')
            
            if use_mpy:
                print(f"Will use .mpy for all files EXCEPT: {', '.join(MPY_EXCLUDE_FILES)}")
            else:
                print("Will use .py files only (no .mpy conversion)")
        else:
            print(f"Using frozen UF2: {frozen_uf2_path}")
            print(f"Frozen modules: {len(frozen_modules)} modules compiled into firmware")
        
        print("\nConnect the device and press Enter to start...")
        input()  # Wait for user to press Enter
        
        if flash_device(use_mpy, use_frozen, frozen_modules, frozen_uf2_path):
            print("Device flashed successfully. You can connect another device.")
        else:
            print("Flashing failed. Please check the device and try again.")

if __name__ == "__main__":
    main()