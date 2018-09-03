#!/usr/bin/env python3
# spectrum module
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
import os
import struct
import subprocess
import threading
import time
import numpy as np
from sys import builtin_module_names

import gammarf_util
from gammarf_base import GrfModuleBase


HRF_FREQ_BYTES = 8
HRF_PWR_BYTES = 4
MOD_NAME = "spectrum"


def start(config, devmod):
    return GrfModuleSpectrum(config, devmod)


class SpectrumWorker(threading.Thread):
    def __init__(self, devmod, hackrf_cmd):
        self.stoprequest = threading.Event()
        threading.Thread.__init__(self)

        self.devmod = devmod

        self.freqmap = None
        self.freqmap_ready = False

        self.maxfreq = int(devmod.get_hackrf_maxfreq()*1e6)
        self.minfreq = int(devmod.get_hackrf_minfreq()*1e6)
        self.step = None

        fstr = "{}:{}".format(devmod.get_hackrf_minfreq(),
                devmod.get_hackrf_maxfreq())
        width = devmod.get_hackrf_step()
        lna_gain = devmod.get_hackrf_lnagain()
        vga_gain = devmod.get_hackrf_vgagain()

        ON_POSIX = 'posix' in builtin_module_names
        self.cmdpipe = subprocess.Popen([
            hackrf_cmd,
            "-f {}".format(fstr),
            "-w {}".format(width),
            "-l {}".format(lna_gain),
            "-g {}".format(vga_gain),
            "-B",
            "-a 1"],
            stdout=subprocess.PIPE,
            stderr=open(os.devnull, 'w'),
            close_fds=ON_POSIX)

    def run(self):
        firstfreq = None
        total_freqs = 0
        while True:
            try:
                reclen, start, end = struct.unpack('=iqq',
                        self.cmdpipe.stdout.read(20))
            except:
                raise Exception("Problem communicating with HACKRF - exit and restart")

            if not firstfreq:
                firstfreq = start
            else:
                if start == firstfreq:
                    break

            pwr_entries = int((reclen - (HRF_FREQ_BYTES * 2))
                    / HRF_PWR_BYTES)

            if not self.step:
                self.step = int((end - start) / pwr_entries)
                self.devmod.set_hackrf_step(self.step)

            try:
                self.cmdpipe.stdout.read(HRF_PWR_BYTES * pwr_entries)
            except:
                raise Exception("Problem communicating with HACKRF - exit and restart")

            total_freqs += pwr_entries

        self.freqmap = np.empty(total_freqs)
        while not self.stoprequest.isSet():
            try:
                pwrs = self.cmdpipe.stdout.read(HRF_PWR_BYTES * pwr_entries)
            except:
                raise Exception("Problem communicating with HACKRF - exit and restart")

            unpacked = list(struct.unpack('{}f'.format(pwr_entries), pwrs))

            substart = int((start - firstfreq)/self.step)
            substop = substart + pwr_entries
            self.freqmap[substart:substop] = list(unpacked)

            try:
                reclen, start, end = struct.unpack('=iqq',
                        self.cmdpipe.stdout.read(20))
            except:
                raise Exception("Problem communicating with HACKRF - exit and restart")

            if start == firstfreq:
                if not self.freqmap_ready:
                    self.freqmap_ready = True

        return

    def is_freqmap_ready(self):
        return self.freqmap_ready

    def freqbin(self, freq):
        return math.floor((freq - self.minfreq) / self.step)

    def pwr(self, freq):
        if freq > self.maxfreq or freq < self.minfreq:
            return

        freqbin = self.freqbin(freq)
        return self.freqmap[freqbin]

    def join(self, timeout=None):
        self.stoprequest.set()
        super(SpectrumWorker, self).join(timeout)


class GrfModuleSpectrum(GrfModuleBase):
    def __init__(self, config, devmod):
        if not devmod.hackrf():
            return

        if not 'hackrfdevs' in config:
            raise Exception("No hackrf section defined in config")

        try:
            hackrf_path = config['hackrfdevs']['hackrf_path']
        except KeyError:
            raise Exception("param 'hackrf_path' not appropriately "\
                    "defined in config")

        hackrf_cmd = hackrf_path + '/' + 'hackrf_sweep'
        if not os.path.isfile(hackrf_cmd)\
                or not os.access(hackrf_cmd, os.X_OK):
            raise Exception("executable hackrf_sweep not found "\
                    "in specified path")

        self.description = "spectrum module"
        self.settings = {}

        self.worker = SpectrumWorker(devmod, hackrf_cmd)
        self.worker.daemon = True
        self.worker.start()

        self.thread_timeout = 3

        gammarf_util.console_message("loaded", MOD_NAME)

    def is_freqmap_ready(self):
        """Check if the freqmap has been populated"""
        return self.worker.is_freqmap_ready()

    def freqbin(self, freq):
        """Return bin in freqmap placed closest to input frequency"""
        return self.worker.freqbin(freq)

    def pwr(self, freq):
        """Get power at a frequency according to the freqmap"""
        return self.worker.pwr(freq)

    # overridden 
