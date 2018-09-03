#!/usr/bin/env python3
# channels module
#
# Joshua Davis (gammarf -*- covert.codes)
# http://gammarf.io
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import math
import threading
import time

import gammarf_util
from gammarf_base import GrfModuleBase

LOOP_SLEEP = 30
MOD_NAME = "channels"
MODULE_CHANNELS = 10
PROTOCOL_VERSION = 1
ROUND_TO = 5000


def start(config):
    return GrfModuleChannels(config)


class Channels(threading.Thread):
    def __init__(self, threshold, system_mods, settings):
        threading.Thread.__init__(self)
        self.stoprequest = threading.Event()

        self.connector = system_mods['connector']
        self.devmod = system_mods['devices']
        self.spectrum = system_mods['spectrum']

        self.maxfreq = int(self.devmod.get_hackrf_maxfreq()*1e6)
        self.minfreq = int(self.devmod.get_hackrf_minfreq()*1e6)
        self.step = int(self.devmod.get_hackrf_step())
        self.width = int(self.devmod.get_hackrf_step())
        self.threshold = threshold

        self.settings = settings

    def run(self):
        data = {}
        data['module'] = MODULE_CHANNELS
        data['protocol'] = PROTOCOL_VERSION

        chanlist = []
        in_channel = False
        while not self.stoprequest.isSet():
            freq = self.minfreq
            if in_channel:  # entered but never left
                in_channel = False

            while freq < self.maxfreq:
                try:
                    pwr = self.spectrum.pwr(freq)
                except Exception:  # possible while shutting down
                    pass

                if pwr > self.threshold:
                    if in_channel:
                        current_channel_pwrs.append(pwr)
                    else:
                        enter_freq = freq
                        current_channel_pwrs = [pwr]
                        in_channel = True

                else:
                    if in_channel:
                        left_freq = freq

                        bw0 = left_freq - enter_freq
                        center = int(ROUND_TO *
                                round(float(enter_freq + (bw0/2)) / ROUND_TO))
                        center_pwr = self.spectrum.pwr(center)

                        # 3dB bw cutoff
                        cutoff_pwr = center_pwr - abs(center_pwr / 2)
                        filtered_pwrs = []
                        for p in current_channel_pwrs:
                            if p >= cutoff_pwr:
                                filtered_pwrs.append(p)

                        bandwidth = len(filtered_pwrs * self.width)

                        if self.settings['print_all']:
                            gammarf_util.console_message("center: {}, "\
                                    "center pwr: {:.2f}, bandwidth: {}"
                                    .format(center, center_pwr, bandwidth),
                                MOD_NAME)

                        in_channel = False

                        data['center'] = center
                        data['bw'] = bandwidth
                        data['pwr'] = center_pwr
                        try:
                            self.connector.senddat(data)
                        except:
                            pass

                freq += self.step

        return

    def join(self, timeout=None):
        self.stoprequest.set()
        super(Channels, self).join(timeout)


class GrfModuleChannels(GrfModuleBase):
    """ Channels: Find channels in the spectrum

        Usage: run channels hackrf_devid threshold

        Example: run channels 0 -30

        Settings:
            print_all: Print channels as their seen
    """

    def __init__(self, config):
        self.device_list = ["hackrf", "virtual"]
        self.description = "channels module"
        self.settings = {'print_all': False}
        self.worker = None

        self.thread_timeout = 3

        gammarf_util.console_message("loaded", MOD_NAME)

    # overridden 
    def run(self, grfstate, devid, cmdline, remotetask=False):
        self.remotetask = remotetask
        system_mods = grfstate.system_mods

        try:
            threshold = int(cmdline)
        except (TypeError, ValueError) as e:
            gammarf_util.console_message("invalid threshold", MOD_NAME)
            return

        if self.worker:
            gammarf_util.console_message("module already running",
                    MOD_NAME)
            return

        self.worker = Channels(threshold, system_mods, self.settings)
        self.worker.daemon = True
        self.worker.start()

        gammarf_util.console_message("{} added on device {}"
                .format(self.description, devid))
        return True
