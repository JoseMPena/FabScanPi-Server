__author__ = "Mario Lukas"
__copyright__ = "Copyright 2017"
__license__ = "GPL v2"
__maintainer__ = "Mario Lukas"
__email__ = "info@mariolukas.de"

import os
import glob
import serial
import time
import logging
import threading
from fabscan.lib.util.FSUtil import FSSystem
from fabscan.lib.util.FSInject import inject
from fabscan.FSConfig import ConfigInterface
from fabscan.scanner.interfaces.FSHardwareConnector import FSHardwareConnectorInterface
from fabscan.scanner.laserscanner.driver.FSSerialProtocol import read_response_until_ready

@inject(
    config=ConfigInterface
)
class FSSerialCom(FSHardwareConnectorInterface):
    def __init__(self, config):

        self.config = config
        self._logger = logging.getLogger(__name__)

        if hasattr(self.config.file.connector, 'port'):
            self._port = self.config.file.connector.port
            self._logger.debug("Port in Config found using: {0}".format(self._port))
        else:
            self._port = "/dev/ttyAMA0"

        if hasattr(self.config.file.connector, 'flash_baudrate'):
            self.flash_baudrate = self.config.file.connector.flash_baudrate
        else:
            self.flash_baudrate = 57600

        self.buf = bytearray()
        self._command_lock = threading.RLock()

        self._baudrate = self.config.file.connector.baudrate
        self._serial = None
        self._connected = False
        self._firmware_version = None
        self._openSerial()
        self._logger.debug("Connection baudrate is: {0}".format(self._baudrate))
        self._logger.debug("Firmware flashing baudrate is: {0}".format(self.flash_baudrate))

        self._stop = False

    def avr_device_is_available(self):
       # status = FSSystem.run_command("sudo avrdude-autoreset -p m328p -b {0} -carduino -P{1}".format(self.flash_baudrate, self._port))
       # return status == 0
       # Forced to True to bypass avrdude check for RAMPS/Mega
       self._logger.info("Bypassing AVR device check for RAMPS 1.4")
       return True

    def avr_flash(self, fname):
        FSSystem.run_command("wc -l {0}".format(fname))
        status = FSSystem.run_command("sudo avrdude-autoreset -D -V -U flash:w:{0}:i -b {1} -carduino -pm328p -P{2}".format(fname, self.flash_baudrate, self._port))
        if status != 0:
            self._logger.error("Failed to flash firmware")
        return status == 0

    def _connect(self):
        self._logger.debug("Trying to connect Arduino on port: {0}".format(self._port))
        # open serial port
        try:
            self._logger.info("Trying on baudrate: {0}".format(self._baudrate))
            self._serial = serial.Serial(str(self._port), int(self._baudrate), timeout=3)
            time.sleep(1)
        except Exception:
            self._logger.error("Could not open serial port")
            self._serial = None

    def _close(self):
        if self._serial:
            self._serial.close()

    def _openSerial(self):
        # We skip the firmware hex file lookups to avoid errors if no hex exists
        self._logger.debug("Bypassing firmware version lookups for RAMPS 1.4")

        try:
            # 1. Try to connect
            self._connect()

            # 2. If port is open, bypass the logic and force connection states
            if self._serial and self._serial_is_open():
                current_version = self.checkVersion()
                if current_version != "None":
                    self._firmware_version = current_version
                    self._connected = True
                    self._logger.info("Connected to RAMPS on port: {0}, firmware: {1}".format(self._port, current_version))
                else:
                    self._logger.error("RAMPS serial port opened on {0}, but firmware did not answer M200.".format(self._port))
                    self._connected = False
            else:
                self._logger.error("Physical port {0} could not be opened.".format(self._port))
                self._connected = False

        except Exception as e:
            self._logger.error("Fatal connection error: {0}".format(e))
            self._connected = False

    def _serial_is_open(self):
        if hasattr(self._serial, "isOpen"):
            return self._serial.isOpen()
        return self._serial.is_open

    def checkVersion(self):
        if not self._serial:
            return "None"
        try:
            with self._command_lock:
                self._serial.write("\r\n\r\n".encode())
                time.sleep(2) # Wait for FabScan to initialize
                self._serial.flushInput() # Flush startup text in serial input
            value = self.send_and_receive("M200")
            return value if value else "None"
        except Exception as e:
            self._logger.error("Check Version Error: {0}".format(e))
            return "None"

    def send_and_receive(self, message):

        if not self._serial:
            return ""

        with self._command_lock:
            try:
                self.send(message)
                self._serial.flush()
                return read_response_until_ready(self.readline)
            except Exception as e:
                self._logger.debug("Send/Receive Error: {0}".format(e))
                return ""

    def readline(self):
        if not self._serial:
            return b""
        read_timeout = False
        try:
            i = self.buf.find(b"\n")
            if i >= 0:
                r = self.buf[:i+1]
                self.buf = self.buf[i+1:]
                return r
            while not read_timeout:
                i = max(1, min(2048, self._serial.in_waiting))
                data = self._serial.read(i)

                if not data:
                    read_timeout = True
                    self._serial.flushInput()
                    self._serial.flushOutput()
                    self._logger.debug("Serial read timeout occured, skipping current and waiting for next command.")

                i = data.find(b"\n")
                if i >= 0:
                    r = self.buf + data[:i+1]
                    self.buf[0:] = data[i+1:]
                    self._serial.flush()
                    del data
                    return r
                else:
                    self.buf.extend(data)
            # Inner loop exited due to timeout without a full line (PySerial returns b'').
            return b""
        except Exception as err:
            self._logger.error("Serial Error occured: {0}".format(err))
            self._connected = False
            return b""


    def flush(self):
       if not self._serial:
           return
       self._serial.flushInput()
       self._serial.flushOutput()

    def send(self, message):
        if not self._serial:
            return
        try:
            message = message + "\n"
            self._serial.write(message.encode())
        except Exception as e:
            self._logger.error("Error while sending: {0}".format(e))

    def is_connected(self):
        return self._connected

    def get_firmware_version(self):
        return self._firmware_version

    def move_turntable(self, steps, speed, blocking=True):

        gcode = "01"

        if bool(blocking) is True:
            gcode = "02"

        command = "G{0} T{1} F{2}".format(gcode, steps, speed)
        #self._logger.debug(command)
        self.send_and_receive(command)

    def laser_on(self, laser):
        if laser == 0:
            command = "M21"
        else:
            command = "M19"
        #self._logger.debug("Laser {0} Switched on".format(laser))
        self.send_and_receive(command)

    def laser_off(self, laser):
        if laser == 0:
            command = "M22"
        else:
            command = "M20"
        #self._logger.debug("Laser {0} Switched off".format(laser))
        self.send_and_receive(command)

    def light_on(self, red, green, blue):
        command = "M05 R{0} G{1} B{2}".format(red, green, blue)
        self.send_and_receive(command)

    def light_off(self):
        command = "M05 R0 G0 B0"
        self.send_and_receive(command)