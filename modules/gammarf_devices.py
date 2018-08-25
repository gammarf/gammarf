#!/usr/bin/env python3
# devices module
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

import rtlsdr
import string
import sys
import time
from collections import OrderedDict
from ctypes import c_ubyte, string_at

import gammarf_util
from gammarf_base import GrfModuleBase

sys.path.insert(0, '3rdparty')
import pylibhackrf

# careful with these - spectrum will scan across this range
HACKRF_DEFAULT_MAXSCAN = int(2000)  # MHz (reduce if you'd like, saves cpu)
HACKRF_DEFAULT_MINSCAN = int(50)  # don't change
HACKRF_DEFAULT_STEP = 5000  # actual step may change

HACKRF_DEFAULT_LNA_GAIN = 16
HACKRF_DEFAULT_VGA_GAIN = 20
HACKRF_DEVNUM = 0

RTLSDR_DEFAULT_GAIN = 23
RTLSDR_DEFAULT_MAXFREQ = int(1600e6)
RTLSDR_DEFAULT_MINFREQ = int(50e6)

MOD_NAME = "devices"


def start(config):
    return GrfModuleDevices(config)


class HackRfDev():
    def __init__(self):
        self.devtype = 'hackrf'
        self.devid = None
        self.name = None
        self.job = None
        self.serial = None
        self.usable = True
        self.reserved = False

        self.lna_gain = HACKRF_DEFAULT_LNA_GAIN
        self.vga_gain = HACKRF_DEFAULT_VGA_GAIN
        self.minfreq = HACKRF_DEFAULT_MINSCAN
        self.maxfreq = HACKRF_DEFAULT_MAXSCAN
        self.step = HACKRF_DEFAULT_STEP


class PseudoDev():
    def __init__(self):
        self.devtype = 'pseudo'
        self.devid = None
        self.name  = None
        self.job = None
        self.serial = None
        self.usable = True
        self.reserved = False


class RtlSdrDev():
    def __init__(self):
        self.devtype = 'rtlsdr'
        self.devid = None
        self.name = None
        self.job = None
        self.serial = None
        self.usable = True
        self.reserved = False

        self.gain = RTLSDR_DEFAULT_GAIN
        self.offset = 0
        self.ppm = 0
        self.minfreq = RTLSDR_DEFAULT_MINFREQ
        self.maxfreq = RTLSDR_DEFAULT_MAXFREQ


class VirtualDev():  # modules sharing the first hackrf
    def __init__(self):
        self.devtype = 'virtual'
        self.devid = None
        self.name = None
        self.job = None
        self.serial = None
        self.usable = True
        self.reserved = False


