#!/usr/bin/env python3
# module base
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

import abc

import gammarf_util


class GrfModuleBase():
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def commands(self):
        """What commands do we provide?"""
        return []

    @abc.abstractmethod
    def devices(self):
        """Which devices do we support?"""
        return self.device_list

    @abc.abstractmethod
    def info(self):
        """Module-specific information"""
        return

    @abc.abstractmethod
    def isproxy(self):
        """Is this a router (e.g. the remotetask module)?"""
        return

    @abc.abstractmethod
    def ispseudo(self):
        """Is pseudo module?"""
        return False

    @abc.abstractmethod
    def run(self, grfstate, devid, cmdline, remotetask):
        """Run a module"""
        return

    @abc.abstractmethod
    def setting(self, setting, arg=None):
        """Show/toggle module settings"""
        if setting == None:
            for setting, state in self.settings.items():
                gammarf_util.console_message(
                        "{}: {} ({})".format(setting, state, type(state)))
            return True

        if setting == 0:
            return self.settings.keys()

        if setting not in self.settings:
            return False

        if isinstance(self.settings[setting], bool):
            new = not self.settings[setting]
        elif not arg:
            gammarf_util.console_message(
                    "Non-boolean setting requires an argument")
            return True
        else:
            if isinstance(self.settings[setting], int):
                new = int(arg)
            elif isinstance(self.settings[setting], float):
                try:
                    new = float(arg)
                except ValueError:
                    print("bad argument for setting")
                    return
            else:
                new = arg

        self.settings[setting] = new

    @abc.abstractmethod
    def shutdown(self):
        try:
            gammarf_util.console_message(
                    "shutting down {}".format(self.description))
        except AttributeError:
            pass

        try:
            if self.worker:
                self.worker.join(self.thread_timeout)
        except AttributeError:
            pass

    @abc.abstractmethod
    def stop(self, devid, devmod):
        if self.worker:
            self.worker.join(self.thread_timeout)
            self.worker = None

            if not self.remotetask:
                devmod.freedev(devid)

            return True
        return False
