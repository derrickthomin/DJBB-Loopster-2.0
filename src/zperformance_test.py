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

# def main():
#     size = 2000  # Size of the list/tuple
#     num_updates = 2000  # Number of updates

#     print("Testing list operations with strings...")
#     list_creation_time, list_update_time = create_and_update_list_with_strings(size, num_updates)
#     print(f"List creation time (strings): {list_creation_time:.5f} seconds")
#     print(f"List update time (strings): {list_update_time:.5f} seconds")

#     print("Testing tuple operations with strings...")
#     tuple_creation_time, tuple_update_time = create_and_update_tuple_with_strings(size, num_updates)
#     print(f"Tuple creation time (strings): {tuple_creation_time:.5f} seconds")
#     print(f"Tuple update time (strings): {tuple_update_time:.5f} seconds")

#     print("Testing list operations with floats...")
#     list_creation_time, list_update_time = create_and_update_list_with_floats(size, num_updates)
#     print(f"List creation time (floats): {list_creation_time:.5f} seconds")
#     print(f"List update time (floats): {list_update_time:.5f} seconds")

#     print("Testing tuple operations with floats...")
#     tuple_creation_time, tuple_update_time = create_and_update_tuple_with_floats(size, num_updates)
#     print(f"Tuple creation time (floats): {tuple_creation_time:.5f} seconds")
#     print(f"Tuple update time (floats): {tuple_update_time:.5f} seconds")

# import time
# import supervisor

# # Number of iterations to measure efficiency
# ITERATIONS = 1000000

# def test_time_monotonic():
#     start = time.monotonic()
#     for _ in range(ITERATIONS):
#         _ = time.monotonic()
#     end = time.monotonic()
#     return end - start

# def test_time_monotonic_ns():
#     try:
#         start = time.monotonic_ns()
#         for _ in range(ITERATIONS):
#             _ = time.monotonic_ns()
#         end = time.monotonic_ns()
#         return (end - start) / 1e9  # Convert nanoseconds to seconds
#     except AttributeError:
#         print("time.monotonic_ns() is not available on this board.")
#         return None

# def test_supervisor_ticks_ms():
#     start = supervisor.ticks_ms()
#     for _ in range(ITERATIONS):
#         _ = supervisor.ticks_ms()
#     end = supervisor.ticks_ms()
#     # Calculate elapsed time considering the wrap-around
#     elapsed = (end - start) if end >= start else (end + (1 << 32) - start)
#     return elapsed / 1000.0  # Convert milliseconds to seconds

# def main():
#     print(f"Testing with {ITERATIONS} iterations...")

#     # Test time.monotonic()
#     monotonic_duration = test_time_monotonic()
#     print(f"time.monotonic() duration: {monotonic_duration:.6f} seconds")

#     # Test time.monotonic_ns()
#     monotonic_ns_duration = test_time_monotonic_ns()
#     if monotonic_ns_duration is not None:
#         print(f"time.monotonic_ns() duration: {monotonic_ns_duration:.6f} seconds")

#     # Test supervisor.ticks_ms()
#     ticks_ms_duration = test_supervisor_ticks_ms()
#     print(f"supervisor.ticks_ms() duration: {ticks_ms_duration:.6f} seconds")

# if __name__ == "__main__":
#     main()

import time
import board
import neopixel
import neopixel_spi
import busio


# Color to fill the pixels with
test_color = (255, 0, 0)  # Red

def measure_update_time(pixels, color):
    start_time = time.monotonic()
    pixels.fill(color)
    pixels.show()
    end_time = time.monotonic()
    total_time = end_time - start_time

    pixels.fill((0, 0, 0))
    pixels.show()

    return total_time
all_pixels = neopixel.NeoPixel(board.GP15, 18, brightness=100)

# 0.002991 seconds
# Measure time for neopixel library
time_neopixel = measure_update_time(all_pixels, test_color)
print(f"neopixel library update time: {time_neopixel:.6f} seconds")


# spi = busio.SPI(board.GP14, board.GP15)
# pixels_neopixel_spi = neopixel_spi.NeoPixel_SPI(spi, 18, brightness=100, auto_write=False)

# # Measure time for neopixel_spi library
# time_neopixel_spi = measure_update_time(pixels_neopixel_spi, test_color)
# print(f"neopixel_spi library update time: {time_neopixel_spi:.6f} seconds")