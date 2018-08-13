#!/usr/bin/env python3
# ΓRF client
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
import configparser
import sys
import time
from collections import OrderedDict
from importlib import import_module
from multiprocessing.managers import BaseManager
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.interface import AbortAction


CONF_FILE = 'gammarf.conf'
PSEUDO_DEVNUM_BASE = 9000
REQ_MESSAGE = 4
SYSTEM_MODS    = ['connector', 'devices', 'location', 'spectrum']
VERSION_STRING = "ΓRF, Copyright 2018 (gammarf |at| covert.codes)"

MODPATH        = 'modules'
MOD_PREFIX     = 'gammarf_'
sys.path.append(MODPATH)

import gammarf_util


class CoreManager(BaseManager):
    pass


class GrfState():
    def __init__(self):
        commands = {}
        loadedmods = OrderedDict()
        system_mods = OrderedDict()

        config = configparser.ConfigParser()
        try:
            config.read(CONF_FILE)
        except Exception:
            raise Exception("could not open configuration file: {}"
                    .format(CONF_FILE))

        if not 'modules' in config:
            raise Exception("no modules section defined in config")

        if not 'modules' in config['modules']:
            raise Exception("no modules listed in configuration file")

        devices_mod = import_module(MOD_PREFIX + 'devices')
        CoreManager.register('devices', getattr(devices_mod,
            'GrfModuleDevices'))

        location_mod = import_module(MOD_PREFIX + 'location')
        CoreManager.register('location', getattr(location_mod,
            'GrfModuleLocation'))

        connector_mod = import_module(MOD_PREFIX + 'connector')
        CoreManager.register('connector', getattr(connector_mod,
            'GrfModuleConnector'))

        spectrum_mod = import_module(MOD_PREFIX + 'spectrum')
        CoreManager.register('spectrum',
                getattr(spectrum_mod, 'GrfModuleSpectrum'))

        core_manager = CoreManager()
        core_manager.start()

        core_manager = CoreManager()
        core_manager.start()

        system_mods['devices'] = core_manager.devices(config)
        system_mods['location'] = core_manager.location(config)
        system_mods['spectrum'] = core_manager.spectrum(config,
                system_mods['devices'])

        if system_mods['devices'].hackrf():
            while not system_mods['spectrum'].is_freqmap_ready():
                gammarf_util.console_message("waiting for freqmap to populate...")
                time.sleep(2)

        system_mods['connector'] = core_manager.connector(config,
                system_mods)

        for sysmod in system_mods:
            modcmds = system_mods[sysmod].commands()
            if not modcmds:
                continue

            for cmd in modcmds:
                if cmd in commands:
                    raise Exception("attempted to register command twice: {}"
                            .format(cmd[0]))
                commands[cmd[0]] = cmd[1]

        modules = set([m.strip() for m in config['modules']['modules']
            .split(',')])

        for module in modules:
            try:
                modsource = MOD_PREFIX + module
                Mod = import_module(modsource)
                ModObj = Mod.start(config)

                modcmds = ModObj.commands()
                for cmd in modcmds:
                    if cmd in commands:
                        raise Exception("attempted to register "\
                                "command twice: {}".format(cmd))
                    commands[cmd[0]] = cmd[1]

                loadedmods[module] = ModObj
            except Exception as e:
                gammarf_util.console_message("warning! could not load module '{}': {}."
                        .format(module, e))

        loaded_str =  ""
        for m in loadedmods:
            loaded_str += "{}, ".format(m)
        loaded_str = loaded_str[:-2]
        gammarf_util.console_message("loaded modules: {}\n\n"
                .format(loaded_str))

        self.commands = commands
        self.config = config
        self.loadedmods = loadedmods
        self.system_mods = system_mods

        return


def main():
    grfstate = GrfState()

    startup_tasks(grfstate)
    pseudo_startup_tasks(grfstate)
    cmdloop(grfstate)

