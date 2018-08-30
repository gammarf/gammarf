#!/usr/bin/env python3
# grf utilities
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
from time import gmtime, strftime


def console_message(message=None, module=None, showdt=True):
    line = ""

    if showdt:
        line += "[{}] ".format(gmt_pretty())

    if module:
        line += "[{}] ".format(module)

    if message:
        line += "{}".format(message)
    else:
        line += ""

    print(line)

def gmt_pretty():
    return strftime("%Y-%m-%d %H:%M:%S", gmtime())

def str_to_hz(strfreq):
    """Convert frequency in rtl_sdr format (103M) to Hz int (103000000)"""

    if not strfreq:
        return None

    try:
        if strfreq[len(strfreq)-1] == 'G':
            outfreq = int(float(strfreq[:len(strfreq)-1])*1e9)
        elif strfreq[len(strfreq)-1] == 'M':
            outfreq = int(float(strfreq[:len(strfreq)-1])*1e6)
        elif strfreq[len(strfreq)-1] == 'k':
            outfreq = int(float(strfreq[:len(strfreq)-1])*1e3)
        else:
            outfreq = int(strfreq)
    except Exception as e:
        return None

    return outfreq
