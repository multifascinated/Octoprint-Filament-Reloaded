# coding=utf-8
from __future__ import absolute_import
from flask import jsonify

import octoprint.plugin
from octoprint.events import Events
import RPi.GPIO as GPIO
from time import sleep
from time import time
from flask import jsonify



class filamentsensorngPlugin(octoprint.plugin.StartupPlugin,
                             octoprint.plugin.EventHandlerPlugin,
                             octoprint.plugin.TemplatePlugin,
                             octoprint.plugin.SettingsPlugin,
                             octoprint.plugin.BlueprintPlugin):

    last_callback_time = 0

    def initialize(self):
        self._logger.info("Running RPi.GPIO version '{0}'".format(GPIO.VERSION))
        if GPIO.VERSION < "0.6":       # Need at least 0.6 for edge detection
            raise Exception("RPi.GPIO must be greater than 0.6")
        GPIO.setwarnings(False)        # Disable GPIO warnings


    @octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
    def check_status(self):
        status = "-1"
        if self.sensor_enabled():
            status = "0" if self.no_filament() else "1"
        return jsonify(status=status)

    @property
    def pin(self):
        return int(self._settings.get(["pin"]))

    @property
    def switch_debounce_period(self):
        return int(self._settings.get(["switch_debounce_period"]))

    @property
    def state_debounce_period(self):
        return int(self._settings.get(["state_debounce_period"]))

    @property
    def switch(self):
        return int(self._settings.get(["switch"]))

    @property
    def mode(self):
        return int(self._settings.get(["mode"]))

    @property
    def debug_mode(self):
        return int(self._settings.get(["debug_mode"]))

    @property
    def no_filament_gcode(self):
        return str(self._settings.get(["no_filament_gcode"])).splitlines()

    @property
    def pause_print(self):
        return self._settings.get_boolean(["pause_print"])
    
    def _set_board_mode(self):
        if self.mode == 0:
            self._logger.info("Using Board Mode")
            GPIO.setmode(GPIO.BOARD)
        else:
            self._logger.info("Using BCM Mode")
            GPIO.setmode(GPIO.BCM)

    @property
    def send_gcode_only_once(self):
        return self._settings.get_boolean(["send_gcode_only_once"])

    def _setup_sensor(self):
        if self.sensor_enabled():
            self._logger.info("Setting up sensor.")
            self._set_board_mode()
            self._logger.info("Filament Sensor active on GPIO Pin [%s]"%self.pin)
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        else:
            self._logger.info("Pin not configured, won't work unless configured!")

    def on_after_startup(self):
        self._logger.info("FilamentSensor-ng started")
        self._setup_sensor()

    def get_settings_defaults(self):
        return({
            'pin':-1,   # Default is no pin
            'switch_debounce_period': 200,  # Debounce 200ms
            'state_debounce_period': 5,  # Debounce 5 seconds
            'switch':0,    # Normally Open
            'mode':0,    # Board Mode
            'no_filament_gcode':'',
            'debug_mode':0, # Debug off!
            'pause_print':True,
            'send_gcode_only_once': False, # Default set to False for backward compatibility
        })
    
    def debug_only_output(self, string):
        if self.debug_mode==1:
            self._logger.info(string)

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._setup_sensor()

    def sensor_triggered(self):
        return self.triggered

    def sensor_enabled(self):
        return self.pin != -1

    def no_filament(self):
        return GPIO.input(self.pin) != self.switch
    
    def has_filament(self):
        return GPIO.input(self.pin) == self.switch

    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=False)]

    def on_event(self, event, payload):
        # Early abort in case of out ot filament when start printing, as we
        # can't change with a cold nozzle
        if event is Events.PRINT_STARTED and self.no_filament():
            self._logger.info("Printing aborted: no filament detected!")
            self._printer.cancel_print()
        # Enable sensor
        if event in (
            Events.PRINT_STARTED,
            Events.PRINT_RESUMED
        ):
            self._logger.info("%s: Enabling filament sensor." % (event))
            if self.sensor_enabled():
                self.triggered = 0 # reset triggered state
                GPIO.remove_event_detect(self.pin)
                GPIO.add_event_detect(
                    self.pin, GPIO.BOTH,
                    callback=self.sensor_callback,
                    bouncetime=self.switch_debounce_period
                )
        # Disable sensor
        elif event in (
            Events.PRINT_DONE,
            Events.PRINT_FAILED,
            Events.PRINT_CANCELLED,
            Events.ERROR
        ):
            self._logger.info("%s: Disabling filament sensor." % (event))
            GPIO.remove_event_detect(self.pin)

    @octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
    def check_status(self):
        self._logger.info("Checking status")
        has_filament = self.pin != -1 and self.has_filament()
        return jsonify( has_filament = has_filament )

    def sensor_callback(self, _):
        if time() - self.last_callback_time < self.state_debounce_period*2:
          return self._logger.info("Skipping event call. Debounce period is not over.")
        self.last_callback_time = time()
        self.debug_only_output('sensor callback triggered')
        self.debug_only_output('State debounce pause: '+str(self.state_debounce_period))
        sleep(self.state_debounce_period)
        if self.has_filament(): return
        self._logger.info("Out of filament!")
        if self.pause_print:
            self._logger.info("Pausing print.")
            self._printer.pause_print()
        if self.no_filament_gcode:
            self._logger.info("Sending out of filament GCODE")
            self._printer.commands(self.no_filament_gcode)


    def get_update_information(self):
        return dict(
            octoprint_filamentsensorng=dict(
                displayName="Filament Sensor NG",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="Red-M",
                repo="Octoprint-Filament-Sensor-ng",
                current=self._plugin_version,

                # update method: pip
                pip="https://github.com/Red-M/Octoprint-Filament-Sensor-ng/archive/{target_version}.zip"
            )
        )

__plugin_name__ = "Filament Sensor NG"
__plugin_version__ = "999.0.2"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = filamentsensorngPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
}
