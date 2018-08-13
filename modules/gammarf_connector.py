#!/usr/bin/env python3
# connector module
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
import json
import time
import threading
import urllib3
import zmq
import queue
from hashlib import md5
from multiprocessing import Pipe
from uuid import uuid4

import gammarf_util
from gammarf_base import GrfModuleBase

CMD_POLL_TIMEOUT = 1500  # ms
CMD_ATTEMPTS = 2
CMD_ATTEMPT_FAIL_SLEEP = 2
HEARTBEAT_INT = 10
LOOP_SLEEP = 0.5
MOD_NAME = "connector"
QUEUE_MAX = int(50)  # leave this alone
RECONNECT_ATTEMPT_WAIT = 5  # s
REQ_HEARTBEAT = 0
REQ_INTERESTING_ADD = 11
REQ_INTERESTING_DEL = 12
REQ_INTERESTING_GET = 1
ZMQ_HWM = 0


def start(config, system_mods):
    return GrfModuleConnector(config, system_mods)


class ConnectorWorker(threading.Thread):
    def __init__(self, opts, system_mods):
        self.stoprequest = threading.Event()
        threading.Thread.__init__(self)

        self.stationid = opts['stationid']
        self.station_pass = opts['station_pass']
        self.server_host = opts['server_host']
        self.dat_port = opts['dat_port']
        self.cmd_port = opts['cmd_port']

        self.datq = queue.Queue(maxsize=QUEUE_MAX)

        self.gps_worker = system_mods['location']
        self.devmod = system_mods['devices']

        self.cmdlock = threading.Lock()

    def run(self):
        self.connected = False
        self.connect_message = None
        self.poller = None
        announce_reconnects = True
        connect_attempted = False
        lost_connection = False
        since_heartbeat = None

        context = zmq.Context()

        while not self.stoprequest.isSet():
            self.loc = self.gps_worker.get_current()
            if not self.loc:
                gammarf_util.console_message("no location data")

            if self.connected:
                try_connect = False

            else:
                if connect_attempted:
                    time.sleep(RECONNECT_ATTEMPT_WAIT)
                    try_connect = False
                    lost_connection = True

                    elapsed = datetime.datetime.utcnow() - connect_attempted
                    if elapsed.total_seconds() > RECONNECT_ATTEMPT_WAIT:
                        try_connect = True

                        if announce_reconnects:
                            if self.connect_message:
                                gammarf_util.console_message(
                                        "attempting to reconnect: {}"
                                        .format(self.connect_message),
                                        MOD_NAME)
                                self.connect_message = None
                            else:
                                gammarf_util.console_message(
                                        "attempting to reconnect to server",
                                        MOD_NAME)

                        try:
                            self.cmdsock.close()
                            self.datsock.close()
                            self.poller.unregister(self.cmdsock)
                        except:
                            pass

                else:
                    gammarf_util.console_message("connecting to server",
                            MOD_NAME)
                    try_connect = True

                if try_connect:
                    connect_attempted = datetime.datetime.utcnow()

                    try:
                        self.datsock = context.socket(zmq.PUSH)
                        self.datsock.setsockopt(zmq.LINGER, 0)
                        self.datsock.set_hwm(ZMQ_HWM)
                        self.datsock.connect("tcp://{}:{}"
                                .format(self.server_host, self.dat_port))

                        self.cmdsock = context.socket(zmq.REQ)
                        self.cmdsock.setsockopt_string(zmq.IDENTITY,
                                self.stationid)
                        self.cmdsock.setsockopt(zmq.LINGER, 0)
                        self.cmdsock.set_hwm(ZMQ_HWM)
                        self.cmdsock.connect("tcp://{}:{}"
                                .format(self.server_host, self.cmd_port))

                        self.poller = zmq.Poller()
                        self.poller.register(self.cmdsock, zmq.POLLIN)
                    except Exception as e:
                        self.connect_message = "error connecting: {}".format(e)
                        self.connected = False
                        try_connect = False

            if since_heartbeat:
                elapsed = datetime.datetime.utcnow() - since_heartbeat
                if elapsed.total_seconds() >= HEARTBEAT_INT:
                    ready_for_heartbeat = True
                else:
                    ready_for_heartbeat = False
            else:
                ready_for_heartbeat = False

            if self.loc and (try_connect or ready_for_heartbeat):
                data = {}
                data['request'] = REQ_HEARTBEAT
                data['running'] = json.dumps([
                        ["{}".format(job[0]), "{}".format(job[1] if job[1]
                            else "noargs"), "{}".format(job[2])]
                        for job in self.devmod.running()\
                                if job != self.devmod.get_hackrf_job()])
                data['gpsstat'] = self.gps_worker.get_status()

                data['dt'] = int(time.time())
                data['rand'] = str(uuid4())[:8]
                m = md5()
                m.update((self.station_pass + data['rand'] + str(data['dt']))
                        .encode('utf-8'))
                data['sign'] = m.hexdigest()[:12]

                resp = self.sendcmd(data)
                try:
                    reply = resp['reply']
                except Exception as e:
                    self.connected = False
                else:
                    if reply == 'ok':
                        self.connected = True
                        since_heartbeat = datetime.datetime.utcnow()

                        if lost_connection:
                            if announce_reconnects:
                                gammarf_util.console_message(
                                        "connection reestablished",
                                        MOD_NAME)
                            lost_connection = False

                        if 'messages' in resp:
                            messages = resp['messages']
                            while messages:
                                ts = messages.pop(0)
                                frm = messages.pop(0)
                                msg = messages.pop(0)
                                gammarf_util.console_message(
                                        "message from {} @ {}: {}"
                                        .format(frm, ts, msg),
                                        MOD_NAME)

                    else:
                        self.connected = False

                        if reply == 'unauthorized':
                            self.connect_message = "station unauthorized"

                        elif reply == 'invalid_station':
                            self.connect_message = "invalid station"

            time.sleep(LOOP_SLEEP)

    def senddat(self, data):
        data['stationid'] = self.stationid
        data['dt'] = int(time.time())
        data.update(self.loc)
        data['rand'] = str(uuid4())[:8]
        m = md5()
        m.update((self.station_pass + data['rand'] + str(data['dt']))
                .encode('utf-8'))
        data['sign'] = m.hexdigest()[:12]

        self.datq.put(data)

        if not self.connected:
            return

        while not self.datq.empty():
            try:
                self.datsock.send_string(json.dumps(self.datq.get()), zmq.NOBLOCK)
            except Exception as e:
                return

    def sendcmd(self, data):
        with self.cmdlock:
            if not self.connected and data['request'] != REQ_HEARTBEAT:
                return {'reply': 'error', 'error': 'not_connected'}

            data['stationid'] = self.stationid
            data.update(self.loc)
            data['dt'] = int(time.time())
            data['rand'] = str(uuid4())[:8]
            m = md5()
            m.update((self.station_pass + data['rand'] + str(data['dt']))
                    .encode('utf-8'))
            data['sign'] = m.hexdigest()[:12]

            for i in range(CMD_ATTEMPTS):
                try:
                    self.cmdsock.send_string(json.dumps(data), zmq.NOBLOCK)
                    break

                except Exception as e:
                    if i == CMD_ATTEMPTS - 1:
                        self.connected = False
                        self.connect_message = "error sending to command socket: "\
                                "{}".format(e)

                        return {'reply': 'error', 'error': 'txerror'}

                    time.sleep(CMD_ATTEMPT_FAIL_SLEEP)
                    continue

            for i in range(CMD_ATTEMPTS):
                l = dict(self.poller.poll(CMD_POLL_TIMEOUT))
                if l.get(self.cmdsock) == zmq.POLLIN:
                    try:
                        resp = json.loads(self.cmdsock.recv_string())
                        return resp

                    except Exception as e:
                        if i == CMD_ATTEMPTS - 1:
                            self.connected = False
                            self.connect_message = "error receiving from "\
                                    "command socket: {}".format(e)

                            return {'reply': 'error', 'error': 'rxerror'}

                else:
                    if i == CMD_ATTEMPTS - 1:
                        self.connected = False
                        return {'reply': 'error', 'error': 'noresp'}

                    time.sleep(CMD_ATTEMPT_FAIL_SLEEP)
                    continue

    def join(self, timeout=None):
        self.stoprequest.set()
        super(ConnectorWorker, self).join(timeout)


