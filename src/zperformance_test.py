import time

def create_and_update_list_with_strings(size, num_updates):
    # Create a large list of strings
    start_time = time.time()
    lst = [""] * size
    creation_time = time.time() - start_time

    # Update the list with strings
    start_time = time.time()
    for i in range(num_updates):
        lst[i % size] = f"string_{i}"
    update_time = time.time() - start_time

    return creation_time, update_time

def create_and_update_tuple_with_strings(size, num_updates):
    # Create a large tuple of strings
    start_time = time.time()
    tpl = ("",) * size
    creation_time = time.time() - start_time

    # Update the tuple with strings
    start_time = time.time()
    for i in range(num_updates):
        tpl = tpl[:i % size] + (f"string_{i}",) + tpl[i % size + 1:]
    update_time = time.time() - start_time

    return creation_time, update_time

def create_and_update_list_with_floats(size, num_updates):
    # Create a large list of floats
    start_time = time.time()
    lst = [0.0] * size
    creation_time = time.time() - start_time

    # Update the list with floats
    start_time = time.time()
    for i in range(num_updates):
        lst[i % size] = float(i)
    update_time = time.time() - start_time

    return creation_time, update_time

def create_and_update_tuple_with_floats(size, num_updates):
    # Create a large tuple of floats
    start_time = time.time()
    tpl = (0.0,) * size
    creation_time = time.time() - start_time

    # Update the tuple with floats
    start_time = time.time()
    for i in range(num_updates):
        tpl = tpl[:i % size] + (float(i),) + tpl[i % size + 1:]
    update_time = time.time() - start_time

    return creation_time, update_time

def main():
    size = 2000  # Size of the list/tuple
    num_updates = 2000  # Number of updates

    print("Testing list operations with strings...")
    list_creation_time, list_update_time = create_and_update_list_with_strings(size, num_updates)
    print(f"List creation time (strings): {list_creation_time:.5f} seconds")
    print(f"List update time (strings): {list_update_time:.5f} seconds")

    print("Testing tuple operations with strings...")
    tuple_creation_time, tuple_update_time = create_and_update_tuple_with_strings(size, num_updates)
    print(f"Tuple creation time (strings): {tuple_creation_time:.5f} seconds")
    print(f"Tuple update time (strings): {tuple_update_time:.5f} seconds")

    print("Testing list operations with floats...")
    list_creation_time, list_update_time = create_and_update_list_with_floats(size, num_updates)
    print(f"List creation time (floats): {list_creation_time:.5f} seconds")
    print(f"List update time (floats): {list_update_time:.5f} seconds")

    print("Testing tuple operations with floats...")
    tuple_creation_time, tuple_update_time = create_and_update_tuple_with_floats(size, num_updates)
    print(f"Tuple creation time (floats): {tuple_creation_time:.5f} seconds")
    print(f"Tuple update time (floats): {tuple_update_time:.5f} seconds")

if __name__ == "__main__":
    main()
