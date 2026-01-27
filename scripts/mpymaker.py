#!/usr/bin/env python3
"""
MPY Maker - A utility script to automate the conversion of .py files to .mpy files
for CircuitPython projects, and optionally copy them to a connected CircuitPython device.

Usage:
    python mpymaker.py [files]
    
If no files are specified, the script will prompt the user for input.
The .mpy files will be created in the mpy_library directory.

After conversion, the script will offer to copy the converted .mpy files to the /lib folder
on a connected CircuitPython device (looks for LOOPSTER2 drive).
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil

# =============================================================================
# CONFIGURATION
# =============================================================================

# Files to exclude from conversion (these will never be converted to .mpy)
# These files need to remain as .py for various reasons:
# - code.py: Main entry point, must be .py for CircuitPython
# - boot.py: Boot script, must be .py for CircuitPython
# - useraddons.py: User-customizable, keep as .py for easy editing
EXCLUDE_FILES = [
    'code.py',
    'boot.py',
    'useraddons.py',
    'mpymaker.py',
]

# =============================================================================
# FUNCTIONS
# =============================================================================

def find_mpy_cross():
    """Find the mpy-cross executable in the script directory."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mpy_cross = os.path.join(script_dir, "mpy-cross")
    
    if not os.path.exists(mpy_cross):
        print(f"Error: mpy-cross not found at {mpy_cross}")
        print("Make sure to download the appropriate mpy-cross for your system")
        print("and place it in the same directory as this script.")
        sys.exit(1)
    
    # Check if the file is executable
    if not os.access(mpy_cross, os.X_OK):
        print(f"Making mpy-cross executable...")
        try:
            os.chmod(mpy_cross, 0o755)  # Make executable
        except Exception as e:
            print(f"Error making mpy-cross executable: {e}")
            print("You may need to run: chmod +x mpy-cross")
            sys.exit(1)
    
    return mpy_cross

