Here is the fully updated script. I have left the State of Charge (SOC) pull intact exactly as requested, and integrated the new Lifetime Generation, Rest Reason, and Hardware Alert flags.

I also added comments for the new DBus paths so your Grafana mapping remains straightforward.

```python
#!/usr/bin/env python

# Name: 		charger.py
# Purpose:	Present a Hydro generator to VenusOS (Midnite Classic)
#           Optimized for native VRM display with extra MQTT telemetry for Grafana
# Date:		06-05-2026
# Version:	2.6 (Added Lifetime Yield, Error States, and Hardware Alerts)
# Author:	Jan Bakuwel / YSolar NZ Ltd (Modified for MidNite Classic Hydro)
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

		logger.info ('Initialising Midnite Hydro thread: IP=%s, Freq=%d' % (self.sIP, self.iFrequency))
		
		# Core service must remain solarcharger for VRM compatibility
		self.service = VeDbusService (servicename='com.victronenergy.solarcharger.midnite', register=False)
		self.service.add_path('/DeviceInstance',			0)
		self.service.add_path('/ProductName',				'Midnite Classic Hydro Turbine')
		self.service.add_path('/Mgmt/ProcessName',		'charger.py')
		self.service.add_path('/Mgmt/ProcessVersion',	config.VERSION)
		self.service.add_path('/Mgmt/Connection',			'dbus')
		self.service.add_path('/FirmwareVersion',			config.VERSION)
		self.service.add_path('/HardwareVersion',			config.VERSION)
		self.service.add_path('/State',						None, writeable=True)
		
		# --- STANDARD VICTRON PATHS (Keeps VRM and CCGX screen happy) ---
		
		# The raw DC voltage coming in from the hydroelectric turbine
		self.service.add_path('/Pv/V',						None, writeable=True, gettextcallback=lambda a, x: "{:.0f}V".format(x))
		
		# The raw DC current (Amps) coming in from the hydroelectric turbine
		self.service.add_path('/Pv/I',						None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		
		# The calculated raw wattage being produced by the turbine (Input Volts * Input Amps)
		self.service.add_path('/Pv/Power',					None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
		
		# The actual, processed DC wattage the MidNite Classic is delivering to the 24V battery bank
		self.service.add_path('/Yield/Power',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
		
		# The current voltage of the 24V battery bank as measured by the charge controller
		self.service.add_path('/Dc/0/Voltage',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}V".format(x))
		
		# The amount of current (Amps) the charge controller is actively pushing into the battery bank
		self.service.add_path('/Dc/0/Current',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		
		# The total energy (in kWh) generated today, resetting automatically at midnight
		self.service.add_path('/Yield/User',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}kWh".format(x))
		
		# --- CUSTOM GRAFANA PATHS (Ignored by VRM, broadcast to MQTT) ---
		
		# The all-time lifetime energy generation of the unit (in kWh)
		self.service.add_path('/Yield/Lifetime',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}kWh".format(x))
		
		# The physical temperature of the battery bank (requires the MidNite external temp sensor)
		self.service.add_path('/Temps/Battery',				None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		
		# The temperature of the MidNite Classic's internal power transistors (crucial for 24/7 hydro runs)
		self.service.add_path('/Temps/FET',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		
		# The temperature of the MidNite Classic's main control board / brain
		self.service.add_path('/Temps/PCB',					None, writeable=True, gettextcallback=lambda a, x: "{:.1f}C".format(x))
		
		# The battery's State of Charge percentage (Note: May rely on specific firmware version)
		self.service.add_path('/Soc',						None, writeable=True, gettextcallback=lambda a, x: "{:.0f}%".format(x))
		
		# The net current flowing in or out of the battery bank, measured by the WhizBang Jr shunt
		self.service.add_path('/Dc/0/ShuntCurrent',			None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
		
		# The total Amp-Hours generated today, resetting at midnight (useful for tracking efficiency alongside kWh)
		self.service.add_path('/Yield/AmpHours',			None, writeable=True, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
		
		# The duty cycle (0-100%) of the AUX 2 port, showing how much excess power is being dumped to the thermal store
		self.service.add_path('/WasteNot/Pwm',				None, writeable=True, gettextcallback=lambda a, x: "{:.0f}%".format(x))
		
		# The internal, granular operating state code specific to the MidNite Classic (e.g., resting, bulk, absorb)
		self.service.add_path('/Midnite/RawState',			None, writeable=True)
		
		# The exact integer code for WHY the turbine is resting (e.g., 6 = FET Temp High, 22 = Battery V High)
		self.service.add_path('/Midnite/RestReasonCode',	None, writeable=True)
		
		# Hardware boolean alert (1 = Over Temperature, 0 = Normal)
		self.service.add_path('/Alerts/OverTemperature',	None, writeable=True)
		
		# Hardware boolean alert (1 = Current Limit Reached, 0 = Normal)
		self.service.add_path('/Alerts/CurrentLimit',		None, writeable=True)
		
		self.service.add_path('/Connected',					1)
		self.service.register()
		logger.info ('Initialised Midnite Hydro thread: IP=%s, Freq=%d' % (self.sIP, self.iFrequency))

	def readModbus (self):
		try:
			if self.classic.connect ():
				HR41 = self.classic.read_holding_registers (4100, 100)
				HR42 = self.classic.read_holding_registers (4200, 100)
				HR43 = self.classic.read_holding_registers (4300, 100)
				self.classic.close ()
				self.service['/Connected'] = 1

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
				
				# New Integrations (Yield, State Info, Flags)
				LIFETIME_KWH	= (HR41.registers[26] << 16) + HR41.registers[25]
				REST_REASON		= HR42.registers[74]
				INFO_FLAGS		= (HR41.registers[30] << 16) + HR41.registers[29]
				
				# Extracting explicit hardware alerts using bitwise masks from InfoFlags
				OVER_TEMP		= 1 if (INFO_FLAGS & 0x00000001) else 0
				CURRENT_LIMIT	= 1 if (INFO_FLAGS & 0x00000200) else 0

				# Publish Standard Victron Paths
				self.service['/State']				= config.MIDNITE_VICTRON[CHARGE_STATE]
				self.service['/Pv/V']				= INPUT_V
				self.service['/Pv/I']				= INPUT_A
				self.service['/Pv/Power']			= INPUT_P
				self.service['/Yield/Power']		= BATT_P  
				self.service['/Yield/User']			= DAILY_KWH
				self.service['/Dc/0/Voltage']		= BATT_V
				self.service['/Dc/0/Current']		= BATT_A
				
				# Publish Custom Grafana Paths
				self.service['/Yield/Lifetime']			= LIFETIME_KWH
				self.service['/Temps/Battery']			= BATT_T
				self.service['/Temps/FET']				= FET_T
				self.service['/Temps/PCB']				= PCB_T
				self.service['/Soc']					= SOC
				self.service['/Dc/0/ShuntCurrent']		= SHUNT_A
				self.service['/Yield/AmpHours']			= DAILY_AH
				self.service['/WasteNot/Pwm']			= PWM_PERCENT
				self.service['/Midnite/RawState']		= MIDNITE_STATE
				self.service['/Midnite/RestReasonCode']	= REST_REASON
				self.service['/Alerts/OverTemperature']	= OVER_TEMP
				self.service['/Alerts/CurrentLimit']	= CURRENT_LIMIT

			else:
				logger.info ('unable to connect to %s' % self.sIP)
				self.service['/Connected'] = 0

		except Exception as e:
			logger.info('Exception updating values: ' + repr(e))
			self.service['/Connected'] = 0
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

```
