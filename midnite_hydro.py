#!/usr/bin/env python

# Name: 		midnite_hydro.py
# Purpose:	Present BOTH a Hydro Generator and a Battery Monitor to VenusOS
#           using a SINGLE safe Modbus connection to prevent MidNite network lockups.
# Date:		06-05-2026
# Version:	3.0 (Unified Dual-DBus Architecture)
# Author:	Jan Bakuwel (Original) / Unified for Hydro & Grafana Telemetry
# License:	GNU General Public License v3.0

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import argparse
import logging
import sys
import os
import time
from pymodbus.client.sync import ModbusTcpClient as ModbusClient

# VenusOS packages
sys.path.insert (1, os.path.join (os.path.dirname( __file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService
from logger import setup_logging

import config

def twos_complement (uValue, iBits):
	if (uValue & (1 << (iBits - 1))) != 0:		
		uValue = uValue - (1 << iBits)			
	return uValue

class readMidnite ():

	def __init__ (self, sIP, iFrequency):
		self.sIP				= sIP
		self.iFrequency   = iFrequency
		self.classic		= ModbusClient (self.sIP, port=502)
		self.terminated	= False

		logger.info ('Initialising Unified Midnite thread: IP=%s, Freq=%d' % (self.sIP, self.iFrequency))
		
		# =================================================================================
		# DEVICE 1: THE HYDRO TURBINE (Solar Charger Service)
		# =================================================================================
		self.charger = VeDbusService (servicename='com.victronenergy.solarcharger.midnite', register=False)
		self.charger.add_path('/DeviceInstance',			0)
		self.charger.add_path('/ProductName',				'Midnite Classic Hydro Turbine')
		self.charger.add_path('/Mgmt/ProcessName',			'midnite_hydro.py')
		self.charger.add_path('/Mgmt/ProcessVersion',		config.VERSION)
		self.charger.add_path('/Mgmt/Connection',			'dbus')
		self.charger.add_path('/FirmwareVersion',			config.VERSION)
		self.charger.add_path('/HardwareVersion',			config.VERSION)
		self.charger.add_path('/State',						None, writeable=True)
		
		# Standard Turbine Paths
		self.charger.add_path('/Pv/V',						None, writeable=True, gettextcallback=lambda a, x: "{:.0f}V".format(x))
		self.charger.add_path('/Pv/I',						None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		self.charger.add_path('/Pv/Power',					None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
		self.charger.add_path('/Yield/Power',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
		self.charger.add_path('/Dc/0/Voltage',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}V".format(x))
		self.charger.add_path('/Dc/0/Current',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		self.charger.add_path('/Yield/User',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}kWh".format(x))
		
		# Extended Grafana Paths (Attached to Charger)
		self.charger.add_path('/Yield/Lifetime',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}kWh".format(x))
		self.charger.add_path('/Yield/AmpHours',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
		self.charger.add_path('/Temps/Battery',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.charger.add_path('/Temps/FET',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.charger.add_path('/Temps/PCB',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.charger.add_path('/Soc',						None, writeable=True, gettextcallback=lambda a, x: "{:.0f}%".format(x))
		self.charger.add_path('/Dc/0/ShuntCurrent',			None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		self.charger.add_path('/WasteNot/Pwm',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}%".format(x))
		self.charger.add_path('/Midnite/RawState',			None, writeable=True)
		self.charger.add_path('/Midnite/RestReasonCode',	None, writeable=True)
		self.charger.add_path('/Alerts/OverTemperature',	None, writeable=True)
		self.charger.add_path('/Alerts/CurrentLimit',		None, writeable=True)
		self.charger.add_path('/Connected',					1)
		self.charger.register()

		# =================================================================================
		# DEVICE 2: THE BATTERY MONITOR (WhizBang Jr Service)
		# =================================================================================
		self.battery = VeDbusService (servicename='com.victronenergy.battery.midnite', register=False)
		self.battery.add_path('/DeviceInstance',			0)
		self.battery.add_path('/ProductName',				'Midnite Classic Battery Monitor')
		self.battery.add_path('/Mgmt/ProcessName',			'midnite_hydro.py')
		self.battery.add_path('/Mgmt/ProcessVersion',		config.VERSION)
		self.battery.add_path('/Mgmt/Connection',			'dbus')
		self.battery.add_path('/FirmwareVersion',			config.VERSION)
		self.battery.add_path('/HardwareVersion',			config.VERSION)
		
		# Core Battery Paths
		self.battery.add_path('/Soc',						None, writeable=True, gettextcallback=lambda a, x: "{:d}%".format(x))
		self.battery.add_path('/Dc/0/Voltage',				None, writeable=True, gettextcallback=lambda a, x: "{:.2f}V".format(x))
		self.battery.add_path('/Dc/0/Current',				None, writeable=True, gettextcallback=lambda a, x: "{:.2f}A".format(x))
		self.battery.add_path('/Dc/0/Power',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
		self.battery.add_path('/Dc/0/Temperature',			None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.battery.add_path('/Temps/FET',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.battery.add_path('/Temps/PCB',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		self.battery.add_path('/Yield/User',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}kWh".format(x))
		self.battery.add_path('/Yield/Lifetime',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}kWh".format(x))
		self.battery.add_path('/Yield/AmpHours',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
		self.battery.add_path('/WasteNot/Pwm',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}%".format(x))
		self.battery.add_path('/Midnite/RawState',			None, writeable=True)
		self.battery.add_path('/Midnite/RestReasonCode',	None, writeable=True)
		self.battery.add_path('/Alerts/OverTemperature',	None, writeable=True)
		self.battery.add_path('/Alerts/CurrentLimit',		None, writeable=True)
		self.battery.add_path('/Connected',					1)
		self.battery.register()

	def readModbus (self):
		try:
			if self.classic.connect():
				# ONE safe connection pulls all data
				HR41 = self.classic.read_holding_registers (4100, 100)
				HR42 = self.classic.read_holding_registers (4200, 100)
				HR43 = self.classic.read_holding_registers (4300, 100)
				self.classic.close ()
				
				self.charger['/Connected'] = 1
				self.battery['/Connected'] = 1

				# Extract Values
				SOC				= HR43.registers[72]
				INPUT_V			= float(HR41.registers[15])/10
				INPUT_A			= float(HR41.registers[20])/10
				INPUT_P			= round(INPUT_V * INPUT_A)
				BATT_V			= float(HR41.registers[14])/10
				BATT_A			= float(HR41.registers[16])/10
				BATT_P			= HR41.registers[18]            
				BATT_T			= float(HR41.registers[31])/10
				FET_T			= float(HR41.registers[32])/10
				PCB_T			= float(HR41.registers[33])/10
				CHARGE_STATE	= (HR41.registers[19] & 0xFF00)>> 8
				MIDNITE_STATE	= (HR41.registers[19] & 0x00FF)
				SHUNT_A			= float (twos_complement(HR43.registers[70],16))/10
				DAILY_KWH		= float(HR41.registers[17])/10
				DAILY_AH		= HR41.registers[24]
				PWM_RAW			= HR41.registers[40]
				PWM_PERCENT		= (PWM_RAW / 1023.0) * 100
				LIFETIME_KWH	= (HR41.registers[26] << 16) + HR41.registers[25]
				REST_REASON		= HR42.registers[74]
				
				INFO_FLAGS		= (HR41.registers[30] << 16) + HR41.registers[29]
				OVER_TEMP		= 1 if (INFO_FLAGS & 0x00000001) else 0
				CURRENT_LIMIT	= 1 if (INFO_FLAGS & 0x00000200) else 0

				# Update Device 1: The Hydro Turbine
				self.charger['/State']					= config.MIDNITE_VICTRON[CHARGE_STATE]
				self.charger['/Pv/V']					= INPUT_V
				self.charger['/Pv/I']					= INPUT_A
				self.charger['/Pv/Power']				= INPUT_P
				self.charger['/Yield/Power']			= BATT_P
				self.charger['/Yield/User']				= DAILY_KWH
				self.charger['/Dc/0/Voltage']			= BATT_V
				self.charger['/Dc/0/Current']			= BATT_A
				self.charger['/Yield/Lifetime']			= LIFETIME_KWH
				self.charger['/Yield/AmpHours']			= DAILY_AH
				self.charger['/Temps/Battery']			= BATT_T
				self.charger['/Temps/FET']				= FET_T
				self.charger['/Temps/PCB']				= PCB_T
				self.charger['/Soc']					= SOC
				self.charger['/Dc/0/ShuntCurrent']		= SHUNT_A
				self.charger['/WasteNot/Pwm']			= PWM_PERCENT
				self.charger['/Midnite/RawState']		= MIDNITE_STATE
				self.charger['/Midnite/RestReasonCode']	= REST_REASON
				self.charger['/Alerts/OverTemperature']	= OVER_TEMP
				self.charger['/Alerts/CurrentLimit']	= CURRENT_LIMIT

				# Update Device 2: The Battery Monitor
				self.battery['/Soc']					= SOC
				self.battery['/Dc/0/Voltage']			= BATT_V
				self.battery['/Dc/0/Current']			= SHUNT_A
				self.battery['/Dc/0/Power']				= round(BATT_V * SHUNT_A)
				self.battery['/Dc/0/Temperature']		= BATT_T
				self.battery['/Temps/FET']				= FET_T
				self.battery['/Temps/PCB']				= PCB_T
				self.battery['/Yield/User']				= DAILY_KWH
				self.battery['/Yield/Lifetime']			= LIFETIME_KWH
				self.battery['/Yield/AmpHours']			= DAILY_AH
				self.battery['/WasteNot/Pwm']			= PWM_PERCENT
				self.battery['/Midnite/RawState']		= MIDNITE_STATE
				self.battery['/Midnite/RestReasonCode']	= REST_REASON
				self.battery['/Alerts/OverTemperature']	= OVER_TEMP
				self.battery['/Alerts/CurrentLimit']	= CURRENT_LIMIT
			else:
				logger.info ('unable to connect to %s' % self.sIP)
				self.charger['/Connected'] = 0
				self.battery['/Connected'] = 0

		except Exception as e:
			logger.info('Exception updating values: ' + repr(e))
			self.charger['/Connected'] = 0
			self.battery['/Connected'] = 0
		return True

	def run (self):
		self.t = GLib.timeout_add (self.iFrequency*1000, self.readModbus)

	def cancel (self):
		GLib.remove_source (self.t)
		self.terminated = True

logger = setup_logging (debug=False)
DBusGMainLoop (set_as_default=True)
t = readMidnite (config.MIDNITE_IP, config.MIDNITE_INTERVAL)
t.run ()

logger.info('Connected to dbus, and switching over to GLib.MainLoop() (= event based)')
mainloop = GLib.MainLoop()
mainloop.run()