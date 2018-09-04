#!/usr/bin/env python3
# p25 receiver module
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

import socket
import threading
import time

import gammarf_util
from gammarf_base import GrfModuleBase

CALL_REGEX = r'[\S\s]+Call created for: ([0-9]+) [\S\s]+'
LST_ADDR = "127.0.0.1"
MOD_NAME = "p25log"
MODULE_P25LOG = 4
PROTOCOL_VERSION = 1
SOCK_BUFSZ  = 1024


def start(config):
    return GrfModuleP25Receiver(config)


class P25Log(threading.Thread):
    def __init__(self, port, system_mods, settings):
        threading.Thread.__init__(self)

        self.connector = system_mods['connector']
        self.settings = settings
        self.port = port

    def run(self):
        data = {}
        data['module'] = MODULE_P25LOG
        data['protocol'] = PROTOCOL_VERSION

        self.lstsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            self.lstsock.bind( ('', self.port) )
        except Exception as e:
            gammarf_util.console_message("could not listen on port {}: {}"
                    .format(self.port, e), MOD_NAME)
            return

        self.lstsock_file = self.lstsock.makefile()
        try:
            for line in self.lstsock_file:
                if '\t' in line:
                    tmp = line.split('\t')
                else:
                    continue

                if len(tmp) != 4:
                    continue

                msg = tmp[1]
                if msg.startswith('TG:'):
                    talkgroup = msg.split()[1].strip()
                else:
                    continue

                if self.settings['print_all']:
                    gammarf_util.console_message("talkgroup: {}"
                    .format(talkgroup), MOD_NAME)

                data['talkgroup'] = talkgroup

                try:
                    self.connector.senddat(data)
                except:
                    pass
        except ValueError:
            pass  # while stopping module

        return

    def join(self, timeout=None):
        self.lstsock_file.close()
        self.lstsock.close()
        super(P25Log, self).join(timeout)


class GrfModuleP25Receiver(GrfModuleBase):
    """ P25log: Parse trunk-recorder lines received on a UDP port

        Usage: run p25log devid port
            devid must be >= 9000 (this is a pseudo-module)

        Example: run p25log 9000 50000

        Settings:
            print_all: Print each talkgroup as its identified
    """


    def __init__(self, config):
        self.device_list = ['pseudo']
        self.description = "p25 receiver module"
        self.settings = {'print_all': False}
        self.worker = None

        self.thread_timeout = 3

        gammarf_util.console_message("loaded", MOD_NAME)

    def usage(self):
        gammarf_util.console_message("must include a port on "\
                "the command line (eg. > p25log 9000 50000)",
                MOD_NAME)
        return

    # overridden 
    def ispseudo(self):
        return True

    def run(self, grfstate, devid, cmdline, remotetask=False):
        self.remotetask = remotetask
        self.system_mods = grfstate.system_mods
        self.devid = devid

        if self.worker:
            gammarf_util.console_message("module already running", MOD_NAME)
            return

        if not cmdline:
            self.usage()
            return

        try:
            port = int(cmdline.strip())
        except Exception:
            gammarf_util.console_message("bad port number", MOD_NAME)
            return

        self.worker = P25Log(port, self.system_mods, self.settings)
        self.worker.daemon = True
        self.worker.start()

        gammarf_util.console_message("{} added on device {}"
                .format(self.description, devid))
        return True