def startup_tasks(grfstate):
    config = grfstate.config
    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods
    devmod = system_mods['devices']

    jobs = []

    if devmod.hackrf():
        try:
            virtlist = config['startup']['startup_virtual']
        except KeyError:
            virtlist = None

        hackrf_devnum = devmod.get_hackrf_devnum()
        if virtlist:
            for cmdline in virtlist.split(','):
                jobs.append( (cmdline, hackrf_devnum) )

    for devid, dev in devmod.alldevs().items():
        serial = dev.serial
        if not serial:  # skip hackrf
            continue

        try:
            cmdline = config['startup']['startup_{}'
                    .format(serial.decode("utf-8"))]
        except KeyError:
            continue

        jobs.append( (cmdline, devid) )

    for cmdline, devid in jobs:
        try:
            module, args = cmdline.split(None, 1)
        except ValueError:
            module = cmdline.strip()
            args = None

        if module in system_mods or module not in loadedmods:
            continue

        if not devmod.usable(devid):
            gammarf_util.console_message("device {} not usable")
            continue

        devtype = devmod.get_devtype(devid)
        if not loadedmods[module].isproxy():  # if not remotetask
            if not devtype in loadedmods[module].devices():
                gammarf_util.console_message("device type {} not supported by module"
                        .format(devtype))
                continue

        if devtype == 'hackrf':
            devid = devmod.next_virtualdev()
            if devid:
                if loadedmods[module].run(grfstate, devid, cmdline):
                    devmod.occupy(devid, module, cmdline)
        else:
            if loadedmods[module].run(grfstate, devid, cmdline):
                devmod.occupy(devid, module, cmdline)

def pseudo_startup_tasks(grfstate):
    config = grfstate.config
    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods
    devmod = system_mods['devices']

    devid = PSEUDO_DEVNUM_BASE
    while True:
        try:
            cmdline = config['startup']['startup_{}'.format(devid)]
        except KeyError:
            break

        try:
            module, args = cmdline.split(None, 1)
        except ValueError:
            module = cmdline.strip()
            args = None

        if module in system_mods or module not in loadedmods:
            devid += 1
            continue

        if not 'pseudo' in loadedmods[module].devices():
            gammarf_util.console_message("module {} does not support pseudo devices"
                    .format(module))

        if loadedmods[module].run(grfstate, devid, args):
            devmod.occupy(devid, module, args, pseudo=True)

        devid += 1

def cmdloop(grfstate):
    commands = grfstate.commands
    config = grfstate.config
    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods

    logo = """
   _______________
   \   __________/
    |  |_____________________
    |  |\______   \_   _____/
    |  | |       _/|    __)
    |  | |    |   \|     \\
    |  | |____|_  /\___  /
    |  |        \/     \/
    \__/

    """
    gammarf_util.console_message(logo, showdt=False)

    intro = '{}\n\n'.format(VERSION_STRING)
    gammarf_util.console_message(intro, showdt=False)
    gammarf_util.console_message("Type 'quit' to quit", showdt=False)

    # system commands
    commands['help'] = cmd_help
    commands['interesting'] = cmd_interesting
    commands['interesting_add'] = cmd_interesting_add
    commands['interesting_del'] = cmd_interesting_del
    commands['location'] = cmd_location
    commands['message'] = cmd_message
    commands['mods'] = cmd_mods
    commands['now'] = cmd_now
    commands['pwr'] = cmd_pwr
    commands['quit'] = cmd_quit
    commands['run'] = cmd_run
    commands['settings'] = cmd_settings
    commands['stations'] = cmd_stations

    stationid = config['connector']['station_id']
    cmdprompt = '{} ΓRF> '.format(stationid)
    history = InMemoryHistory()

    while True:
        rawinput = prompt(cmdprompt,
                completer = GrfCompleter(grfstate),
                enable_history_search = True,
                history = history,
                on_abort = AbortAction.RETRY,
                on_exit = AbortAction.RETRY).strip()

        cmdline = rawinput.split(None, 1)
        if not cmdline:
            continue

        cmd = cmdline[0]
        if len(cmdline) > 1:
            args = cmdline[1]
        else:
            args = None

        if cmd[0] == '#':  # comment
            continue

        if cmd == 'help':
            cmd_help(commands)

        elif cmd == 'run':
            cmd_run(grfstate, args)

        elif cmd == 'quit':
            cmd_quit(grfstate)

        elif cmd in commands:
            commands[cmd](grfstate, args)

        else:
            gammarf_util.console_message("bad command.  Type 'help'.")