class GrfModuleConnector(GrfModuleBase):
    def __init__(self, config, system_mods):
        if not 'connector' in config:
            raise Exception("No connector section defined in config")

        try:
            stationid = config['connector']['station_id']
        except KeyError:
            raise Exception("param 'stationid' not appropriately "\
                    "defined in config")

        try:
            station_pass = config['connector']['station_pass']
        except KeyError:
            raise Exception("param 'station_pass' not appropriately "\
                    "defined in config")

        try:
            server_host = config['connector']['server_host']
        except KeyError:
            raise Exception("param 'server_host' not appropriately "\
                    "defined in config")

        try:
            dat_port = config['connector']['data_port']
        except KeyError:
            raise Exception("param 'dat_port' not appropriately "\
                    "defined in config")
        dat_port = int(dat_port)

        try:
            cmd_port = config['connector']['cmd_port']
        except KeyError:
            raise Exception("param 'cmd_port' not appropriately "\
                    "defined in config")
        cmd_port = int(cmd_port)

        try:
            self.server_host = config['connector']['server_host']
        except KeyError:
            raise Exception("param 'server_host' not appropriately "\
                    "defined in config")

        try:
            self.server_web_port = config['connector']['server_web_port']
        except KeyError:
            raise Exception("param 'server_web_port' not appropriately "\
                    "defined in config")

        try:
            self.server_web_proto = config['connector']['server_web_proto']
        except KeyError:
            raise Exception("param 'server_web_proto' not appropriately "\
                    "defined in config")

        self.description = "connector module"
        self.settings = {}
        self.worker = None

        self.thread_timeout = 3

        self.server_url = self.server_web_proto + "://" \
                + self.server_host \
                + ":" + self.server_web_port

        opts = {'stationid': stationid,
                'station_pass': station_pass,
                'server_host': server_host,
                'dat_port': dat_port,
                'cmd_port': cmd_port}


        self.worker = ConnectorWorker(opts, system_mods)
        self.worker.daemon = True
        self.worker.start()

        gammarf_util.console_message("loaded", MOD_NAME)

    def interesting_add(self, freq, name, group):
        req = {'request': REQ_INTERESTING_ADD, 'name': name, 'freq': freq, 'group': group}
        resp = self.sendcmd(req)
        if resp['reply'] == 'ok':
            return True

    def interesting_del(self, freq):
        req = {'request': REQ_INTERESTING_DEL, 'freq': freq}
        resp = self.sendcmd(req)
        if resp['reply'] == 'ok':
            return True

    def interesting_raw(self):
        req = {'request': REQ_INTERESTING_GET}
        resp = self.sendcmd(req)
        if resp['reply'] == 'ok':
            interesting = resp['freqs'].split(None)
            out = []
            for freq, name, freqgroup in zip(interesting[0::3], interesting[1::3], interesting[2::3]):
                out.append( (int(freq), name, freqgroup) )
            return sorted(out, key=lambda tup: tup[0])

    def interesting_pretty(self):
        req = {'request': REQ_INTERESTING_GET}
        resp = self.sendcmd(req)
        if resp['reply'] == 'ok':
            interesting = resp['freqs'].split(None)
            out = []
            for freq, name, freqgroup in zip(interesting[0::3], interesting[1::3], interesting[2::3]):
                out.append( (int(freq), name, freqgroup) )

            out = sorted(out, key=lambda tup: tup[0])
            for freq, name, freqgroup in out:
                gammarf_util.console_message("{:11d} {} ({})".format(freq, name, freqgroup))
            return True
        return

    def senddat(self, data):
        self.worker.senddat(data)

    def sendcmd(self, data):
        return self.worker.sendcmd(data)

    def stations_pretty(self):
        url = self.server_url + "/util/locations"
        http = urllib3.PoolManager()

        try:
            response = http.request('GET', url)
        except Exception:
            return

        if response.status != 200:
            return

        gammarf_util.console_message()

        data = json.loads(response.data.decode('utf-8'))
        for d in data:
            active  = d[3]
            if active:
                stnstr = "{:16s}| {:6.3f} {:6.3f}".format(d[0], d[1], d[2])
                gammarf_util.console_message(stnstr)
                gammarf_util.console_message('-' * len(stnstr))

                mods = json.loads(d[4])
                if mods:
                    modstrlen = 0
                    for m in mods:
                        modstr = "{} {} {}".format(m[0], m[1], m[2])
                        gammarf_util.console_message(modstr)

                        if len(modstr) > modstrlen:
                            modstrlen = len(modstr)
                    gammarf_util.console_message('=' * modstrlen)
                else:
                    gammarf_util.console_message('=' * len(stnstr))

            else:
                stnstr = "{:16s}| last seen at {:6.3f} {:6.3f}"\
                        .format(d[0], d[1], d[2])
                gammarf_util.console_message(stnstr)
                gammarf_util.console_message('='*len(stnstr))

            gammarf_util.console_message()

        return True

    def stations_raw(self):
        url = self.server_url + "/util/locations"
        http = urllib3.PoolManager()

        try:
            response = http.request('GET', url)
        except Exception:
            return

        if response.status != 200:
            return

        out = []
        data = json.loads(response.data.decode('utf-8'))
        for d in data:
            out.append(d[0])

        return out

    # overridden 
    def shutdown(self):
        gammarf_util.console_message("shutting down {}"
                .format(self.description))

        if self.worker:
            self.worker.join(self.thread_timeout)
