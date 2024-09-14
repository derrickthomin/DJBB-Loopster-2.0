import gc
from debug import print_debug

def next_or_previous_index(current_index, list_length, up_or_down, loop_around=True):
    """
    Returns the next or previous index based on the current index and direction.

    Args:
        current_index (int): The current index.
        list_length (int): The length of the list.
        up_or_down (bool): True for next index, False for previous index.
        loop_around (bool, optional): Whether to loop around to the other end of the list when reaching the end or beginning. Defaults to True.

    Returns:
        int: The next or previous index.
    """
    if not isinstance(current_index, int) or not isinstance(list_length, int) or not isinstance(up_or_down, bool):
        raise TypeError("Invalid parameter type. current_index and list_length must be integers, up_or_down must be a boolean.")
    
    direction = 1 if up_or_down else -1
    if loop_around:
        new_index = (current_index + direction) % list_length
        return new_index
    
    new_index = current_index + direction
    if new_index < 0 or new_index > list_length:
        return current_index
    
    return new_index

def free_memory():
    """
    Frees memory by running the garbage collector.
    """
    gc.collect()
    print_debug(f"Free memory: {gc.mem_free()}")