def cmd_help(commands):
    """Show system help"""

    gammarf_util.console_message()
    gammarf_util.console_message(VERSION_STRING)
    gammarf_util.console_message("Type 'quit' to quit")

    output = []
    for cmd, function in commands.items():
        output.append("{:18s}| {}".format(cmd, function.__doc__))
    output.sort()

    gammarf_util.console_message()
    for line in output:
        gammarf_util.console_message(line)
    gammarf_util.console_message()

def cmd_interesting(grfstate, args):
    """Show current interesting frequencies for this node"""

    system_mods = grfstate.system_mods
    if not system_mods['connector'].interesting_pretty():
        gammarf_util.console_message("error getting interesting freqs")

def cmd_interesting_add_usage():
    gammarf_util.console_message("usage: > interesting_add freq freqname freqgroup; "\
            "freq is integer or in rtl_power format, "\
            "name and group are strings to help you organize your freqs")

def cmd_interesting_add(grfstate, args):
    """Add an interesting frequency to this node's set"""

    system_mods = grfstate.system_mods

    if not args:
        cmd_interesting_add_usage()
        return

    try:
        freq, name, freqgroup = args.split()
    except ValueError:
        cmd_interesting_add_usage()
        return

    freq = gammarf_util.str_to_hz(freq)
    if not freq:
        cmd_interesting_add_usage()
        return

    if system_mods['connector'].interesting_add(freq, name, freqgroup):
        gammarf_util.console_message("interesting freqs updated")
    else:
        gammarf_util.console_message("error updating interesting freqs")

def cmd_interesting_del_usage():
    gammarf_util.console_message(
            "usage: > interesting_del freq; "\
            "freq is an integer or in rtl_power format")

def cmd_interesting_del(grfstate, args):
    """Delete an interesting frequency from this node's set"""

    system_mods = grfstate.system_mods

    if not args:
        cmd_interesting_del_usage()
        return

    freq = gammarf_util.str_to_hz(args)
    if not freq:
        cmd_interesting_del_usage()
        return

    if system_mods['connector'].interesting_del(freq):
        return True

    return

def cmd_location(grfstate, args):
    """Show station location and GPS status"""

    system_mods = grfstate.system_mods
    system_mods['location'].info()

    return

def cmd_message_usage():
    gammarf_util.console_message("usage: > message target_station message")

def cmd_message(grfstate, args):
    """Send a message to another station: > message target the message"""

    config = grfstate.config
    system_mods = grfstate.system_mods

    if not args:
        cmd_message_usage()
        return

    try:
        target, message = args.split(" ", 1)
    except ValueError:
        cmd_message_usage()
        return

    req = {'request': REQ_MESSAGE, 'target': target, 'message': message}
    resp = system_mods['connector'].sendcmd(req)
    if resp['reply'] == 'ok':
        gammarf_util.console_message("message sent")
    else:
        gammarf_util.console_message("error sending message")

def cmd_mods(grfstate, args):
    """Show available modules"""

    config = grfstate.config
    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods

    modules = loadedmods
    for module in modules:
        gammarf_util.console_message(module, showdt=False)
        gammarf_util.console_message('=' * len(module), showdt=False)
        gammarf_util.console_message(loadedmods[module].__doc__, showdt=False)
        gammarf_util.console_message('', showdt=False)

