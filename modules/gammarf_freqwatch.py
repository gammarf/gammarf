#!/usr/bin/env python3
# freqwatch module
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

import datetime
import threading
import time

import gammarf_util
from gammarf_base import GrfModuleBase

INTERESTING_REFRESH_INT = 10  # s
LOOP_SLEEP = 5
MOD_NAME = "freqwatch"
MODULE_FREQWATCH = 6
PROTOCOL_VERSION = 1


def start(config):
    return GrfModuleFreqwatch(config)


class Freqwatch(threading.Thread):
    def __init__(self, system_mods, settings):
        threading.Thread.__init__(self)
        self.stoprequest = threading.Event()

        self.connector = system_mods['connector']
        self.devmod = system_mods['devices']
        self.spectrum = system_mods['spectrum']

        self.maxfreq = int(self.devmod.get_hackrf_maxfreq()*1e6)
        self.minfreq = int(self.devmod.get_hackrf_minfreq()*1e6)

        self.settings = settings
        self.freqlist = []

    def run(self):
        data = {}
        data['module'] = MODULE_FREQWATCH
        data['protocol'] = PROTOCOL_VERSION

        notified_nofreqs = False
        since_interesting_refresh = None

        while not self.stoprequest.isSet():
            if since_interesting_refresh:
                elapsed = datetime.datetime.utcnow()\
                        - since_interesting_refresh
                if elapsed.total_seconds() > INTERESTING_REFRESH_INT:
                    check_interesting = True
            else:
                check_interesting = True

            if check_interesting:
                tmp = self.connector.interesting_raw()
                if not tmp:
                    if not notified_nofreqs:
                        gammarf_util.console_message(
                                "retrieved no interesting freqs",
                                MOD_NAME)
                        notified_nofreqs = True

                else:
                    newfreqs = []
                    tmp = [entry[0] for entry in tmp]
                    for freq in tmp:
                        if freq > self.maxfreq or freq < self.minfreq:
                            gammarf_util.console_message(
                                "frequency out of bounds: {}"
                                    .format(freq), MOD_NAME)
                            continue

                        newfreqs.append(freq)
                    newfreqs.sort()

                    if newfreqs != self.freqlist:
                        gammarf_util.console_message(
                                "updated interesting freqs",
                                MOD_NAME)
                        out = []
                        for entry in newfreqs:
                            out.append(str(entry))
                        gammarf_util.console_message(", ".join(out), MOD_NAME)

                        self.freqlist = list(newfreqs)  # make a copy
                        notified_nofreqs = False

                since_interesting_refresh = datetime.datetime.utcnow()
                check_interesting = False

            for freq in self.freqlist:
                pwr = self.spectrum.pwr(freq)
                if pwr:
                    if self.settings['print_all']:
                        gammarf_util.console_message("freq: {}, Pwr: {:.2f}"
                                .format(freq, pwr), MOD_NAME)

                    data['freq'] = freq
                    data['pwr'] = pwr

                    try:
                        self.connector.senddat(data)
                    except:
                        pass

            time.sleep(LOOP_SLEEP)

        return

    def join(self, timeout=None):
        self.stoprequest.set()
        super(Freqwatch, self).join(timeout)


class GrfModuleFreqwatch(GrfModuleBase):
    """ Freqwatch: Periodically report power on specified frequencies

        Usage: run freqwatch hackrf_devid

        Example: run freqwatch 0

        Settings:
            print_all: Print power readings to console
    """

    def __init__(self, config):
        self.device_list = ["hackrf", "virtual"]
        self.description = "freqwatch module"
        self.settings = {'print_all': False}
        self.worker = None

        self.thread_timeout = 3

        gammarf_util.console_message("loaded", MOD_NAME)

    # overridden 
    def run(self, grfstate, devid, cmdline, remotetask=False):
        self.remotetask = remotetask
        system_mods = grfstate.system_mods

        if self.worker:
            gammarf_util.console_message("module already running",
                    MOD_NAME)
            return

        self.worker = Freqwatch(system_mods, self.settings)
        self.worker.daemon = True
        self.worker.start()

        gammarf_util.console_message("{} added on device {}"
                .format(self.description, devid))
        return True