class GrfModuleDevices(GrfModuleBase):
    def __init__(self, config):
        self.description = "devices module"
        self.settings = {}

        self.thread_timeout = 3

        gammarf_util.console_message("Loaded {}".format(self.description))

        devs = OrderedDict()
        devidx = 0

        hackrf = pylibhackrf.HackRf()
        r = hackrf.setup()
        if r != pylibhackrf.HackRfError.HACKRF_SUCCESS:
            self.have_hackrf = False
            gammarf_util.console_message("no hackrf found", MOD_NAME)

        else:
            self.have_hackrf = True
            hackrf.set_amp_enable(False)

            hrfdev = HackRfDev()
            hrfdev.devid = HACKRF_DEVNUM
            hrfdev.name = "{} HackRF".format(hrfdev.devid, hrfdev.devid)
            hrfdev.job = "Virtual Provider"

            if 'hackrfdevs' in config:
                if 'lna_gain' in config['hackrfdevs']:
                    hrfdev.lna_gain = int(config['hackrfdevs']['lna_gain'])

                if 'vga_gain' in config['hackrfdevs']:
                    hrfdev.vga_gain = int(config['hackrfdevs']['vga_gain'])

                if 'minfreq' in config['hackrfdevs']:
                    hrfdev.minfreq = int(config['hackrfdevs']['minfreq'])

                if 'maxfreq' in config['hackrfdevs']:
                    hrfdev.maxfreq = int(config['hackrfdevs']['maxfreq'])

                if 'step' in config['hackrfdevs']:
                    hrfdev.step = int(config['hackrfdevs']['step'])

            devs[HACKRF_DEVNUM] = hrfdev
            devidx += 1
        hackrf.close()

        rtlsdr_devcount = rtlsdr.librtlsdr.rtlsdr_get_device_count()
        if not rtlsdr_devcount and not hackrf:
            gammarf_util.console_message("found no usable devices", MOD_NAME)
            exit()

        for rtl_devid in range(rtlsdr_devcount):
            rtldev = RtlSdrDev()
            rtldev.devid = rtl_devid

            buffer1 = (c_ubyte * 256)()
            buffer2 = (c_ubyte * 256)()
            serial = (c_ubyte * 256)()
            rtlsdr.librtlsdr.rtlsdr_get_device_usb_strings(rtl_devid,
                    buffer1, buffer2, serial)
            serial = string_at(serial)
            tmp = rtlsdr.librtlsdr.rtlsdr_get_device_name(rtl_devid)
            devname = "{} {} {}".format(devidx,
                    tmp.decode('utf-8'),
                    serial.decode('utf-8'))

            rtldev.name = devname
            rtldev.serial = serial
            gammarf_util.console_message(devname, MOD_NAME)

            if 'rtldevs' in config:
                try:
                    frangestr = config['rtldevs']['range_{}'
                            .format(serial.decode('utf-8'))]
                except KeyError:
                    pass
                else:
                    try:
                        minfreq, maxfreq = frangestr.split(None, 2)
                        minfreq = int(float(minfreq) * 1e6)
                        maxfreq = int(float(maxfreq) * 1e6)

                    except Exception as e:
                        raise Exception("Invalid frequency range string: {}: {}"
                                .format(frangestr, e))

                    rtldev.minfreq = minfreq
                    rtldev.maxfreq = maxfreq

                if rtldev.minfreq >= rtldev.maxfreq:
                    raise Exception("Maximum devicefreq must be larger than "\
                            "minimum device freq")

                try:
                    stickgain = config['rtldevs']['gain_{}'
                            .format(serial.decode('utf-8'))]
                except KeyError:
                    pass
                else:
                    rtldev.gain = float(stickgain)

                try:
                    stickppm = config['rtldevs']['ppm_{}'
                            .format(serial.decode('utf-8'))]
                except KeyError:
                    pass
                else:
                    rtldev.ppm = int(stickppm)

                try:
                    stickoffset = config['rtldevs']['offset_{}'
                            .format(serial.decode('utf-8'))]
                except KeyError:
                    pass
                else:
                    rtldev.offset = int(stickoffset)

            devs[devidx] = rtldev
            devidx += 1

        self.devs = devs
        self.numdevs = devidx

    def alldevs(self):
        return self.devs

    def devid_to_module(self, devid):
        if not self.occupied(devid):
            return

        dev = self.devs[devid]
        if not dev.usable:
            return

        module, _, _ = dev.job
        return module

    def freedev(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'virtual':
            self.devs.pop(devid, None)
        elif dev.devtype == 'pseudo':
            self.devs.pop(devid, None)
        else:
            dev.job = None
        return

    def get_devs(self):
        return [dtup[1].name for dtup in self.devs.items()]

    def get_devtype(self, devid):
        try:
            devid = int(devid)
        except ValueError:
            return 'virtual'
        dev = self.devs[devid]
        return dev.devtype

    def get_hackrf_devnum(self):
        if not self.have_hackrf:
            return
        return HACKRF_DEVNUM

    def get_hackrf_job(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].job

    def get_hackrf_lnagain(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].lna_gain

    def get_hackrf_maxfreq(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].maxfreq

    def get_hackrf_minfreq(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].minfreq

    def get_hackrf_step(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].step

    def get_hackrf_vgagain(self):
        if not self.have_hackrf:
            return
        return self.devs[HACKRF_DEVNUM].vga_gain

    def get_max_freq(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.maxfreq
        return

    def get_min_freq(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.minfreq
        return

    def get_numdevs(self):
        return self.numdevs

    def get_rtlsdr_gain(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.gain
        return

    def get_rtlsdr_maxfreq(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.maxfreq
        return

    def get_rtlsdr_minfreq(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.minfreq
        return

    def get_rtlsdr_offset(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.offset
        return

    def get_rtlsdr_ppm(self, devid):
        dev = self.devs[devid]
        if dev.devtype == 'rtlsdr':
            return dev.ppm
        return

    def get_sysdevid(self, devid):
        dev = self.devs[devid]
        return dev.devid

    def hackrf(self):
        return self.have_hackrf

    def isdev(self, devid):
        if devid in self.devs:
            return True
        return False

    def ishackrf(self, devid):
        if not self.have_hackrf:
            return False
        return devid == HACKRF_DEVNUM

    def next_virtualdev(self):
        for char in string.ascii_lowercase:
            if char not in self.devs:
                return char
        return None

    def occupied(self, devid):
        if self.hackrf and self.ishackrf(devid):
            return False

        if not self.isdev(devid):
            return False

        dev = self.devs[devid]
        if dev.job:
            return True

        return False

    def occupy(self, devid, module, cmdline=None, pseudo=False):
        virtual = False
        try:
            devid = int(devid)
        except ValueError:
            virtual = True

        if virtual:
            dev = VirtualDev()
            dev.name = "{} {}".format(devid, 'Virtual')
            dev.job = (module, cmdline, time.strftime("%c"))
            self.devs[devid] = dev
            return True

        elif pseudo:
            dev = PseudoDev()
            dev.devid = devid
            dev.name = "{} Pseudo device".format(devid)
            dev.job = (module, cmdline, time.strftime("%c"))
            self.devs[devid] = dev
            return True

        else:
            dev = self.devs[devid]
            if dev.job or not dev.usable:
                return
            dev.job = (module, cmdline, time.strftime("%c"))
            return True

        return

    def removedev(self, devid):
        if self.isdev(devid):
            dev = self.devs[devid]
            dev.job = "*** Out of commission"
            dev.usable = False
        return

    def reserve(self, devid):
        if self.isdev(devid):
            dev = self.devs[devid]
            dev.reserved = True
            dev.job = "*** Reserved"
        return

    def reserved(self, devid):
        if self.have_hackrf:
            if self.ishackrf(devid):
                return False

        if not self.isdev(devid):
            return False

        dev = self.devs[devid]
        return dev.reserved

    def running(self):
        jobs = []
        for devtuple in self.devs.items():
            dev = devtuple[1]
            if dev.reserved:
                continue
            if dev.job:
                jobs.append(dev.job)

        return jobs

    def set_hackrf_step(self, step):
        if not self.have_hackrf:
            return

        dev = self.devs[HACKRF_DEVNUM]
        dev.step = step
        return

    def unreserve(self, devid):
        dev = self.devs[devid]
        dev.reserved = False
        dev.job = None
        return

    def usable(self, devid):
        dev = self.devs[devid]
        return dev.usable

    # Commands we provide
    def cmd_devs(self, grfstate, args):
        """Show loaded devices and running modules"""

        system_mods = grfstate.system_mods
        system_mods['devices'].info()
        return

    def cmd_reserve(self, grfstate, args):
        """Reserve a device"""

        system_mods = grfstate.system_mods
        devmod = system_mods['devices']

        try:
            devid = int(args)
        except (ValueError, TypeError):
            gammarf_util.console_message(
            "command takes a device number as its argument")
            return

        if devmod.hackrf():
            if devmod.ishackrf(devid):
                gammarf_util.console_message("invalid device: {}"
                        .format(HACKRF_DEVNUM))

        if not devmod.isdev(devid):
            gammarf_util.console_message("not a valid device number: {}"
                    .format(devid))
            return

        if devmod.occupied(devid):
            gammarf_util.console_message("device occupied: {}".format(devid))
            return

        if devmod.reserved(devid):
            gammarf_util.console_message("device {} already reserved"
                    .format(devid))
            return

        devmod.reserve(devid)
        return

    def cmd_stop(self, grfstate, args):
        """Stop a task occupying a device (> stop device)"""

        loadedmods = grfstate.loadedmods
        system_mods = grfstate.system_mods
        devmod = system_mods['devices']

        if not args:
            gammarf_util.console_message(
                    "command takes a device number or letter as its argument")
            return

        try:
            devid = int(args)
            virtual = False
        except ValueError:
            devid = args.strip()
            virtual = True

        if devmod.hackrf():
            if devmod.ishackrf(devid):
                gammarf_util.console_message("invalid device: {}"
                        .format(HACKRF_DEVNUM))

        if not devmod.isdev(devid):
            gammarf_util.console_message("not a device: {}".format(devid))
            return

        if devmod.reserved(devid):
            gammarf_util.console_message("device {} is reserved".format(devid))
            return

        module = devmod.devid_to_module(devid)
        if module:
            loadedmods[module].stop(devid, devmod)
        else:
            gammarf_util.console_message("device {} not occupied"
                    .format(devid))
        return

    def cmd_unreserve(self, grfstate, args):
        """Unreserve a device"""

        system_mods = grfstate.system_mods
        devmod = system_mods['devices']

        try:
            devid = int(args)
        except (ValueError, TypeError):
            gammarf_util.console_message("command takes a device "\
                    "number as its argument")
            return

        if devmod.hackrf():
            if devmod.ishackrf(devid):
                gammarf_util.console_message("invalid device: {}"
                        .format(HACKRF_DEVNUM))

        if not devmod.isdev(devid):
            gammarf_util.console_message("not a valid device number: {}"
                    .format(devid))
            return

        if not devmod.reserved(devid):
            return

        devmod.unreserve(devid)
        return

    # overridden 
    def commands(self):
        return [('devs', self.cmd_devs),
                ('reserve', self.cmd_reserve),
                ('stop', self.cmd_stop),
                ('unreserve', self.cmd_unreserve)]

    def devices(self):
        return None

    def info(self):
        for devtuple in self.devs.items():
            dev = devtuple[1]

            if dev.job:
                try:
                    module, args, started = dev.job
                    argstr = args if args else "no args"
                    jobstr = "{}, {}, started: {}"\
                            .format(module, argstr, started)
                except ValueError:
                    jobstr = dev.job
            else:
                jobstr = "no job"

            gammarf_util.console_message("{}: {}".format(dev.name, jobstr))

    def shutdown(self):
        gammarf_util.console_message("shutting down {}"
                .format(self.description))
        return
