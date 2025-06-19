import os

# This script is used to put all .py files in the /src folder into a single file



def combine_files(src_folder, output_file):
    with open(output_file, 'w') as outfile:
        for filename in os.listdir(src_folder):
            if filename.endswith(('.py', '.txt', '.json')):
                outfile.write(f"#--- BEGIN {filename} ---#\n")
                with open(os.path.join(src_folder, filename), 'r') as infile:
                    outfile.write(infile.read())
                outfile.write(f"\n#--- END {filename} ---#\n\n")

src_folder = os.path.join(os.path.dirname(__file__), 'src')
output_file = os.path.join(os.path.dirname(__file__), 'srccombined.txt')
combine_files(src_folder, output_file)
