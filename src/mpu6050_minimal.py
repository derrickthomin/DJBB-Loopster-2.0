# Minimal MPU6050 driver - only acceleration reading
# Saves ~10KB RAM vs full adafruit_mpu6050 library

class MPU6050:
    _ACCEL_OUT = 0x3B  # First of 6 accel registers (ACCEL_XOUT_H)
    _PWR_MGMT_1 = 0x6B
    _ADDR = 0x68  # Default I2C address (use 0x69 if AD0 pin is high)
    
    def __init__(self, i2c, address=0x68):
        self._i2c = i2c
        self._addr = address
        self._buf = bytearray(6)
        self._reg = bytearray(1)
        
        # Wake up the sensor (clear sleep bit in PWR_MGMT_1)
        self._write_reg(self._PWR_MGMT_1, 0x00)
    
    def _write_reg(self, reg, value):
        while not self._i2c.try_lock():
            pass
        try:
            self._i2c.writeto(self._addr, bytes([reg, value]))
        finally:
            self._i2c.unlock()
    
    def _read_reg(self, reg, buf):
        while not self._i2c.try_lock():
            pass
        try:
            self._reg[0] = reg
            self._i2c.writeto_then_readfrom(self._addr, self._reg, buf)
        finally:
            self._i2c.unlock()
    
    @property
    def acceleration(self):
        # Read 6 bytes: ACCEL_XOUT_H, ACCEL_XOUT_L, ACCEL_YOUT_H, ACCEL_YOUT_L, ACCEL_ZOUT_H, ACCEL_ZOUT_L
        self._read_reg(self._ACCEL_OUT, self._buf)
        
        # Convert to signed 16-bit values
        raw_x = (self._buf[0] << 8) | self._buf[1]
        raw_y = (self._buf[2] << 8) | self._buf[3]
        raw_z = (self._buf[4] << 8) | self._buf[5]
        
        # Convert from unsigned to signed
        if raw_x > 32767:
            raw_x -= 65536
        if raw_y > 32767:
            raw_y -= 65536
        if raw_z > 32767:
            raw_z -= 65536
        
        # Default scale is ±2g with 16384 LSB/g, convert to m/s²
        scale = 9.80665 / 16384.0
        return (raw_x * scale, raw_y * scale, raw_z * scale)