def convert_to_mpy(mpy_cross, file_path, output_dir):
    """Convert a .py file to .mpy using mpy-cross and save it to the output directory."""
    if not file_path.endswith('.py'):
        print(f"Skipping {file_path} - Not a Python file")
        return False
    
    base_filename = os.path.basename(file_path)
    
    if base_filename in EXCLUDE_FILES:
        print(f"Skipping {file_path} - In exclusion list")
        return False
    
    try:
        output_file = os.path.join(output_dir, base_filename.replace('.py', '.mpy'))
        
        print(f"Converting {file_path} to {output_file}...")
        
        # Run mpy-cross on the file
        result = subprocess.run(
            [mpy_cross, file_path, "-o", output_file], 
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Error converting {file_path}:")
            print(result.stderr)
            return False
        
        # Verify the .mpy file was created
        if os.path.exists(output_file):
            print(f"Successfully created {output_file}")
            return True
        else:
            print(f"Failed to create {output_file}")
            return False
            
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def find_all_py_files(src_dir):
    """Find all .py files directly in the src directory (not in subdirectories like lib)."""
    files_to_convert = []
    
    print(f"Looking for Python files in {src_dir}")
    
    try:
        for item in os.listdir(src_dir):
            item_path = os.path.join(src_dir, item)
            # Only process files directly in src (not subdirectories)
            if os.path.isfile(item_path) and item.endswith('.py') and item not in EXCLUDE_FILES:
                files_to_convert.append(item_path)
    except Exception as e:
        print(f"Error reading directory {src_dir}: {e}")
    
    return sorted(files_to_convert)

def get_valid_mpy_filenames(src_dir):
    """Get the set of valid .mpy filenames based on .py files in src directory."""
    valid_mpy_names = set()
    
    try:
        for item in os.listdir(src_dir):
            item_path = os.path.join(src_dir, item)
            if os.path.isfile(item_path) and item.endswith('.py') and item not in EXCLUDE_FILES:
                mpy_name = item.replace('.py', '.mpy')
                valid_mpy_names.add(mpy_name)
    except Exception as e:
        print(f"Error reading directory {src_dir}: {e}")
    
    return valid_mpy_names

def cleanup_orphaned_mpy_files(output_dir, src_dir):
    """Remove .mpy files that no longer have corresponding .py files in src."""
    valid_mpy_names = get_valid_mpy_filenames(src_dir)
    removed_count = 0
    
    try:
        for item in os.listdir(output_dir):
            if item.endswith('.mpy'):
                if item not in valid_mpy_names:
                    item_path = os.path.join(output_dir, item)
                    print(f"Removing orphaned .mpy file: {item}")
                    os.remove(item_path)
                    removed_count += 1
    except Exception as e:
        print(f"Error during cleanup: {e}")
    
    if removed_count > 0:
        print(f"Cleaned up {removed_count} orphaned .mpy file(s)")
    
    return removed_count

def parse_file_selection(choice, all_py_files):
    """
    Parse user input to select files. Accepts:
    - Numbers: '1,2,3' or '1, 2, 3'
    - File names: 'arp,boot' or 'arp.py, boot.py'
    - Mixed: '1, arp, 3, boot.py'
    
    Returns a list of matching file paths.
    """
    # Build a lookup dict: basename (without .py) -> full path
    name_to_path = {}
    for f in all_py_files:
        basename = os.path.basename(f)
        name_without_ext = basename.replace('.py', '')
        name_to_path[name_without_ext.lower()] = f
        name_to_path[basename.lower()] = f  # Also allow with .py extension
    
    selected_files = []
    items = [x.strip() for x in choice.split(',') if x.strip()]
    
    for item in items:
        item_lower = item.lower()
        
        # Try as a number first
        try:
            idx = int(item) - 1
            if 0 <= idx < len(all_py_files):
                selected_files.append(all_py_files[idx])
            else:
                print(f"Warning: Index {item} out of range, skipping.")
            continue
        except ValueError:
            pass  # Not a number, try as filename
        
        # Try as a filename (with or without .py)
        if item_lower in name_to_path:
            selected_files.append(name_to_path[item_lower])
        else:
            print(f"Warning: '{item}' not found, skipping.")
    
    return selected_files

def prompt_for_files(all_py_files):
    """Prompt user to select which files to convert."""
    print("\nAvailable .py files for conversion:")
    for i, file in enumerate(all_py_files):
        print(f"{i+1}. {os.path.basename(file)}")
    
    print("\nOptions:")
    print("- Enter comma-separated numbers (e.g., '1,3,5')")
    print("- Enter comma-separated file names (e.g., 'arp,boot' or 'arp.py,boot.py')")
    print("- Mix numbers and names (e.g., '1,boot,3')")
    print("- Enter 'all' to convert all files")
    print("- Enter 'q' to quit")
    
    choice = input("\nYour selection: ").strip().lower()
    
    if choice == 'q':
        print("Exiting...")
        sys.exit(0)
    elif choice == 'all':
        return all_py_files
    else:
        selected_files = parse_file_selection(choice, all_py_files)
        
        if not selected_files:
            print("No valid files selected. Converting all files.")
            return all_py_files
            
        return selected_files

def find_loopster2_drive():
    """Find the LOOPSTER CircuitPython device drive on macOS."""
    device_path = '/Volumes/LOOPSTER'
    
    if os.path.exists(device_path) and os.path.isdir(device_path):
        return device_path
    
    return None

def prompt_load_to_device():
    """Simple yes/no prompt to load files to device."""
    while True:
        choice = input("\nLoad converted files to device? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            return True
        elif choice in ['n', 'no', '']:
            return False
        else:
            print("Please enter 'y' or 'n'")

def copy_mpy_files_to_device(mpy_files, source_dir, device_path):
    """Copy selected .mpy files to the CircuitPython device lib folder."""
    if not mpy_files:
        return 0
    
    # Ensure the lib directory exists on the device
    device_lib_path = os.path.join(device_path, 'lib')
    
    try:
        os.makedirs(device_lib_path, exist_ok=True)
    except Exception as e:
        print(f"Error creating lib directory on device: {e}")
        return 0
    
    success_count = 0
    
    for mpy_file in mpy_files:
        source_file = os.path.join(source_dir, mpy_file)
        dest_file = os.path.join(device_lib_path, mpy_file)
        
        try:
            print(f"Copying {mpy_file} to device...")
            shutil.copy2(source_file, dest_file)
            print(f"Successfully copied {mpy_file}")
            success_count += 1
        except Exception as e:
            print(f"Error copying {mpy_file}: {e}")
    
    return success_count

def main():
    # Find the mpy-cross executable
    mpy_cross = find_mpy_cross()
    print(f"Using mpy-cross: {mpy_cross}")
    
    # Set paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "mpy_library")
    src_dir = "/Users/derrickthomin/📜Documents Local/📝Project Writeups/DJBB Midi Loopster SMD RGB/Code - Production/src"
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory for .mpy files: {output_dir}")
    
    # Always clean up orphaned .mpy files first
    print(f"\n{'='*50}")
    print("CLEANUP CHECK")
    print(f"{'='*50}")
    cleanup_orphaned_mpy_files(output_dir, src_dir)
    
    # Get list of files to convert
    print(f"\n{'='*50}")
    print("FILE CONVERSION")
    print(f"{'='*50}")
    
    if len(sys.argv) > 1:
        # Convert specific files provided as command-line arguments
        files_to_convert = sys.argv[1:]
    else:
        # Find all available Python files
        all_py_files = find_all_py_files(src_dir)
        
        if not all_py_files:
            print("No Python files found in the src directory.")
            sys.exit(1)
        
        # Prompt user for file selection
        files_to_convert = prompt_for_files(all_py_files)
    
    # Convert files and track which ones were successfully converted
    successfully_converted = []
    for file_path in files_to_convert:
        if convert_to_mpy(mpy_cross, file_path, output_dir):
            # Get the .mpy filename for the successfully converted file
            mpy_filename = os.path.basename(file_path).replace('.py', '.mpy')
            successfully_converted.append(mpy_filename)
    
    # Print summary
    print(f"\nConversion complete: {len(successfully_converted)}/{len(files_to_convert)} files converted successfully")
    print(f"All .mpy files are stored in: {output_dir}")
    
    # Copy to device if files were successfully converted
    if successfully_converted:
        print(f"\n{'='*50}")
        print("DEVICE LOADING")
        print(f"{'='*50}")
        
        # Find the LOOPSTER2 device
        device_path = find_loopster2_drive()
        
        if device_path:
            print(f"Found LOOPSTER device at: {device_path}")
            
            # Simple yes/no prompt
            if prompt_load_to_device():
                # Copy the successfully converted files
                copied_count = copy_mpy_files_to_device(successfully_converted, output_dir, device_path)
                print(f"\nCopy operation complete: {copied_count}/{len(successfully_converted)} files copied successfully")
                print(f"Files copied to: {os.path.join(device_path, 'lib')}")
            else:
                print("Skipping device loading.")
        else:
            print("LOOPSTER device not found.")
            print("Make sure your CircuitPython device is connected and mounted.")
            print("The device should appear as 'LOOPSTER' in your file system.")
    else:
        print("No .mpy files were created, skipping device loading.")

if __name__ == "__main__":
    main()
