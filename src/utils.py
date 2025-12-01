import gc

def next_or_previous_index(current_index, list_length, up_or_down, loop_around=True):
    """Returns next/previous index, optionally wrapping around."""
    if not isinstance(current_index, int) or not isinstance(list_length, int) or not isinstance(up_or_down, bool):
        raise TypeError("Invalid parameter type. current_index and list_length must be integers, up_or_down must be a boolean.")
    
    direction = 1 if up_or_down else -1
    if loop_around:
        new_index = (current_index + direction) % list_length
        return new_index
    
    new_index = current_index + direction
    if new_index < 0 or new_index > list_length-1:
        return current_index
    
    return new_index

def free_memory():
    gc.collect()

def show_memory(label=""):
    if label:
        print(label)
    print(f"Free memory: {gc.mem_free()}")
