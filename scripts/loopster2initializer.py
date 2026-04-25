import shutil
import sys
import os
import time
import subprocess
import zipfile
import tempfile

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

# Release settings
RELEASES_FOLDER = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/releases"

# Files to copy to release (not frozen into UF2)
RELEASE_FILES = ['boot.py', 'code.py', 'presets.json', 'useraddons.py', 'font5x8.bin']

# README content for release zip
RELEASE_README = """DJBB Loopster Update Instructions
==================================

1. While holding the BOOT button (small button near the lower right corner of the screen),
   plug the Loopster into your computer. It should mount as a drive called "RPI-RP2".

2. Drag the "loopster.uf2" file onto the RPI-RP2 drive.
   The device will reboot and remount as "CIRCUITPY" or "LOOPSTER".
   If it doesn't appear after ~30 seconds, just continue to the next step.

3. Unplug the Loopster, then hold the FN button and plug it back in.

4. Delete all existing files on the device.

4. Copy the entire contents of the "files" folder to the now-empty drive:
   - boot.py
   - code.py
   - presets.json
   - useraddons.py
   - font5x8.bin
   - lib/ (entire folder)
   - ... (all other files / folders in this folder)

5. Safely eject the drive. Your Loopster is updated!

For more info, visit: https://github.com/derrickthomin/DJBB-Loopster
"""

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

def list_existing_releases():
    """List existing release folders"""
    if not os.path.exists(RELEASES_FOLDER):
        return []
    
    releases = []
    for item in os.listdir(RELEASES_FOLDER):
        item_path = os.path.join(RELEASES_FOLDER, item)
        if os.path.isdir(item_path):
            releases.append(item)
    
    return sorted(releases)


