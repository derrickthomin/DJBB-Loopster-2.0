import gc

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
    if new_index < 0 or new_index > list_length-1:
        return current_index
    
    return new_index

def free_memory():
    """
    Frees memory by running the garbage collector.
    """
    gc.collect()

def show_memory(label=""):
    """
    Shows the amount of free memory.
    """
    if label:
        print(label)
    print(f"Free memory: {gc.mem_free()}")

def test_memory_usage():
    """
    Tests memory usage by populating a list with 20 integer elements and printing the memory usage.
    Also does a similar test for a dictionary and other data stuctures.
    """
    free_memory()
    print("Free memory before test:")
    show_memory()
    test_list = [i for i in range(20)]
    print(f"List: {test_list}")
    print(f"Memory usage of list: {gc.mem_free()} bytes")

    test_dict = {i: i for i in range(20)}
    print(f"Dictionary: {test_dict}")
    print(f"Memory usage of dictionary: {gc.mem_free()} bytes")

    test_set = {i for i in range(20)}
    print(f"Set: {test_set}")
    print(f"Memory usage of set: {gc.mem_free()} bytes")

    # test with array.array
    import array
    test_array = array.array('i', [i for i in range(20)])
    print(f"Memory usage of array: {gc.mem_free()} bytes")
    # test with bytearray
    test_bytearray = bytearray([i for i in range(20)])
    print(f"Memory usage of bytearray: {gc.mem_free()} bytes")

    # test with array of 10 array.arrays with 20 elements vs 20 separate arrays
    test_array_of_arrays = [array.array('i', [i for i in range(20)]) for _ in range(10)]
    print(f"Memory usage of array of arrays: {gc.mem_free()} bytes")
    test_separate_arrays = [[i for i in range(20)] for _ in range(10)]
    print(f"Memory usage of separate arrays: {gc.mem_free()} bytes")

if __name__=="__main__":
    test_memory_usage()
    free_memory()
    show_memory("Memory usage after freeing memory:")