def cmd_now(grfstate, args):
    """Show the current time (UTC)"""

    gammarf_util.console_message(datetime.datetime.now())

def cmd_pwr_usage():
    gammarf_util.console_message("usage: > pwr freq")

def cmd_pwr(grfstate, args):
    """Show the power at the specified frequency"""

    system_mods = grfstate.system_mods

    if not args:
        cmd_pwr_usage()
        return

    freq = gammarf_util.str_to_hz(args.split()[0])
    if not freq:
        cmd_pwr_usage()
        return

    pwr = system_mods['spectrum'].pwr(freq)
    if pwr:
        gammarf_util.console_message(pwr)

def cmd_quit(grfstate):
    """Quit"""

    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods

    # shut down system modules last
    for module in loadedmods:
        if module not in SYSTEM_MODS:
            loadedmods[module].shutdown()

    for module in SYSTEM_MODS:
        system_mods[module].shutdown()

    sys.exit()

def cmd_run(grfstate, args):
    """Run a module on a device: > run module devid [params]"""

    config = grfstate.config
    loadedmods = grfstate.loadedmods
    system_mods = grfstate.system_mods
    devmod = system_mods['devices']

    if not args:
        gammarf_util.console_message("must specify which module to run")
        return

    parsed = args.split(None, 2)
    if not parsed:
        gammarf_util.console_message("type 'mods' for command usage")
        return

    module = parsed[0]
    if (module not in loadedmods) or (module in system_mods):
        gammarf_util.console_message("invalid module: {}".format(module))
        return

    try:
        devid = int(parsed[1])
    except (ValueError, IndexError):
        gammarf_util.console_message(
                "must specify a device number as the first argument")
        return

    cmdline = parsed[2] if len(parsed) > 2 else None

    pseudo = False
    if loadedmods[module].ispseudo():
        pseudo = True

        if devid < PSEUDO_DEVNUM_BASE:
            gammarf_util.console_message("pseudo modules must use devid >= {}"
                    .format(PSEUDO_DEVNUM_BASE))
            return

        devtype = 'pseudo'

    else:
        if not devmod.isdev(devid):
            gammarf_util.console_message("not a device: {}".format(devid))
            return

        if not devmod.usable(devid):
            gammarf_util.console_message("device {} not usable")
            return

        devtype = devmod.get_devtype(devid)

        if not loadedmods[module].isproxy():
            if not devtype in loadedmods[module].devices():
                gammarf_util.console_message("device type {} not supported by module"
                        .format(devtype))
                return

    if devmod.occupied(devid):
        gammarf_util.console_message("cannot run module: device {} occupied"
                .format(devid))
        return

    if devtype == 'hackrf':
        if not devmod.hackrf():
            gammarf_util.console_message("no hackrf installed")
            return

        devid = devmod.next_virtualdev()
        if devid:
            if loadedmods[module].run(grfstate, devid, cmdline):
                devmod.occupy(devid, module, cmdline, pseudo)
    else:
        if loadedmods[module].run(grfstate, devid, cmdline):
            devmod.occupy(devid, module, cmdline, pseudo)

def cmd_settings_usage():
    gammarf_util.console_message("usage: > settings module [setting]")

def cmd_settings(grfstate, args):
    """Show / toggle a module's settings: > settings module [setting]"""

    config = grfstate.config
    loadedmods = grfstate.loadedmods

    if not args:
        cmd_settings_usage()
        return

    parsed = args.split(None)
    if len(parsed) > 3:
        cmd_settings_usage()
        return

    module = parsed[0]
    if module not in loadedmods:
        gammarf_util.console_message("invalid module: {}".format(module))
        return

    if len(parsed) == 1:  # show
        loadedmods[module].setting(None)
    else: # toggle
        if len(parsed) == 2:  # boolean arg
            result = loadedmods[module].setting(parsed[1])
            return
        else:
            if len(parsed) == 3:
                result = loadedmods[module].setting(parsed[1], parsed[2])
                return

        if result == None:
            gammarf_util.console_message(
                    "module {} has no toggleable settings"
                    .format(module))
            return

