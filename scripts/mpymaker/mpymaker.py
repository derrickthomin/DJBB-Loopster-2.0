#!/usr/bin/env python3
"""
MPY Maker - A utility script to automate the conversion of .py files to .mpy files
for CircuitPython projects.

Usage:
    python mpymaker.py [files]
    
If no files are specified, the script will prompt the user for input.
The .mpy files will be created in the mpymaker directory, preserving the original .py files.
"""

import os
import sys
import subprocess
import glob
from pathlib import Path
import shutil

def find_mpy_cross():
    """Find the mpy-cross executable in the current directory."""
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
    
    if os.path.basename(file_path) == 'mpymaker.py':
        print(f"Skipping {file_path} - This is the mpymaker script itself")
        return False
    
    try:
        base_filename = os.path.basename(file_path)
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
    """Find all .py files in the src directory (excluding mpymaker directory and lib subdirectories)."""
    files_to_convert = []
    
    print(f"Looking for Python files in {src_dir}")
    
    for root, dirs, files in os.walk(src_dir):
        # Skip the mpymaker directory and lib directory subdirectories
        if os.path.basename(root) == "mpymaker" or "lib" in root.split(os.sep):
            continue
            
        for file in files:
            if file.endswith('.py') and file != 'mpymaker.py':
                files_to_convert.append(os.path.join(root, file))
    
    return files_to_convert

def prompt_for_files(all_py_files):
    """Prompt user to select which files to convert."""
    print("\nAvailable .py files for conversion:")
    for i, file in enumerate(all_py_files):
        print(f"{i+1}. {os.path.basename(file)}")
    
    print("\nOptions:")
    print("- Enter comma-separated numbers to select specific files (e.g., '1,3,5')")
    print("- Enter 'all' to convert all files")
    print("- Enter 'q' to quit")
    
    choice = input("\nYour selection: ").strip().lower()
    
    if choice == 'q':
        print("Exiting...")
        sys.exit(0)
    elif choice == 'all':
        return all_py_files
    else:
        try:
            selected_indices = [int(x.strip()) - 1 for x in choice.split(',') if x.strip()]
            selected_files = [all_py_files[i] for i in selected_indices if 0 <= i < len(all_py_files)]
            
            if not selected_files:
                print("No valid files selected. Converting all files.")
                return all_py_files
                
            return selected_files
        except (ValueError, IndexError):
            print("Invalid input. Converting all files.")
            return all_py_files

def main():
    # Find the mpy-cross executable
    mpy_cross = find_mpy_cross()
    print(f"Using mpy-cross: {mpy_cross}")
    
    # Set output directory to mpymaker folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = script_dir
    print(f"Output directory for .mpy files: {output_dir}")
    
    # Get list of files to convert
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    all_py_files = []
    
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
    
    # Convert files
    success_count = 0
    for file_path in files_to_convert:
        if convert_to_mpy(mpy_cross, file_path, output_dir):
            success_count += 1
    
    # Print summary
    print(f"\nConversion complete: {success_count}/{len(files_to_convert)} files converted successfully")
    print(f"All .mpy files have been created in: {output_dir}")

if __name__ == "__main__":
    main()