def update_boot_release_comment(release_number):
    """Update src/boot.py with a release comment"""
    boot_path = os.path.join(SRC_FOLDER_FP, "boot.py")
    if not os.path.exists(boot_path):
        print("WARNING: boot.py not found in src folder. Skipping release comment update.")
        return False

    try:
        with open(boot_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        release_comment = f"# release {release_number}\n"
        updated = False

        # Replace existing release comment if found
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("# release "):
                lines[i] = release_comment
                updated = True
                break

        # Insert release comment near the top if not found
        if not updated:
            insert_index = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "" or stripped.startswith("import "):
                    insert_index = i + 1
                    continue
                break
            lines.insert(insert_index, release_comment)
            updated = True

        if updated:
            with open(boot_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"Updated boot.py with release comment: {release_number}")
        return updated
    except Exception as e:
        print(f"WARNING: Failed to update boot.py release comment: {e}")
        return False


def validate_release_runtime_files(files_folder, frozen_modules):
    """
    Validate that required runtime files are available either in filesystem or frozen firmware.
    This is especially important for Colm custom modules (e.g. pedals.py, mpu6050_minimal.py).
    """
    frozen_base_names = set()
    if frozen_modules:
        for f in frozen_modules:
            base = f.replace('.py', '') if f.endswith('.py') else f
            frozen_base_names.add(base)

    runtime_checks = [
        ("pedals", "src/pedals.py"),
        ("mpu6050_minimal", "src/mpu6050_minimal.py"),
    ]

    for module_name, relative_src in runtime_checks:
        src_path = os.path.join(SRC_FOLDER_FP, os.path.basename(relative_src))
        if not os.path.exists(src_path):
            continue  # Module not present in this project variant

        module_frozen = module_name in frozen_base_names
        module_py_on_fs = os.path.exists(os.path.join(files_folder, f"{module_name}.py"))
        module_mpy_on_fs = os.path.exists(os.path.join(files_folder, "lib", f"{module_name}.mpy"))

        if not (module_frozen or module_py_on_fs or module_mpy_on_fs):
            print(f"ERROR: Required runtime module missing: {module_name}")
            print("       Expected one of:")
            print("         - frozen in UF2")
            print(f"         - files/{module_name}.py")
            print(f"         - files/lib/{module_name}.mpy")
            return False

    return True


def generate_release(release_number):
    """
    Generate a release package:
    1. Rebuild the frozen UF2
    2. Create release folder structure
    3. Copy all needed files
    4. Create zip file
    """
    print(f"\n{'='*50}")
    print(f"Generating Release {release_number}")
    print(f"{'='*50}")
    
    if not BUILD_FROZEN_AVAILABLE:
        print("ERROR: build_frozen module not available. Cannot generate release.")
        return False
    
    # Step 1: Update boot.py release comment before building
    print("\nStep 1: Updating boot.py release comment...")
    update_boot_release_comment(release_number)

    # Step 2: Always rebuild the frozen UF2
    print("\nStep 2: Building frozen UF2 firmware...")
    print("(This may take a few minutes and may prompt for disk mounting)")
    
    result = build_frozen.build_frozen_firmware(
        src_folder=SRC_FOLDER_FP,
        output_dir=FROZEN_UF2_OUTPUT_DIR,
        output_name=FROZEN_UF2_NAME
    )
    
    if not result['success']:
        print("ERROR: Failed to build frozen UF2")
        return False
    
    frozen_uf2_path = result['uf2_path']
    print(f"Frozen UF2 built successfully: {frozen_uf2_path}")
    
    # Step 3: Create release folder structure
    print(f"\nStep 3: Creating release folder structure...")
    release_folder = os.path.join(RELEASES_FOLDER, release_number)
    files_folder = os.path.join(release_folder, "files")
    files_lib_folder = os.path.join(files_folder, "lib")
    
    # Create folders (remove existing if present)
    if os.path.exists(release_folder):
        print(f"Removing existing release folder: {release_folder}")
        shutil.rmtree(release_folder)
    
    os.makedirs(files_lib_folder)
    print(f"Created: {release_folder}")
    print(f"Created: {files_folder}")
    print(f"Created: {files_lib_folder}")
    
    # Step 4: Copy UF2 to release folder
    print(f"\nStep 4: Copying files...")
    dest_uf2 = os.path.join(release_folder, FROZEN_UF2_NAME)
    shutil.copy2(frozen_uf2_path, dest_uf2)
    print(f"Copied: {FROZEN_UF2_NAME}")
    
    # Step 5: Copy all runtime filesystem files, excluding frozen modules
    # This guarantees Colm-specific modules (e.g., pedals.py, mpu6050_minimal.py)
    # are included whenever they are not frozen into the UF2.
    print("Copying runtime filesystem files (frozen-aware)...")
    success = copy_files_to_device(
        SRC_FOLDER_FP,
        files_folder,
        use_mpy=False,
        frozen_modules=result.get('frozen_modules')
    )
    if not success:
        print("ERROR: Failed to copy runtime files into release package")
        return False

    # Validate critical runtime modules before creating zip
    if not validate_release_runtime_files(files_folder, result.get('frozen_modules')):
        print("ERROR: Release validation failed")
        return False
    
    # Step 6: Create zip file containing everything
    print(f"\nStep 6: Creating zip file...")
    zip_filename = f"loopster_{release_number}.zip"
    zip_path = os.path.join(release_folder, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add all files in the release folder (except the zip itself)
        for root, dirs, files in os.walk(release_folder):
            for file in files:
                if file.endswith('.zip'):
                    continue  # Skip the zip file itself
                file_path = os.path.join(root, file)
                # Create archive name relative to release folder
                arcname = os.path.relpath(file_path, release_folder)
                zipf.write(file_path, arcname)
                print(f"  Added to zip: {arcname}")
        
        # Add README.txt to zip only (not as a separate file)
        zipf.writestr("README.txt", RELEASE_README)
        print(f"  Added to zip: README.txt")
    
    print(f"\nCreated: {zip_filename}")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Release {release_number} generated successfully!")
    print(f"{'='*50}")
    print(f"\nRelease folder: {release_folder}")
    print(f"Contents:")
    print(f"  - {FROZEN_UF2_NAME}")
    print(f"  - files/")
    print(f"      - runtime filesystem files (frozen-aware copy from src/)")
    print(f"      - lib/")
    print(f"  - {zip_filename}")
    
    return True, release_folder, zip_path


def check_device_in_bootloader():
    """Check if a device is connected in bootloader mode (RPI-RP2 mounted)"""
    return os.path.exists(RPI_INIT_FP)


def test_release_from_zip(zip_path):
    """
    Test a release by extracting the zip and flashing a connected device.
    Returns True if successful, False otherwise.
    """
    print(f"\n{'='*50}")
    print("Testing Release from ZIP")
    print(f"{'='*50}")
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="loopster_release_test_")
    print(f"Created temp directory: {temp_dir}")
    
    try:
        # Extract zip to temp directory
        print(f"\nExtracting {os.path.basename(zip_path)}...")
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(temp_dir)
        print("Extraction complete.")
        
        # Find the UF2 file in extracted contents
        uf2_path = os.path.join(temp_dir, FROZEN_UF2_NAME)
        files_folder = os.path.join(temp_dir, "files")
        
        if not os.path.exists(uf2_path):
            print(f"ERROR: {FROZEN_UF2_NAME} not found in extracted zip")
            return False
        
        if not os.path.exists(files_folder):
            print("ERROR: files/ folder not found in extracted zip")
            return False
        
        print(f"Found UF2: {uf2_path}")
        print(f"Found files folder: {files_folder}")
        
        # Nuke if needed
        time_prev = time.monotonic()
        if NUKE:
            try:
                shutil.copy(NUKE_FP, RPI_INIT_FP)
                print("Nuking...")
            except Exception as e:
                print(f"Error nuking device: {e}")
                return False
        
        # Wait for RPI-RP2 to remount and copy UF2
        ready_for_copy = False
        print("Waiting for RPI-RP2 to mount...")
        while not ready_for_copy:
            try:
                shutil.copy(uf2_path, RPI_INIT_FP)
                ready_for_copy = True
                print(f"Copied {FROZEN_UF2_NAME} to RPI-RP2")
                time_prev = time.monotonic()
            except:
                print("Retrying in 2s...")
                time.sleep(2)
            
            if time.monotonic() - time_prev > TIMEOUT_THRESHOLD:
                print("Timeout waiting for RPI-RP2")
                return False
        
        time.sleep(10)
        
        # Wait for CIRCUITPY to mount and copy files
        success = False
        print("Waiting for CIRCUITPY to mount...")
        time_prev = time.monotonic()
        while not success:
            try:
                # Copy all contents from files/ folder to CIRCUITPY
                shutil.copytree(files_folder, RPI_CIRCUITPYTHON_PATH, dirs_exist_ok=True)
                success = True
                print("Files copied successfully to CIRCUITPY")
                time_prev = time.monotonic()
            except Exception as e:
                print(f"Retrying in 2s... Error: {e}")
                time.sleep(2)
            
            if time.monotonic() - time_prev > TIMEOUT_THRESHOLD * 2:
                print("Timeout waiting for CIRCUITPY")
                return False
        
        print(f"\n{'='*50}")
        print("Release test completed successfully!")
        print(f"{'='*50}")
        return True
        
    finally:
        # Always clean up temp directory
        print(f"\nCleaning up temp directory: {temp_dir}")
        try:
            shutil.rmtree(temp_dir)
            print("Temp directory removed.")
        except Exception as e:
            print(f"Warning: Could not remove temp directory: {e}")


def flash_customer_device(version):
    """
    Flash a customer device using pre-built release files.
    Uses the UF2 and files from releases/{version}/ folder.
    """
    release_folder = os.path.join(RELEASES_FOLDER, version)
    uf2_path = os.path.join(release_folder, FROZEN_UF2_NAME)
    files_folder = os.path.join(release_folder, "files")
    
    # Validate release folder exists
    if not os.path.exists(release_folder):
        print(f"ERROR: Release folder not found: {release_folder}")
        return False
    
    if not os.path.exists(uf2_path):
        print(f"ERROR: UF2 not found: {uf2_path}")
        return False
    
    if not os.path.exists(files_folder):
        print(f"ERROR: Files folder not found: {files_folder}")
        return False
    
    print(f"\nFlashing customer device with release {version}")
    print(f"  UF2: {uf2_path}")
    print(f"  Files: {files_folder}")
    
    time_prev = time.monotonic()
    
    # Nuke if needed
    if NUKE:
        try:
            shutil.copy(NUKE_FP, RPI_INIT_FP)
            print("Nuking...")
        except Exception as e:
            print(f"No folder named RPI-RP2 found: {e}")
            return False
    
    # Copy UF2 to device
    ready_for_copy = False
    print("Waiting for RPI-RP2 to mount...")
    while not ready_for_copy:
        try:
            shutil.copy(uf2_path, RPI_INIT_FP)
            ready_for_copy = True
            print(f"Copied {FROZEN_UF2_NAME} to RPI-RP2")
            time_prev = time.monotonic()
        except:
            print("Retrying in 2s...")
            time.sleep(2)
        
        if time.monotonic() - time_prev > TIMEOUT_THRESHOLD:
            print("Timeout waiting for RPI-RP2")
            return False
    
    time.sleep(10)
    
    # Copy files to CIRCUITPY
    success = False
    print("Waiting for CIRCUITPY to mount...")
    time_prev = time.monotonic()
    while not success:
        try:
            shutil.copytree(files_folder, RPI_CIRCUITPYTHON_PATH, dirs_exist_ok=True)
            success = True
            print("Files copied successfully to CIRCUITPY")
            time_prev = time.monotonic()
        except Exception as e:
            print(f"Retrying in 2s... Error: {e}")
            time.sleep(2)
        
        if time.monotonic() - time_prev > TIMEOUT_THRESHOLD * 2:
            print("Timeout waiting for CIRCUITPY")
            return False
    
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
        print("\n" + "="*50)
        print("DJBB Loopster Initializer")
        print("="*50)
        
        # Prompt for customer device first (default: no)
        customer_device_input = input("\nLoading to customer device? (y/n, default: n): ").strip().lower()
        if customer_device_input == 'y':
            # Show existing releases
            existing = list_existing_releases()
            if existing:
                print(f"\nAvailable versions: {', '.join(existing)}")
            else:
                print("\nNo releases found. Please generate a release first.")
                continue
            
            version = input("Enter version number (e.g., 2.41): ").strip()
            if not version:
                print("No version provided. Returning to main menu.")
                continue
            
            if version not in existing:
                print(f"Version {version} not found in releases folder.")
                continue
            
            print("\nConnect the device and press Enter to start...")
            input()
            
            if flash_customer_device(version):
                print("Customer device flashed successfully. You can connect another device.")
            else:
                print("Flashing failed. Please check the device and try again.")
            continue  # Go back to main menu
        
        # Prompt for release generation (default: no)
        generate_release_input = input("\nGenerate release? (y/n, default: n): ").strip().lower()
        if generate_release_input == 'y':
            # Show existing releases
            existing = list_existing_releases()
            if existing:
                print(f"\nExisting releases: {', '.join(existing)}")
            else:
                print("\nNo existing releases found.")
            
            release_number = input("Enter release number (e.g., 2.41): ").strip()
            if release_number:
                result = generate_release(release_number)
                if result[0]:  # Release generated successfully
                    _, _, zip_path = result
                    
                    # Check if device is connected in bootloader mode
                    if check_device_in_bootloader():
                        print("\nDevice detected in bootloader mode (RPI-RP2)!")
                        print("Automatically testing release on device...")
                        test_release_from_zip(zip_path)
                    else:
                        print("\nNo device detected in bootloader mode. Release generation complete.")
            else:
                print("No release number provided. Skipping release generation.")
            continue  # Go back to main menu
        
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