def cmd_stations(grfstate, args):
    """Show stations associated with the cluster"""

    if not grfstate.system_mods['connector'].stations_pretty():
        gammarf_util.console_message("error getting station information from server")
    return


class GrfCompleter(Completer):
    def __init__(self, grfstate):
        self.command_list = list(grfstate.commands)
        self.loadedmods = grfstate.loadedmods
        self.system_mods = grfstate.system_mods
        self.devmod = self.system_mods['devices']

    def get_completions(self, document, complete_event):
        if not document.is_cursor_at_the_end_of_line:
            yield Completion('')
            return

        line = document.current_line
        components = line.split(None)
        num_words = len(components)
        if num_words == 0:
            for command in self.command_list:
                yield Completion(command)

        elif num_words == 1:
            current = document.get_word_before_cursor()
            if current:  # still typing the first word
                if current in self.command_list:
                    return
                else:
                    for command in self.command_list:
                        if command.startswith(current):
                            yield Completion(command[len(current):],
                                    display=command)

            else:  # finished the first word, want options for the second
                if components[0] == 'run':
                    for mod in self.loadedmods:
                        yield Completion(mod)

                elif components[0] == 'stop':
                    for dev in self.devmod.alldevs().keys():
                        if self.devmod.occupied(dev):
                            if not current:
                                yield Completion(str(dev))

                elif components[0] == 'reserve':
                    for devid in range(self.devmod.get_numdevs()):
                        if not self.devmod.occupied(devid):
                            if not self.devmod.reserved(devid):
                                yield Completion(str(devid))

                elif components[0] == 'unreserve':
                    for devid in range(self.devmod.get_numdevs()):
                        if self.devmod.reserved(devid):
                            yield Completion(str(devid))

                elif components[0] == 'settings':
                    if current in self.loadedmods:
                        return
                    else:
                        for mod in self.loadedmods:
                            if mod.startswith(current):
                                yield Completion(mod[len(current):],
                                        display=mod)

                elif components[0] == 'message':
                    stations = self.system_mods['connector'].stations_raw()
                    if not stations:
                        return
                    for station in stations:
                        yield Completion(station)

        elif num_words == 2:
            current = document.get_word_before_cursor()
            if current:
                if components[0] == 'run':
                    if current in self.loadedmods:
                        return
                    else:
                        for mod in self.loadedmods:
                            if mod.startswith(current):
                                yield Completion(mod[len(current):],
                                        display = mod)

                elif components[0] == 'stop':
                    for dev in self.devmod.alldevs().keys():
                        if self.devmod.occupied(dev):
                            if not current:
                                yield Completion(str(dev))

                elif components[0] == 'settings':
                    if current in self.loadedmods:
                        return
                    else:
                        for mod in self.loadedmods:
                            if mod.startswith(current):
                                yield Completion(mod[len(current):],
                                        display = mod)

                elif components[0] == 'message':
                    stations = self.system_mods['connector'].stations_raw()
                    if not stations:
                        return
                    for station in stations:
                        if station.startswith(current):
                            yield Completion(station[len(current):],
                                    display = station)

            else:  # finished second word, want options for the third
                if components[0] == 'run':
                    for devid in range(self.devmod.get_numdevs()):
                        if self.devmod.reserved(devid):
                            continue
                        if self.devmod.occupied(devid):
                            continue
                        yield Completion(str(devid))

        elif num_words == 3:
            current = document.get_word_before_cursor()
            if current:
                if components[0] == 'settings':
                    module = components[1]
                    if not module in self.loadedmods:
                        return

                    settings = self.loadedmods[module].setting(0)
                    if settings:
                        for setting in settings:
                            if setting.startswith(current):
                                yield Completion(setting[len(current):], display=setting)

            else:  # finished third word, want options for the fourth (n/a)
                pass

if __name__ == '__main__':
    main()
