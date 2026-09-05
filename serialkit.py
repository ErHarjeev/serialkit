import argparse
import codecs
import json
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports

# The tool's own name and version, in one place: --version prints them,
# and the window title and the Ctrl+G header take the name from here
# rather than spelling it out again.
PROGRAM = "serialkit"
VERSION = "1.0.0"

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, colorchooser
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

# What the one widget subclass in the file inherits from. A class
# statement runs at import time, so a bare "ttk.Frame" base would fail
# the whole module - and with it the terminal front end, which needs no
# tkinter at all. Every other use of tk is inside a function, reached
# only behind TK_AVAILABLE.
GUI_FRAME = ttk.Frame if TK_AVAILABLE else object


# ============================================================
# Highlight rules
#
# pattern, foreground, background[, flags]
#
# Matching is case-insensitive unless a rule gives its own flags,
# so pass 0 for a rule that must respect case.
#
# You can add your own MobaXterm-style regex rules here.
# ============================================================

HIGHLIGHT_RULES = []


# Colour for what you type, once the device echoes it back.
# Set to None to leave typed text looking like everything else.
INPUT_COLOR = "#7fd1ff"

# The tool's own messages - banners, the Ctrl+G key list, transfer
# progress - are drawn italic and in this colour, so they cannot be
# mistaken for something the device said. Terminals that ignore the
# italic escape still show the colour.
NOTICE_COLOR = "#9aa0a6"


# How many rules the rule window offers
USER_RULE_COUNT = 12

# The active rule table. Profiles supply all rules now — there are no
# built-in rules that sit underneath.
ACTIVE_RULES = []


# ============================================================
# Profile: extended
#
# The MobaXterm-style set: log levels, error phrases, shell syntax,
# option flags, interface names, addresses, hex values, temperatures.
# ============================================================
EXTENDED_USER_RULES = [
    # 1  Red: errors, failures, false values.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:ERROR|FAIL(?:ED|URE)?)\b"
            r"|(?<![A-Za-z_&-])(?:"
            r"rejected|session (?:closed|disconnected)"
            r"|does not (?:match|exist)"
            r"|(?:bad|wrong|incorrect|improper|invalid|unsupported)"
            r"(?: (?:file|memory))? "
            r"(?:descriptor|alloc(?:ation)?|addr(?:ess)?|owner(?:ship)?"
            r"|arg(?:ument)?|param(?:eter)?|setting|length|filename)"
            r"|not properly|improperly"
            r"|(?:operation |connection |authentication |access |permission )?"
            r"(?:denied|disallowed|not allowed|refused|not permitted"
            r"|failure|failed)"
            r"|no [A-Za-z]+(?: [A-Za-z]+)? found"
            r"|invalid|unsupported|not supported|seg(?:mentation )?fault"
            r"|corrupt(?:ion|ed)?|overflow|underrun|not ok"
            r"|unimplemented|not implemented|errors?|crash(?:ed)?|core dump"
            r"|administratively down|\(ee\)|\(ni\)"
            r"|down"
            r")(?![A-Za-z_-])"
            r"|(?<=[=>\"':.,;(\[{]) *(?:false|no|ko) *(?=[\]=>\"':.,;)}])"
        ),
        "foreground": "#ff4444",
        "background": "#330000",
        "ignore_case": True,
    },

    # 2  Green: success, up, connected, true values.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:INFO|CONNECTED|UP)\b"
            r"|(?<![A-Za-z_&-])(?:"
            r"session opened|accepted|allowed|enabled|connected"
            r"|successfully|successful|succeeded|success"
            r")(?![A-Za-z_-])"
            r"|(?<=[=>\"':.,;(\[{]) *(?:true|yes|ok) *(?=[\]=>\"':.,;)}])"
            r"|(?<![A-Za-z_&-])(?:true|yes|ok|up|active)(?= {4})"
        ),
        "foreground": "#00ff88",
        "background": None,
        "ignore_case": True,
    },

    # 3  Yellow: warnings, stops, shell expansions.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:WARNING|WARN)\b"
            r"|(?<![A-Za-z_&-])(?:"
            r"unassigned|shutdown|discard(?:ed|ing)|warn(?:ing)?s?"
            r"|caught signal [0-9]+|cannot|could not|unable to"
            r"|(?:connection (?:to (?:remote host|[a-z0-9.]+) )?)?"
            r"(?:closed|terminated|stopped|not responding)"
            r"|exited|no more [A-Za-z]+ available|unexpected"
            r"|(?:command |binary |file )?not found"
            r"|out of (?:space|memory)|low (?:memory|disk)"
            r"|(?:user )?unknown(?: user)?|disabled|disconnected|deprecated"
            r"|disconnect(?:ion)?|attention|alerts?|exclamation"
            r"|\(ww\)|\(\?\?\)"
            r")(?![A-Za-z_-])"
            r"|\$(?:[A-Za-z_][A-Za-z_0-9]*|\{[^}]*\}|\([^)]*\)"
            r"|\[[^\]]*\]|[?@$])"
        ),
        "foreground": "#ffd700",
        "background": "#443300",
        "ignore_case": True,
    },

    # 4  Orange: disconnected.
    {
        "enabled": True,
        "pattern": r"\bDISCONNECTED\b",
        "foreground": "#ff8800",
        "background": "#331a00",
        "ignore_case": True,
    },

    # 5  Grey: DEBUG, timestamps.
    {
        "enabled": True,
        "pattern": (
            r"\bDEBUG\b"
            r"|\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"
        ),
        "foreground": "#888888",
        "background": None,
        "ignore_case": True,
    },

    # 6  Blue: IP addresses, escape sequences, bracketed counters,
    #    shell plumbing.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
            r"|\\(?:033|e)(?:\[[0-9;]*[A-Za-z]|\((?:0|B))"
            r"|\[[0-9.:,]+\]|/dev/null|\|\||&&"
        ),
        "foreground": "#00bfff",
        "background": None,
        "ignore_case": True,
    },

    # 7  Magenta: MAC addresses, shell keywords, interface names,
    #    temperature.
    {
        "enabled": True,
        "pattern": (
            r"(?<![0-9A-Za-z_&-])(?:"
            r"[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}"
            r"|localhost|null|none"
            r")(?![0-9A-Za-z_-])"
            r"|(?:^|(?<=[;|&])) *\(? *(?:for(?:each)?|while|done|if|then"
            r"|else|elif|fi|case|esac|endif|exit|eval|shift|read|continue"
            r"|return)(?![A-Za-z_-])"
            r"|(?<![A-Za-z_&-])(?:interface )?(?:Fa[0-9/]+|Gi[0-9/]+"
            r"|GigabitEthernet[0-9/.]+|FastEthernet[0-9/.]+|vlan[0-9]+"
            r"|Dot11Radio[0-9.]+|bvi[0-9]+)(?![A-Za-z_-])"
        ),
        "foreground": "#ff66ff",
        "background": None,
        "ignore_case": True,
    },

    # 8  Teal: hex values (0x prefix, \x escapes, hex dump columns).
    {
        "enabled": True,
        "pattern": (
            r"\b0[xX][0-9A-Fa-f]+\b"
            r"|\\x[0-9A-Fa-f]{2}"
            r"|(?<![0-9A-Za-z])(?=[0-9A-Fa-f ]*[A-Fa-f])"
            r"(?:[0-9A-Fa-f]{2} ){3,}[0-9A-Fa-f]{2}(?![0-9A-Za-z])"
        ),
        "foreground": "#00d7c0",
        "background": None,
        "ignore_case": False,
    },

    # 9  Cyan: CLI options, progress notes, builtins, config keywords.
    {
        "enabled": True,
        "pattern": (
            r"(?<=[ (\"'\[])--?[A-Za-z0-9][A-Za-z0-9_-]*"
            r"(?=[ =,.)\"'\]]|$)"
            r"|(?<![A-Za-z_&-])(?:"
            r"last (?:failed )?login:|launching|checking|loading|creating"
            r"|building|important|booting|starting|notice|informational"
            r"|information|info|note|\(ii\)|\(!!\)"
            r")(?![A-Za-z_-])"
            r"|(?<![A-Za-z_&-])(?:"
            r"setenv|export|unset|builtin|shopt|unalias|echo|printf|alias"
            r"|function|bindkey|setopt|unsetopt|user access verification"
            r"|switchport|logging event|no ip address|service-policy"
            r"|vlan-range|spanning-tree|access-list|description"
            r"|running-config|startup-config|radius-server|class-map"
            r"|policy-map|media-type|ip address"
            r")(?![A-Za-z_-])"
        ),
        "foreground": "#00e5ff",
        "background": None,
        "ignore_case": True,
    },

    # 10 Orange: dBm values.
    {
        "enabled": True,
        "pattern": r"[-+]?\d+(?:\.\d+)?\s*dBm\b",
        "foreground": "#ffaa00",
        "background": None,
        "ignore_case": True,
    },

    # 11 Magenta: temperature readings (case-sensitive).
    {
        "enabled": True,
        "pattern": (
            r"(?<![0-9A-Fa-fxX.])[-+]?\d+(?:\.\d+)?\s*(?:°C|C)\b"
        ),
        "foreground": "#ff66ff",
        "background": None,
        "ignore_case": False,
    },

    # 12 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },
]


# ============================================================
# Profile: simple
#
# Fewer rules, each one narrow — for logs where the extended set
# would light up too much. Includes former built-in log-level words.
# ============================================================
SIMPLE_USER_RULES = [
    # 1  Red: hard errors and log-level ERROR/FAIL.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:ERROR|FAIL(?:ED|URE)?|ERR|ERRNO"
            r"|EXCEPTION|ASSERT(?:ION)?|PANIC|ABORT|DOWN)\b"
        ),
        "foreground": "#ff4444",
        "background": "#330000",
        "ignore_case": True,
    },

    # 2  Green: success keywords, INFO, UP, CONNECTED.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:PASS(?:ED)?|OK|SUCCESS|DONE"
            r"|INFO|UP|CONNECTED)\b"
        ),
        "foreground": "#00ff88",
        "background": None,
        "ignore_case": True,
    },

    # 3  Yellow: warnings, timeouts, retries.
    {
        "enabled": True,
        "pattern": (
            r"\b(?:WARNING|WARN|TIMEOUT|RETRY|RETRIES"
            r"|BUSY|DROP(?:PED)?)\b"
        ),
        "foreground": "#ffd700",
        "background": "#443300",
        "ignore_case": True,
    },

    # 4  Orange: disconnected.
    {
        "enabled": True,
        "pattern": r"\bDISCONNECTED\b",
        "foreground": "#ff8800",
        "background": "#331a00",
        "ignore_case": True,
    },

    # 5  Grey: DEBUG, timestamps.
    {
        "enabled": True,
        "pattern": (
            r"\bDEBUG\b"
            r"|\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"
        ),
        "foreground": "#888888",
        "background": None,
        "ignore_case": True,
    },

    # 6  Magenta: RX/TX.
    {
        "enabled": True,
        "pattern": r"\b(?:RX|TX)\b",
        "foreground": "#ff66ff",
        "background": None,
        "ignore_case": False,
    },

    # 7  Blue: IP addresses.
    {
        "enabled": True,
        "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "foreground": "#00bfff",
        "background": None,
        "ignore_case": True,
    },

    # 8  Magenta: MAC addresses.
    {
        "enabled": True,
        "pattern": r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b",
        "foreground": "#ff66ff",
        "background": None,
        "ignore_case": True,
    },

    # 9  Teal: hex values (0x prefix, \x escapes).
    {
        "enabled": True,
        "pattern": (
            r"\b0[xX][0-9A-Fa-f]+\b"
            r"|\\x[0-9A-Fa-f]{2}"
        ),
        "foreground": "#00d7c0",
        "background": None,
        "ignore_case": False,
    },

    # 10 Yellow: quoted strings.
    {
        "enabled": True,
        "pattern": r'"[^"]*"',
        "foreground": "#ffd700",
        "background": None,
        "ignore_case": True,
    },

    # 11 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },

    # 12 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },
]


# ============================================================
# Profile: network
#
# Combined network + embedded/firmware: IPs, MACs, interfaces,
# hex dumps, registers, dBm, voltages, temperatures.
# ============================================================
NETWORK_USER_RULES = [
    # 1  Red: link/session failures, CRC/checksum, bus faults, log-level
    #    ERROR/FAIL.
    {
        "enabled": True,
        "pattern": (
            r"(?<!\[)\b(?:ERROR|ERR|FAIL(?:ED|URE)?)\b(?!\])"
            r"|(?<![A-Za-z_&-])(?:"
            r"link down|carrier lost|no carrier|CRC error|checksum"
            r"|(?:frame|packet|bit) error|collision|runts?|giants?"
            r"|drops?|(?:input|output) error|overrun|underrun"
            r"|timeout|unreachable|no route|(?:auth(?:entication)? )?"
            r"(?:failed|failure|denied)|(?:hard|soft) fault"
            r"|bus error|parity error|stack overflow|down"
            r")(?![A-Za-z_-])"
        ),
        "foreground": "#ff4444",
        "background": "#330000",
        "ignore_case": True,
    },

    # 2  Green: link up, negotiation, boot OK, INFO, UP, CONNECTED.
    #    INFO is skipped when inside brackets like [INFO].
    {
        "enabled": True,
        "pattern": (
            r"(?<!\[)\b(?:INFO)\b(?!\])"
            r"|\b(?:CONNECTED|UP)\b"
            r"|(?<![A-Za-z_&-])(?:"
            r"link up|carrier detect|negotiated|established|reachable"
            r"|associated|registered|ready|boot(?:ed)? ok|flash ok"
            r"|calibrat(?:ed|ion) (?:ok|done|complete)"
            r"|programmed|initialized|sync(?:ed|ronized)?"
            r")(?![A-Za-z_-])"
        ),
        "foreground": "#00ff88",
        "background": "#003300",
        "ignore_case": True,
    },

    # 3  Yellow: protocol transitions, retransmits, WARNING/WARN.
    #    WARN/WARNING skipped when inside brackets.
    {
        "enabled": True,
        "pattern": (
            r"(?<!\[)\b(?:WARNING|WARN)\b(?!\])"
            r"|(?<![A-Za-z_&-])(?:"
            r"retransmit|duplex mismatch|speed mismatch|flapping"
            r"|STP|spanning.tree|BPDU|topology change"
            r"|(?:over|under)voltage|brownout|low battery"
            r"|watchdog|reset|reboot(?:ing)?"
            r")(?![A-Za-z_-])"
        ),
        "foreground": "#ffd700",
        "background": "#443300",
        "ignore_case": True,
    },

    # 4  Orange: disconnected.
    {
        "enabled": True,
        "pattern": r"\bDISCONNECTED\b",
        "foreground": "#ff8800",
        "background": "#331a00",
        "ignore_case": True,
    },

    # 5  Grey: DEBUG, timestamps, sequence/frame counters.
    #    DEBUG skipped when inside brackets.
    #    Timestamp requires preceding space or start-of-line so it
    #    does not grab the tail of a MAC address like 00:80:E1:00:00:02.
    {
        "enabled": True,
        "pattern": (
            r"(?<!\[)\bDEBUG\b(?!\])"
            r"|(?:^|(?<=\s))\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"
            r"|(?<![A-Za-z])(?:seq|ack|frame|pkt)\s*[#=:]\s*\d+"
        ),
        "foreground": "#888888",
        "background": None,
        "ignore_case": True,
    },

    # 6  Blue: IP/CIDR addresses.
    {
        "enabled": True,
        "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b",
        "foreground": "#00bfff",
        "background": None,
        "ignore_case": True,
    },

    # 7  Magenta: MAC addresses, interface names, register addresses.
    {
        "enabled": True,
        "pattern": (
            r"(?<![0-9A-Za-z_&-])(?:"
            r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}"
            r"|(?:Gi|Fa|Eth|eth|Te|Po)[0-9/.:]+"
            r"|(?:GigabitEthernet|FastEthernet|TenGigE|Ethernet)"
            r"[0-9/.:]+"
            r"|[Vv]lan\s*[0-9]+"
            r"|(?:0x)?[0-9A-Fa-f]{4,8}(?=\s*[=:<])"
            r")(?![0-9A-Za-z_-])"
        ),
        "foreground": "#ff66ff",
        "background": None,
        "ignore_case": False,
    },

    # 8  Teal: hex values (0x prefix, \x escapes, hex dump columns).
    {
        "enabled": True,
        "pattern": (
            r"\b0[xX][0-9A-Fa-f]+\b"
            r"|\\x[0-9A-Fa-f]{2}"
            r"|(?<![0-9A-Za-z])(?=[0-9A-Fa-f ]*[A-Fa-f])"
            r"(?:[0-9A-Fa-f]{2} ){3,}[0-9A-Fa-f]{2}(?![0-9A-Za-z])"
        ),
        "foreground": "#00d7c0",
        "background": None,
        "ignore_case": False,
    },

    # 9  Cyan: dBm, voltage, current, frequency, temperature readings.
    {
        "enabled": True,
        "pattern": (
            r"[-+]?\d+(?:\.\d+)?\s*(?:dBm|[mk]?V|mA|MHz)\b"
            r"|(?<![0-9A-Fa-fxX.])[-+]?\d+(?:\.\d+)?\s*(?:°C|C)\b"
        ),
        "foreground": "#00e5ff",
        "background": None,
        "ignore_case": False,
    },

    # 10 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },

    # 11 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },

    # 12 (spare)
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    },
]


# ============================================================
# Profile: custom
#
# Empty slots — user fills from scratch.
# ============================================================
CUSTOM_USER_RULES = [
    {
        "enabled": True,
        "pattern": "",
        "foreground": "#ffffff",
        "background": None,
        "ignore_case": True,
    }
    for _ in range(USER_RULE_COUNT)
]


# All highlight rules live inside profiles now — no built-in base layer.
# "simple" is narrow log-level words; "extended" is the MobaXterm set
# with shell syntax, flags and interface names; "network" targets
# network + embedded/firmware output; "custom" starts empty.
RULE_PROFILES = {
    "simple": SIMPLE_USER_RULES,
    "extended": EXTENDED_USER_RULES,
    "network": NETWORK_USER_RULES,
    "custom": CUSTOM_USER_RULES,
}

DEFAULT_RULE_PROFILE = "extended"


def default_user_rules(profile=None):

    rules = RULE_PROFILES.get(profile or DEFAULT_RULE_PROFILE)

    if rules is None:
        rules = RULE_PROFILES[DEFAULT_RULE_PROFILE]

    return [dict(rule) for rule in rules][:USER_RULE_COUNT]


def profile_rules(profile, stored=None):
    """
    The rules naming a profile asks for.

    "custom" is the one profile with nothing of its own to give: its
    stock set is twelve empty slots, and the rules it stands for live
    only in the settings file. Naming it therefore means the stored
    set - rebuilding it from the name would throw away the very rules
    being asked for, and the loss is silent, since a stock profile
    rebuilds byte for byte and only custom does not.
    """

    if profile == "custom" and stored:
        return [dict(rule) for rule in stored][:USER_RULE_COUNT]

    return default_user_rules(profile)


def blank_user_rules():

    return [
        {
            "enabled": True,
            "pattern": "",
            "foreground": "#ffffff",
            "background": None,
            "ignore_case": True,
        }
        for _ in range(USER_RULE_COUNT)
    ]


def set_user_rules(rules):
    """Rebuild the active rule table from the rule window's entries."""

    global ACTIVE_RULES

    table = []

    for rule in rules or []:

        pattern = (rule.get("pattern") or "").strip()

        if not pattern or not rule.get("enabled", True):
            continue

        try:
            re.compile(pattern)
        except re.error:
            continue

        table.append(
            (
                pattern,
                rule.get("foreground") or "#ffffff",
                rule.get("background") or None,
                re.IGNORECASE if rule.get("ignore_case", True) else 0,
            )
        )

    ACTIVE_RULES = table

    return ACTIVE_RULES


# ============================================================
# Special keys, sent to the device as ANSI/VT sequences
#
# These are what a normal terminal emits, so shell history
# (arrow up/down) and line editing work on the device side.
# ============================================================

# Second character returned by msvcrt after a \x00 / \xe0 prefix
WINDOWS_SPECIAL_KEYS = {
    "H": "\x1b[A",      # Up
    "P": "\x1b[B",      # Down
    "M": "\x1b[C",      # Right
    "K": "\x1b[D",      # Left
    "G": "\x1b[H",      # Home
    "O": "\x1b[F",      # End
    "R": "\x1b[2~",     # Insert
    "S": "\x1b[3~",     # Delete
    "I": "\x1b[5~",     # Page Up
    "Q": "\x1b[6~",     # Page Down
}

# Tk keysym -> sequence, for the GUI front end
TK_SPECIAL_KEYS = {
    "Up": "\x1b[A",
    "Down": "\x1b[B",
    "Right": "\x1b[C",
    "Left": "\x1b[D",
    "Home": "\x1b[H",
    "End": "\x1b[F",
    "Insert": "\x1b[2~",
    "Delete": "\x1b[3~",
    "Prior": "\x1b[5~",
    "Next": "\x1b[6~",
    "Tab": "\t",
    "Escape": "\x1b",
}


# ============================================================
# Regex matching, shared by both front ends
# ============================================================

def find_matches(text):
    """
    Return non-overlapping (start, end, rule_index) tuples for text,
    longest match first when two rules start at the same offset.
    """

    matches = []

    for index, rule in enumerate(ACTIVE_RULES):

        pattern = rule[0]
        flags = rule[3] if len(rule) > 3 else re.IGNORECASE

        try:

            for match in re.finditer(pattern, text, flags):

                matches.append(
                    (
                        match.start(),
                        match.end(),
                        index
                    )
                )

        except re.error:
            pass

    matches.sort(
        key=lambda x: (
            x[0],
            -(x[1] - x[0])
        )
    )

    selected = []
    last_end = 0

    for start, end, rule_index in matches:

        if start >= last_end:

            selected.append(
                (start, end, rule_index)
            )

            last_end = end

    return selected


def open_port(port, baud):
    """
    Open a port 8N1.

    write_timeout matters: without it a write to a device that has
    stopped reading blocks the thread for good.
    """

    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.1,
        write_timeout=2.0
    )


def port_is_present(name):
    """Is this port still listed by the system?"""

    try:

        return any(
            item.device == name
            for item in serial.tools.list_ports.comports()
        )

    except Exception:
        return False


# ============================================================
# Line assembler
#
# Devices redraw the current line in place: a shell recalling a
# command from history sends CR, rewrites the line and erases the
# tail with CSI K. Treating CR as a line break turns every history
# step into a new line, so the current line is kept as a character
# buffer with a cursor and only LF ends it.
# ============================================================

CSI_PATTERN = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")


class LineAssembler:

    def __init__(self, keep_sgr=False, track_input=True):

        # When keep_sgr is set, the colour the device asked for is
        # recorded per character and survives in-place redraws.
        self.keep_sgr = keep_sgr

        # When track_input is set, characters the device echoes back
        # after we typed them are marked, so they can be drawn in
        # their own colour.
        self.track_input = track_input

        self.chars = []
        self.styles = []
        self.inputs = []
        self.sgr = ""
        self.col = 0

        # Characters we sent and expect to see echoed, with a deadline
        self.echo_queue = deque()

        # Set while rendering our own local echo
        self.force_input = False

        # Deadline while a device-side line redraw counts as input
        self.redraw_until = 0.0

        # Escape sequence split across two reads
        self.pending = ""

    def current(self):

        return "".join(self.chars)

    def snapshot(self):
        """Return (text, styles, inputs) for the open line."""

        return "".join(self.chars), list(self.styles), list(self.inputs)

    def reset(self):

        self.chars = []
        self.styles = []
        self.inputs = []
        self.sgr = ""
        self.col = 0
        self.pending = ""
        self.echo_queue.clear()
        self.redraw_until = 0.0

    def expect_echo(self, text, ttl=10.0):
        """Remember characters we just sent, so their echo can be marked."""

        if not self.track_input:
            return

        deadline = time.monotonic() + ttl

        for char in text:

            if char >= " " and char != "\x7f":
                self.echo_queue.append((char, deadline))

    def expect_redraw(self, ttl=2.0):
        """
        Called when we send a key that makes the device rewrite the line,
        such as Up for history. The device repaints prompt and command
        together, and none of it is an echo of characters we typed, so
        the redraw is compared against what is already on the line:
        characters that change are the recalled command and count as
        input, characters that stay the same are the prompt.
        """

        if self.track_input:
            self.redraw_until = time.monotonic() + ttl

    ECHO_LOOKAHEAD = 3

    def match_echo(self, char):
        """
        True when this character is the echo of one we sent.

        A short lookahead covers an echo that lost a character on the
        way back: without it the queue would stay stuck on the missing
        one and the rest of the line would lose its colour.
        """

        if not self.track_input:
            return False

        now = time.monotonic()

        while self.echo_queue and self.echo_queue[0][1] < now:
            self.echo_queue.popleft()

        for offset in range(min(self.ECHO_LOOKAHEAD, len(self.echo_queue))):

            if self.echo_queue[offset][0] == char:

                for _ in range(offset + 1):
                    self.echo_queue.popleft()

                return True

        return False

    def feed(self, text, as_input=False):
        """
        Consume a chunk and return the (text, styles, inputs) tuples of
        the lines it completed. Whatever is left is in snapshot().

        as_input marks the whole chunk as typed text, for local echo.
        """

        self.force_input = as_input and self.track_input

        completed = []

        data = self.pending + text
        self.pending = ""

        position = 0
        length = len(data)

        while position < length:

            char = data[position]

            if char == "\x1b":

                match = CSI_PATTERN.match(data, position)

                if match:
                    self.apply_csi(match.group(1), match.group(3))
                    position = match.end()
                    continue

                # Escapes that are not CSI (charset selects, OSC titles)
                if position + 1 < length and data[position + 1] == "]":

                    end = data.find("\x07", position)

                    if end == -1:
                        self.pending = data[position:]
                        break

                    position = end + 1
                    continue

                # Possibly an escape sequence cut in half by the read
                # boundary: hold it until the rest arrives.
                if length - position < 12:
                    self.pending = data[position:]
                    break

                position += 1
                continue

            if char == "\n":

                self.redraw_until = 0.0

                completed.append(self.snapshot())

                self.chars = []
                self.styles = []
                self.inputs = []
                self.col = 0

            elif char == "\r":
                self.col = 0

            elif char == "\x08":
                self.col = max(0, self.col - 1)

            elif char == "\x7f":

                # Erase the previous character when it is the last one,
                # otherwise just step back.
                self.col = max(0, self.col - 1)

                if self.col == len(self.chars) - 1:
                    self.chars.pop()
                    self.styles.pop()
                    self.inputs.pop()

            elif char == "\t":

                for _ in range(8 - (self.col % 8)):
                    self.write(" ")

            elif char < " ":
                pass

            else:
                self.write(char)

            position += 1

        self.force_input = False

        return completed

    def write(self, char):

        repaint = (
            self.col < len(self.chars)
            and self.chars[self.col] == char
        )

        if repaint and not self.force_input:

            # A device that repaints its line - bootloaders do this
            # after every keystroke - rewrites the characters that are
            # already there. Such a character keeps what it was, and
            # must not eat the echo expected for the character being
            # typed now.
            is_input = self.inputs[self.col]

        else:

            is_input = self.force_input or self.match_echo(char)

            if (
                not is_input
                and self.track_input
                and time.monotonic() < self.redraw_until
            ):
                is_input = True

        if self.col < len(self.chars):
            self.chars[self.col] = char
            self.styles[self.col] = self.sgr
            self.inputs[self.col] = is_input
        else:
            self.chars.append(char)
            self.styles.append(self.sgr)
            self.inputs.append(is_input)

        self.col += 1

    def apply_csi(self, params, final):

        if final == "m":
            self.apply_sgr(params)
            return

        numbers = []

        for part in params.split(";"):

            try:
                numbers.append(int(part))
            except ValueError:
                numbers.append(0)

        first = numbers[0] if numbers else 0
        count = max(1, first)

        # Erase in line
        if final == "K":

            if first == 0:
                del self.chars[self.col:]
                del self.styles[self.col:]
                del self.inputs[self.col:]

            elif first == 1:

                for index in range(min(self.col + 1, len(self.chars))):
                    self.chars[index] = " "
                    self.styles[index] = ""
                    self.inputs[index] = False

            elif first == 2:
                self.chars = []
                self.styles = []
                self.inputs = []
                self.col = 0

        elif final == "C":
            self.col += count

        elif final == "D":
            self.col = max(0, self.col - count)

        elif final == "G":
            self.col = max(0, count - 1)

        elif final == "P":
            del self.chars[self.col:self.col + count]
            del self.styles[self.col:self.col + count]
            del self.inputs[self.col:self.col + count]

        elif final == "@":
            self.chars[self.col:self.col] = [" "] * count
            self.styles[self.col:self.col] = [""] * count
            self.inputs[self.col:self.col] = [False] * count

        # Anything else (cursor save, screen erase) is dropped.

        if self.col > len(self.chars):

            padding = self.col - len(self.chars)

            self.chars.extend([" "] * padding)
            self.styles.extend([""] * padding)
            self.inputs.extend([False] * padding)

    def apply_sgr(self, params):
        """Track the device's own colour so it can be replayed."""

        if not self.keep_sgr:
            return

        params = params.strip()

        if params in ("", "0"):
            self.sgr = ""
            return

        if self.sgr:
            self.sgr = self.sgr + ";" + params
        else:
            self.sgr = params


# ============================================================
# SGR (device colour) helpers
# ============================================================

ANSI_BASE_COLORS = [
    "#000000", "#cd3131", "#0dbc79", "#e5e510",
    "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5"
]

ANSI_BRIGHT_COLORS = [
    "#666666", "#f14c4c", "#23d18b", "#f5f543",
    "#3b8eea", "#d670d6", "#29b8db", "#ffffff"
]


def style_runs(text, styles):
    """Split text into (sgr, chunk) runs of equal styling."""

    runs = []
    index = 0

    while index < len(text):

        style = styles[index] if index < len(styles) else ""

        end = index

        while end < len(text):

            current = styles[end] if end < len(styles) else ""

            if current != style:
                break

            end += 1

        runs.append((style, text[index:end]))

        index = end

    return runs


def ansi_256_color(number):

    if number < 8:
        return ANSI_BASE_COLORS[number]

    if number < 16:
        return ANSI_BRIGHT_COLORS[number - 8]

    if number < 232:

        number -= 16

        levels = [0, 95, 135, 175, 215, 255]

        r = levels[number // 36]
        g = levels[(number // 6) % 6]
        b = levels[number % 6]

        return f"#{r:02x}{g:02x}{b:02x}"

    level = 8 + (number - 232) * 10

    return f"#{level:02x}{level:02x}{level:02x}"


def sgr_to_colors(params):
    """Turn accumulated SGR parameters into (foreground, background)."""

    foreground = None
    background = None
    bold = False

    numbers = []

    for part in params.split(";"):

        try:
            numbers.append(int(part))
        except ValueError:
            numbers.append(0)

    index = 0

    while index < len(numbers):

        code = numbers[index]

        if code == 0:
            foreground = None
            background = None
            bold = False

        elif code == 1:
            bold = True

        elif code == 39:
            foreground = None

        elif code == 49:
            background = None

        elif 30 <= code <= 37:
            foreground = ANSI_BASE_COLORS[code - 30]

        elif 90 <= code <= 97:
            foreground = ANSI_BRIGHT_COLORS[code - 90]

        elif 40 <= code <= 47:
            background = ANSI_BASE_COLORS[code - 40]

        elif 100 <= code <= 107:
            background = ANSI_BRIGHT_COLORS[code - 100]

        elif code in (38, 48):

            mode = numbers[index + 1] if index + 1 < len(numbers) else 0

            if mode == 5 and index + 2 < len(numbers):

                color = ansi_256_color(numbers[index + 2])
                index += 2

            elif mode == 2 and index + 4 < len(numbers):

                r, g, b = numbers[index + 2:index + 5]
                color = f"#{r:02x}{g:02x}{b:02x}"
                index += 4

            else:
                index += 1
                color = None

            if color:

                if code == 38:
                    foreground = color
                else:
                    background = color

        index += 1

    # Bold on a base colour is conventionally drawn bright.
    if bold and foreground in ANSI_BASE_COLORS:
        foreground = ANSI_BRIGHT_COLORS[ANSI_BASE_COLORS.index(foreground)]

    return foreground, background


# ============================================================
# GUI front end
# ============================================================

# Box glyphs used by the toggles: same width either way, so a label
# does not shift when it is ticked.
BOX_EMPTY = "\u2610"
BOX_TICKED = "\u2611"


def check_button(parent, **options):
    """
    A toggle that is flat while it is off and filled with a tick while
    it is on.

    Tk's own indicator is out of the question: the clam theme, which the
    GUI uses for its dark palette, marks a ticked box with a cross, and
    the Windows indicator is a white square that stays white on a dark
    toolbar whether it is ticked or not. Dropping the indicator and
    carrying the box in the label leaves the state to a glyph plus a
    background, both of which follow the palette.
    """

    style = ttk.Style(parent)

    background = style.lookup("TFrame", "background")
    foreground = style.lookup("TLabel", "foreground")

    # A theme may name its colour instead of spelling it out, and a
    # named colour is a system one, which is never the dark palette.
    try:
        dark = sum(hex_to_rgb(background)) < 300
    except (ValueError, IndexError, AttributeError):
        dark = False

    label = options.pop("text", "")
    variable = options.get("variable")

    if background:
        options.setdefault("bg", background)
        options.setdefault("activebackground", background)

    if foreground:
        options.setdefault("fg", foreground)
        options.setdefault("activeforeground", foreground)

    # With no indicator, selectcolor is the background of the whole
    # widget while it is on.
    options.setdefault("selectcolor", "#2b4a6f" if dark else "#cfe3ff")

    options.setdefault("indicatoron", False)
    options.setdefault("relief", "flat")
    options.setdefault("offrelief", "flat")
    options.setdefault("overrelief", "flat")
    options.setdefault("highlightthickness", 0)
    options.setdefault("borderwidth", 1)
    options.setdefault("padx", 4)
    options.setdefault("pady", 1)
    options.setdefault("anchor", "w")

    widget = tk.Checkbutton(parent, **options)

    def repaint(*ignored):

        box = BOX_TICKED if variable.get() else BOX_EMPTY

        widget.configure(text=f"{box} {label}" if label else box)

    if variable is not None:

        repaint()
        variable.trace_add("write", repaint)

    elif label:
        widget.configure(text=label)

    return widget


class FlowFrame(GUI_FRAME):
    """
    Toolbar that wraps onto more rows when the window is too narrow.

    A single packed row is silently clipped when the window is snapped to
    a Windows tile, which hides whatever sits at the right-hand end.
    """

    def __init__(self, master, padx=3, pady=2, **kwargs):

        super().__init__(master, **kwargs)

        self.groups = []
        self.padx = padx
        self.pady = pady

        self.last_width = 0

        self.bind("<Configure>", self.on_configure)

    def group(self, label=None):
        """A set of widgets that should wrap together."""

        if label:
            frame = ttk.Labelframe(self, text=label, padding=(6, 2, 6, 4))
        else:
            frame = ttk.Frame(self)

        self.groups.append(frame)

        return frame

    def on_configure(self, event):

        # Re-laying out fires Configure again; only react to real changes
        if abs(event.width - self.last_width) < 4:
            return

        self.last_width = event.width

        self.reflow(event.width)

    def reflow(self, width):

        row = 0
        column = 0
        used = 0

        for frame in self.groups:

            needed = frame.winfo_reqwidth() + 2 * self.padx

            if column and used + needed > width:
                row += 1
                column = 0
                used = 0

            frame.grid(
                row=row,
                column=column,
                padx=self.padx,
                pady=self.pady,
                sticky="w"
            )

            used += needed
            column += 1


class SerialTerminal:
    def __init__(self, root, config_path=None):

        self.config_path = config_path or CONFIG_FILE
        self.config = load_config(self.config_path)

        set_user_rules(
            self.config.get("rules")
            or default_user_rules(self.config.get("rule_profile"))
        )

        self.root = root
        self.root.title(PROGRAM)
        self.root.geometry("1200x700")
        self.root.minsize(320, 240)

        self.serial = None
        self.reader_thread = None
        self.running = False

        self.rx_queue = queue.Queue()

        self.assembler = LineAssembler(keep_sgr=True)

        # Held while an XMODEM transfer owns the port
        self.pause_reader = threading.Event()

        # What the reader thread is working with, free of Tk variables
        self.active_port = None
        self.active_baud = None

        # The Reconnect checkbox, as a plain flag: only the main thread
        # may touch a Tk variable, and the waiting happens on the reader.
        self.reconnect_enabled = self.config["reconnect"]

        # Status text from the reader thread. Only the main thread may
        # touch Tk, so it is handed over rather than set directly.
        self.status_queue = queue.Queue()

        self.stop_requested = False

        # Cache of tags created for device SGR states
        self.sgr_tags = {}

        # True while the terminal holds an unterminated line.
        self.line_open = False

        self.create_styles()
        self.create_interface()
        self.create_tags()

        self.refresh_ports()

        self.root.after(30, self.process_queue)

    # ========================================================
    # UI
    # ========================================================

    def create_styles(self):
        self.root.configure(bg="#1e1e1e")

        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "TFrame",
            background="#1e1e1e"
        )

        style.configure(
            "TLabel",
            background="#1e1e1e",
            foreground="#dddddd"
        )

        # clam pads every button out to eleven characters, which leaves
        # Save and Clear as wide as Disconnect. Sizing to the text keeps
        # the toolbar on one row for longer.
        style.configure(
            "TButton",
            background="#333333",
            foreground="#ffffff",
            width=0,
            padding=(8, 3)
        )

        style.configure(
            "TCheckbutton",
            background="#1e1e1e",
            foreground="#dddddd"
        )

        style.map(
            "TCheckbutton",
            background=[("active", "#1e1e1e")],
            foreground=[("active", "#ffffff")]
        )

        # Toolbar groups are boxed and titled, so a button can be found
        # by what it does rather than by where it happens to sit.
        style.configure(
            "TLabelframe",
            background="#1e1e1e",
            bordercolor="#3c3c3c"
        )

        style.configure(
            "TLabelframe.Label",
            background="#1e1e1e",
            foreground="#8ab4f8"
        )

    def create_interface(self):

        # ----------------------------------------------------
        # Top controls, wrapping when the window is narrow
        # ----------------------------------------------------

        top = FlowFrame(self.root)
        top.pack(fill="x", padx=8, pady=(8, 4))

        # Port, baud and the link itself
        ports = top.group("Connection")

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            ports,
            textvariable=self.port_var,
            width=12,
            state="readonly"
        )
        self.port_combo.pack(side="left")

        ttk.Button(
            ports,
            text="Refresh",
            command=self.refresh_ports
        ).pack(side="left", padx=(5, 10))

        ttk.Label(ports, text="Baud:").pack(side="left")

        self.baud_var = tk.StringVar(value=str(self.config["baud"]))

        ttk.Combobox(
            ports,
            textvariable=self.baud_var,
            values=[
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
                "230400",
                "460800",
                "921600"
            ],
            width=10
        ).pack(side="left", padx=(5, 10))

        ttk.Button(
            ports,
            text="Connect",
            command=self.connect
        ).pack(side="left")

        ttk.Button(
            ports,
            text="Disconnect",
            command=self.disconnect
        ).pack(side="left", padx=(3, 6))

        self.reconnect_var = tk.BooleanVar(value=self.config["reconnect"])

        check_button(
            ports,
            text="Reconnect",
            variable=self.reconnect_var,
            command=self.toggle_reconnect
        ).pack(side="left")

        # Sending data out
        tools = top.group("Send")

        ttk.Button(
            tools,
            text="XMODEM...",
            command=self.open_xmodem
        ).pack(side="left")

        ttk.Button(
            tools,
            text="Buffers...",
            command=self.open_buffers
        ).pack(side="left", padx=(3, 6))

        self.local_echo_var = tk.BooleanVar(value=self.config["local_echo"])

        check_button(
            tools,
            text="Local echo",
            variable=self.local_echo_var
        ).pack(side="left")

        # Everything that decides how the text looks
        colors = top.group("Colours")

        self.mark_input_var = tk.BooleanVar(
            value=bool(self.config["input_color"])
        )

        check_button(
            colors,
            text="Typed text",
            variable=self.mark_input_var,
            command=self.toggle_mark_input
        ).pack(side="left")

        self.device_colors_var = tk.BooleanVar(
            value=self.config["device_colors"]
        )

        check_button(
            colors,
            text="Device ANSI",
            variable=self.device_colors_var,
            command=self.toggle_device_colors
        ).pack(side="left", padx=(6, 6))

        self.highlight_var = tk.BooleanVar(value=self.config["highlight"])

        check_button(
            colors,
            text="Regex",
            variable=self.highlight_var,
            command=self.toggle_highlight
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            colors,
            text="Highlight rules...",
            command=self.open_rules
        ).pack(side="left")

        # The log itself
        log = top.group("Log")

        self.timestamp_var = tk.BooleanVar(value=self.config["timestamp"])

        check_button(
            log,
            text="Timestamp",
            variable=self.timestamp_var
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            log,
            text="Clear",
            command=self.clear_terminal
        ).pack(side="left")

        ttk.Button(
            log,
            text="Save",
            command=self.save_output
        ).pack(side="left", padx=(3, 0))

        self.toolbar = top

        # ----------------------------------------------------
        # Terminal
        # ----------------------------------------------------

        terminal_frame = tk.Frame(
            self.root,
            bg="#000000"
        )
        terminal_frame.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=(0, 8)
        )

        scrollbar = tk.Scrollbar(
            terminal_frame
        )
        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.terminal = tk.Text(
            terminal_frame,
            bg="#050505",
            fg="#dddddd",
            insertbackground="#ffffff",
            selectbackground="#444444",
            font=("Consolas", 10),
            wrap="none",
            undo=False,
            yscrollcommand=scrollbar.set
        )

        self.terminal.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar.config(
            command=self.terminal.yview
        )

        # Keyboard input
        self.terminal.bind(
            "<Key>",
            self.key_pressed
        )

        # ----------------------------------------------------
        # Bottom status
        # ----------------------------------------------------

        self.status_var = tk.StringVar(
            value="Disconnected"
        )

        status = ttk.Label(
            self.root,
            textvariable=self.status_var
        )
        status.pack(
            fill="x",
            padx=8,
            pady=(0, 5)
        )

    # ========================================================
    # Syntax highlighting tags
    # ========================================================

    def create_tags(self):

        for index, rule in enumerate(ACTIVE_RULES):
            pattern, foreground, background = rule[:3]

            tag = f"rule_{index}"

            kwargs = {
                "foreground": foreground
            }

            if background:
                kwargs["background"] = background

            self.terminal.tag_configure(
                tag,
                **kwargs
            )

        # Created last, so it draws over the rule tags
        if self.config["input_color"]:

            self.terminal.tag_configure(
                "input_text",
                foreground=self.config["input_color"]
            )

        # The tool's own messages. Italic and dimmed whatever the colour
        # toggles say, so a banner or an error is never taken for
        # something the device said.
        self.terminal.tag_configure(
            "notice",
            foreground=NOTICE_COLOR,
            font=("Consolas", 10, "italic")
        )

        self.terminal.tag_raise("notice")

    # ========================================================
    # COM ports
    # ========================================================

    def refresh_ports(self):

        ports = [
            port.device
            for port in serial.tools.list_ports.comports()
        ]

        self.port_combo["values"] = ports

        if ports and not self.port_var.get():

            remembered = self.config.get("port")

            if remembered in ports:
                self.port_var.set(remembered)
            else:
                self.port_var.set(ports[0])

    # ========================================================
    # Connect
    # ========================================================

    def connect(self):

        if self.serial and self.serial.is_open:
            return

        port = self.port_var.get()

        if not port:
            messagebox.showerror(
                "Serial",
                "Select a COM port."
            )
            return

        try:
            baud = int(self.baud_var.get())

            self.serial = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
                write_timeout=2.0
            )

            # Plain copies: the reader thread must not touch Tk
            # variables, which belong to the main thread.
            self.active_port = port
            self.active_baud = baud

            self.running = True

            self.reader_thread = threading.Thread(
                target=self.read_serial,
                daemon=True
            )

            self.reader_thread.start()

            self.status_var.set(
                f"Connected: {port} @ {baud} 8N1"
            )

            self.notice(f"--- Connected to {port} @ {baud} 8N1 ---")

        except Exception as e:

            messagebox.showerror(
                "Connection error",
                str(e)
            )

    # ========================================================
    # Disconnect
    # ========================================================

    def disconnect(self):

        self.running = False

        where = ""

        port, self.serial = self.serial, None

        if port:

            # Read them off the port before it goes away
            try:
                where = f" from {port.port} @ {port.baudrate} 8N1"
            except Exception:
                pass

            # A removed USB device can leave close() blocking behind a
            # pending read, which would freeze the window.
            def shut():

                try:
                    port.close()
                except Exception:
                    pass

            threading.Thread(target=shut, daemon=True).start()

        self.status_var.set(f"Disconnected{where}")

    # ========================================================
    # Serial reader
    # ========================================================

    def drop_port(self):
        """Let go of a dead handle without blocking the reader."""

        port, self.serial = self.serial, None

        if port is None:
            return

        def shut():

            try:
                port.close()
            except Exception:
                pass

        threading.Thread(target=shut, daemon=True).start()

    def wait_for_port(self):
        """Poll until the port opens again, as after a power cycle."""

        name = self.active_port
        baud = self.active_baud

        if not name:
            return False

        while self.running and self.reconnect_enabled:

            if self.pause_reader.is_set():
                time.sleep(0.05)
                continue

            if port_is_present(name):

                try:

                    self.serial = open_port(name, baud)

                    self.rx_queue.put((
                        "notice",
                        f"[reconnected to {name} @ {baud} 8N1]"
                    ))

                    self.status_queue.put(f"Connected: {name} @ {baud} 8N1")

                    return True

                except Exception:
                    pass

            self.status_queue.put(f"Waiting for {name}...")

            time.sleep(0.25)

        if self.running:

            self.rx_queue.put(("notice", f"[stopped waiting for {name}]"))
            self.status_queue.put("Disconnected")
            self.stop_requested = True

        return False

    def read_serial(self):

        # Incremental decoder so a multi-byte UTF-8 character split
        # across two reads is not mangled.
        decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )

        while self.running:

            try:

                if not self.serial or not self.serial.is_open:

                    if not self.wait_for_port():
                        break

                # An XMODEM transfer needs the port to itself
                if self.pause_reader.is_set():
                    time.sleep(0.05)
                    continue

                data = self.serial.read(
                    self.serial.in_waiting or 1
                )

                if not data:
                    continue

                text = decoder.decode(data)

                if text:
                    self.rx_queue.put(text)

            except Exception as e:

                if not self.running:
                    break

                self.rx_queue.put(("notice", f"[Serial error: {e}]"))

                if not self.reconnect_enabled:

                    self.rx_queue.put(("notice", "[port lost - disconnected]"))
                    self.stop_requested = True
                    break

                self.rx_queue.put((
                    "notice",
                    f"[{self.active_port} lost - waiting for it to "
                    f"come back. Disconnect stops waiting.]"
                ))

                self.drop_port()

                if not self.wait_for_port():
                    break

                decoder = codecs.getincrementaldecoder("utf-8")(
                    errors="replace"
                )

                break

    # ========================================================
    # Process incoming data
    # ========================================================

    def process_queue(self):

        try:

            while True:

                item = self.rx_queue.get_nowait()

                if isinstance(item, tuple):
                    self.notice(item[1])
                else:
                    self.display_text(item)

        except queue.Empty:
            pass

        try:

            while True:
                self.status_var.set(self.status_queue.get_nowait())

        except queue.Empty:
            pass

        if getattr(self, "stop_requested", False):

            self.stop_requested = False
            self.disconnect()

        self.root.after(
            30,
            self.process_queue
        )

    # ========================================================
    # Regex highlighting engine
    # ========================================================

    def toggle_mark_input(self):

        self.assembler.track_input = self.mark_input_var.get()

        if not self.assembler.track_input:
            self.assembler.echo_queue.clear()

    def toggle_device_colors(self):

        self.assembler.keep_sgr = self.device_colors_var.get()

        if not self.assembler.keep_sgr:
            self.assembler.sgr = ""

    def display_text(self, text, as_input=False):
        """
        Render incoming data as it arrives.

        The open line is repainted from the assembler on every chunk, so
        echoed keystrokes appear without waiting for a newline, in-place
        redraws (history recall) overwrite instead of stacking up, and a
        rule matches as soon as its word is complete.
        """

        for line, styles, inputs in self.assembler.feed(text, as_input):

            self.set_open_line(line, styles, inputs)

            self.terminal.insert("end", "\n")

            self.line_open = False

        line, styles, inputs = self.assembler.snapshot()

        self.set_open_line(line, styles, inputs, self.assembler.col)

        self.terminal.see("end")

    def notice(self, text):
        """
        One of the tool's own messages: a banner, an error, a transfer
        note. It goes on its own line, in the notice tag alone, so none
        of the colour toggles reach it.

        A line still being drawn is taken off the screen first and put
        back underneath, the way the CLI repaints it.
        """

        open_line = None

        if self.line_open:

            open_line = self.assembler.snapshot()

            self.terminal.delete("line_start", "end-1c")
            self.line_open = False

        for chunk in text.strip("\n").split("\n"):

            start = self.terminal.index("end-1c")

            self.terminal.insert("end", chunk + "\n")

            self.terminal.tag_add("notice", start, "end-1c")

        if open_line is not None:

            line, styles, inputs = open_line
            self.set_open_line(line, styles, inputs, self.assembler.col)

        self.terminal.see("end")

    def set_open_line(self, line, styles=None, inputs=None, column=None):

        self.start_line()

        self.terminal.delete("line_start", "end-1c")

        if line:
            self.terminal.insert("end", line)

        self.apply_device_colors(line, styles or [])
        self.highlight_open_line()
        self.mark_input(line, inputs or [])

        # A device erases with backspace-space-backspace, so the blank
        # it wrote stays in the text and only the cursor moves back.
        if column is not None:
            self.terminal.mark_set(
                "insert",
                "%s+%dc" % (self.terminal.index("line_start"), column)
            )

    def apply_device_colors(self, line, styles):
        """Paint the colours the device asked for, under the rule tags."""

        if not line or not self.device_colors_var.get():
            return

        start = self.terminal.index("line_start")

        offset = 0

        for sgr, chunk in style_runs(line, styles):

            if sgr:

                tag = self.sgr_tag(sgr)

                if tag:

                    self.terminal.tag_add(
                        tag,
                        f"{start}+{offset}c",
                        f"{start}+{offset + len(chunk)}c"
                    )

            offset += len(chunk)

    def mark_input(self, line, inputs):
        """Colour the characters the device echoed back after we typed them."""

        if (
            not line
            or not self.config["input_color"]
            or not self.mark_input_var.get()
        ):
            return

        start = self.terminal.index("line_start")

        position = 0

        while position < len(line):

            if position >= len(inputs) or not inputs[position]:
                position += 1
                continue

            end = position

            while end < len(inputs) and inputs[end]:
                end += 1

            self.terminal.tag_add(
                "input_text",
                f"{start}+{position}c",
                f"{start}+{end}c"
            )

            position = end

    def sgr_tag(self, sgr):
        """Create, cache and return a tag for one SGR state."""

        if sgr in self.sgr_tags:
            return self.sgr_tags[sgr]

        foreground, background = sgr_to_colors(sgr)

        if not foreground and not background:
            self.sgr_tags[sgr] = None
            return None

        tag = f"sgr_{len(self.sgr_tags)}"

        kwargs = {}

        if foreground:
            kwargs["foreground"] = foreground

        if background:
            kwargs["background"] = background

        self.terminal.tag_configure(tag, **kwargs)

        # Highlight rules win over the device's own colours.
        self.terminal.tag_lower(tag, "rule_0")

        self.sgr_tags[sgr] = tag

        return tag

    def start_line(self):

        if self.line_open:
            return

        if self.timestamp_var.get():

            self.write_plain(
                datetime.now().strftime(
                    "[%Y-%m-%d %H:%M:%S] "
                )
            )

        # Left gravity keeps the mark in front of text inserted
        # at the end of the widget.
        self.terminal.mark_set("line_start", "end-1c")
        self.terminal.mark_gravity("line_start", "left")

        self.line_open = True

    def toggle_highlight(self):
        """Rules on or off. Device ANSI and typed text are separate."""

        self.rehighlight_all()

    def toggle_reconnect(self):
        """Keep the plain copy the reader thread reads in step."""

        self.reconnect_enabled = self.reconnect_var.get()

    def highlight_open_line(self):

        if not self.line_open or not self.highlight_var.get():
            return

        start = self.terminal.index("line_start")
        end = self.terminal.index("end-1c")

        line = self.terminal.get(start, end)

        if not line:
            return

        for index in range(len(ACTIVE_RULES)):

            self.terminal.tag_remove(
                f"rule_{index}",
                start,
                end
            )

        for match_start, match_end, rule_index in find_matches(line):

            self.terminal.tag_add(
                f"rule_{rule_index}",
                f"{start}+{match_start}c",
                f"{start}+{match_end}c"
            )

    # ========================================================
    # Plain text
    # ========================================================

    def write_plain(self, text):

        self.terminal.insert(
            "end",
            text
        )

    # ========================================================
    # Keyboard input
    # ========================================================

    def key_pressed(self, event):

        if not self.serial or not self.serial.is_open:
            return "break"

        # Ignore control keys handled by Tk
        if event.keysym in (
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Caps_Lock"
        ):
            return "break"

        try:

            # Arrows and navigation keys, as a terminal would send them
            sequence = TK_SPECIAL_KEYS.get(event.keysym)

            if sequence:

                self.serial.write(
                    sequence.encode("utf-8")
                )

                self.assembler.expect_redraw()

            # Enter
            elif event.keysym == "Return":

                self.serial.write(
                    b"\r\n"
                )

                self.echo_local("\n")

            # Backspace
            elif event.keysym == "BackSpace":

                self.serial.write(
                    b"\x08"
                )

                self.echo_local("\x08")

            # Normal character
            elif event.char:

                self.serial.write(
                    event.char.encode(
                        "utf-8"
                    )
                )

                self.assembler.expect_echo(event.char)

                self.echo_local(event.char)

        except Exception as e:

            self.notice(f"[TX error: {e}]")

        return "break"

    def echo_local(self, text):
        """
        Show what was typed, for a device that does not echo.

        Escape sequences are left out: they are a device-side edit, and
        printing their characters would just be junk on the line.
        """

        if text and self.local_echo_var.get():
            self.display_text(text, as_input=True)

    # ========================================================
    # Clear
    # ========================================================

    def clear_terminal(self):

        self.terminal.delete(
            "1.0",
            "end"
        )

        self.line_open = False
        self.assembler.reset()

    # ========================================================
    # Settings
    # ========================================================

    def save_settings(self):
        """Remember the toolbar state for the next run."""

        config = dict(self.config)

        config.update({
            "front_end": "gui",
            "port": self.port_var.get() or config.get("port"),
            "timestamp": self.timestamp_var.get(),
            "device_colors": self.device_colors_var.get(),
            "local_echo": self.local_echo_var.get(),
            "highlight": self.highlight_var.get(),
            "reconnect": self.reconnect_var.get(),
        })

        try:
            config["baud"] = int(self.baud_var.get())
        except ValueError:
            pass

        if not self.mark_input_var.get():
            config["input_color"] = None
        elif not config.get("input_color"):
            config["input_color"] = INPUT_COLOR

        save_config(config, self.config_path)

    # ========================================================
    # XMODEM
    # ========================================================

    def open_xmodem(self):

        if not self.serial or not self.serial.is_open:

            messagebox.showerror(
                "XMODEM",
                "Connect to a port first."
            )
            return

        try:

            dialog = XmodemDialog(
                self.serial,
                pause_event=self.pause_reader,
                block_size=128 if self.config["xmodem"] == "128" else 1024,
                parent=self.root,
                title=f"XMODEM send - {self.port_var.get()}"
            )

            dialog.run()

        finally:
            # A window that never came up would leave the buffers off
            unlock_buffer_dialogs()

    # ========================================================
    # Highlight rules
    # ========================================================

    def open_rules(self):

        profile = self.config.get("rule_profile")

        dialog = HighlightDialog(
            self.config.get("rules") or default_user_rules(profile),
            self.rules_applied,
            parent=self.root,
            title="Highlight rules",
            profile=profile
        )

        dialog.run()

    def rules_applied(self, rules, profile=None):

        self.config["rules"] = rules
        self.config["rule_profile"] = profile or self.config["rule_profile"]

        save_config(self.config, self.config_path)

        # New rules mean new tags, and the text already on screen
        # should follow them too.
        self.create_tags()
        self.rehighlight_all()

    def rehighlight_all(self):

        for tag in self.terminal.tag_names():

            if tag.startswith("rule_"):
                self.terminal.tag_remove(tag, "1.0", "end")

        if not self.highlight_var.get():
            return

        last = int(self.terminal.index("end-1c").split(".")[0])

        for number in range(1, last + 1):

            text = self.terminal.get(f"{number}.0", f"{number}.end")

            if not text:
                continue

            if "notice" in self.terminal.tag_names(f"{number}.0"):
                continue

            for start, end, index in find_matches(text):

                self.terminal.tag_add(
                    f"rule_{index}",
                    f"{number}.{start}",
                    f"{number}.{end}"
                )

    # ========================================================
    # Command buffers
    # ========================================================

    def open_buffers(self):

        path = buffer_file(self.config.get("buffers"))

        ensure_buffer_file(path)

        dialog = BufferDialog(
            self.write_serial,
            parent=self.root,
            path=path,
            title=f"Buffers - {self.port_var.get()}"
        )

        dialog.run()

    def write_serial(self, data):

        if not self.serial or not self.serial.is_open:
            raise IOError("not connected")

        text = data.decode("utf-8", "replace")

        if "\x1b" in text:
            self.assembler.expect_redraw()
        else:
            self.assembler.expect_echo(text)

        self.serial.write(data)

        # A buffer sent to a device that does not echo would otherwise
        # leave no trace of what was sent.
        if "\x1b" not in text:
            self.echo_local(text)

    # ========================================================
    # Save
    # ========================================================

    def save_output(self):

        filename = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[
                ("Log files", "*.log"),
                ("Text files", "*.txt"),
                ("All files", "*.*")
            ]
        )

        if not filename:
            return

        content = self.terminal.get(
            "1.0",
            "end"
        )

        try:

            with open(
                filename,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(content)

            self.status_var.set(
                f"Saved: {filename}"
            )

        except Exception as e:

            messagebox.showerror(
                "Save error",
                str(e)
            )


# ============================================================
# ANSI colouring for the CLI front end
# ============================================================

RESET = "\x1b[0m"


def ansi_code(foreground, background):

    parts = []

    if foreground:
        r, g, b = hex_to_rgb(foreground)
        parts.append(f"38;2;{r};{g};{b}")

    if background:
        r, g, b = hex_to_rgb(background)
        parts.append(f"48;2;{r};{g};{b}")

    if not parts:
        return ""

    return "\x1b[" + ";".join(parts) + "m"


def hex_to_rgb(value):

    value = value.lstrip("#")

    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16)
    )


def colorize(text, styles=None, inputs=None, input_color=None, rules=True):
    """
    Paint one line for the terminal.

    Priority, highest first: characters we typed, so your own input
    stands out, then the highlight rules, then whatever colour the
    device asked for.

    The three are independent: pass rules=False, styles=None or
    input_color=None to drop that one and leave the others working.
    """

    if not text:
        return ""

    rule_of = {}

    if rules:

        for start, end, rule_index in find_matches(text):

            for position in range(start, end):
                rule_of[position] = rule_index

    tokens = []

    for position, char in enumerate(text):

        if (
            input_color
            and inputs
            and position < len(inputs)
            and inputs[position]
        ):
            tokens.append(("input", None))

        elif position in rule_of:
            tokens.append(("rule", rule_of[position]))

        elif styles and position < len(styles) and styles[position]:
            tokens.append(("sgr", styles[position]))

        else:
            tokens.append(("plain", None))

    out = []
    position = 0

    while position < len(text):

        token = tokens[position]

        end = position

        while end < len(text) and tokens[end] == token:
            end += 1

        chunk = text[position:end]
        kind, value = token

        if kind == "input":
            out.append(ansi_code(input_color, None) + chunk + RESET)

        elif kind == "rule":

            pattern, foreground, background = ACTIVE_RULES[value][:3]

            out.append(ansi_code(foreground, background) + chunk + RESET)

        elif kind == "sgr":
            out.append(f"\x1b[{value}m" + chunk + RESET)

        else:
            out.append(chunk)

        position = end

    return "".join(out)


def enable_windows_vt():
    """Turn on ANSI escape handling in the Windows console."""

    if os.name != "nt":
        return

    try:

        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)

        mode = ctypes.c_uint32()

        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):

            kernel32.SetConsoleMode(
                handle,
                mode.value | 0x0004
            )

    except Exception:
        pass


# With this flag set the Windows console eats Ctrl+C itself and raises
# it as a signal. Clearing it hands the key over as a plain \x03 byte.
ENABLE_PROCESSED_INPUT = 0x0001


def windows_console_input():
    """Handle and current mode of the console input buffer."""

    if os.name != "nt":
        return None, None

    try:

        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)

        mode = ctypes.c_uint32()

        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None, None

        return handle, mode.value

    except Exception:
        return None, None


def set_windows_console_mode(handle, mode):

    if os.name != "nt" or handle is None or mode is None:
        return False

    try:

        import ctypes

        return bool(ctypes.windll.kernel32.SetConsoleMode(handle, mode))

    except Exception:
        return False


# ============================================================
# XMODEM sender (CRC-128 and 1K)
# ============================================================

XMODEM_SOH = 0x01
XMODEM_STX = 0x02
XMODEM_EOT = 0x04
XMODEM_ACK = 0x06
XMODEM_NAK = 0x15
XMODEM_CAN = 0x18
XMODEM_SUB = 0x1a
XMODEM_CRC_CHAR = 0x43      # 'C', receiver asking for CRC mode


def crc16_xmodem(data):

    crc = 0

    for byte in data:

        crc ^= byte << 8

        for _ in range(8):

            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xffff
            else:
                crc = (crc << 1) & 0xffff

    return crc


DRIVE_PATTERN = re.compile(r"^([A-Za-z]):?[\\/](.*)$", re.DOTALL)


def resolve_path(raw):
    """
    Turn what the user typed into an existing file path.

    Accepts quotes, ~, environment variables, forward or back slashes,
    a Windows path while running under WSL, and a drive letter typed
    without its colon (C\\Users\\... instead of C:\\Users\\...).

    Returns (path, tried) where path is None when nothing matched.
    """

    text = raw.strip().strip('"').strip("'").strip()

    if not text:
        return None, []

    candidates = []

    def add(value):
        if value and value not in candidates:
            candidates.append(value)

    expanded = os.path.expanduser(os.path.expandvars(text))

    add(expanded)
    add(expanded.replace("\\", "/"))

    match = DRIVE_PATTERN.match(expanded)

    if match:

        drive, rest = match.group(1), match.group(2)

        rest_backslash = rest.replace("/", "\\")
        rest_slash = rest.replace("\\", "/")

        # Windows form, with the colon put back if it was missing
        add(f"{drive}:\\{rest_backslash}")
        add(f"{drive}:/{rest_slash}")

        # Same path seen from WSL
        add(f"/mnt/{drive.lower()}/{rest_slash}")

    for candidate in candidates:

        if os.path.isfile(candidate):
            return candidate, candidates

    return None, candidates


class XmodemSender:
    """
    XMODEM upload over an open pyserial port.

    block_size 128 sends SOH blocks, 1024 sends STX blocks and falls
    back to a 128-byte block for a short tail. CRC or checksum is chosen
    from what the receiver asks for: 'C' means CRC, NAK means checksum.

    The caller must make sure nothing else is reading the port while a
    transfer runs.
    """

    def __init__(
        self,
        port,
        block_size=1024,
        status=None,
        cancelled=None,
        progress=None,
        start_timeout=60.0,
        ack_timeout=10.0,
        retries=10
    ):

        self.port = port
        self.block_size = block_size
        self.status = status or (lambda message, progress=False: None)
        self.cancelled = cancelled or (lambda: False)
        self.progress = progress or (lambda sent, total, blocks: None)
        self.start_timeout = start_timeout
        self.ack_timeout = ack_timeout
        self.retries = retries

        # Sticky: the abort key is consumed by the first check that sees it
        self.aborted = False

    # --------------------------------------------------------

    def is_cancelled(self):

        if not self.aborted and self.cancelled():
            self.aborted = True

        return self.aborted

    def read_byte(self, timeout):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            data = self.port.read(1)

            if data:
                return data[0]

            if self.is_cancelled():
                return None

        return None

    def read_answer(self, timeout):
        """
        Wait for a protocol reply, skipping anything else.

        A receiver polls with 'C' or NAK every few seconds before the
        transfer starts, so several of them are usually still queued when
        the first block goes out. Taking one of those for the block's
        answer resends block 1, which the receiver sees as a duplicate
        sequence number and aborts on. Devices also print human-readable
        text into the same stream, so only ACK, NAK and CAN count.
        """

        deadline = time.monotonic() + timeout

        while True:

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                return None

            byte = self.read_byte(min(0.5, remaining))

            if byte is None:

                if self.aborted:
                    return None

                continue

            if byte in (XMODEM_ACK, XMODEM_NAK, XMODEM_CAN):
                return byte

    def drain_input(self):

        try:
            self.port.reset_input_buffer()
        except Exception:
            pass

    def cancel(self):

        try:
            self.port.write(bytes([XMODEM_CAN] * 3))
            self.port.flush()
        except Exception:
            pass

    # --------------------------------------------------------

    def wait_for_start(self):
        """Return True for CRC, False for checksum, None if it never came."""

        deadline = time.monotonic() + self.start_timeout

        while time.monotonic() < deadline:

            if self.is_cancelled():
                return None

            byte = self.read_byte(1.0)

            if byte == XMODEM_CRC_CHAR:
                return True

            if byte == XMODEM_NAK:
                return False

            if byte == XMODEM_CAN:
                return None

        return None

    def build_packet(self, index, chunk, crc_mode):

        header = XMODEM_SOH if len(chunk) == 128 else XMODEM_STX

        packet = bytearray()
        packet.append(header)
        packet.append(index)
        packet.append(0xff - index)
        packet.extend(chunk)

        if crc_mode:

            crc = crc16_xmodem(chunk)

            packet.append((crc >> 8) & 0xff)
            packet.append(crc & 0xff)

        else:
            packet.append(sum(chunk) & 0xff)

        return bytes(packet)

    def send_packet(self, packet):
        """Write one block and wait for its ACK. False means give up."""

        for attempt in range(self.retries):

            if self.is_cancelled():
                return False

            self.port.write(packet)
            self.port.flush()

            answer = self.read_answer(self.ack_timeout)

            if answer == XMODEM_ACK:
                return True

            if answer == XMODEM_CAN:
                self.status("XMODEM: receiver cancelled")
                return False

            # NAK or a timeout: send the same block again
            self.status(
                f"XMODEM: retry {attempt + 1}/{self.retries}",
                progress=True
            )

        return False

    def send_eot(self):

        for _ in range(self.retries):

            self.port.write(bytes([XMODEM_EOT]))
            self.port.flush()

            if self.read_answer(self.ack_timeout) == XMODEM_ACK:
                return True

        return False

    # --------------------------------------------------------

    def send(self, path):

        with open(path, "rb") as handle:
            payload = handle.read()

        if not payload:
            self.status("XMODEM: file is empty, nothing to send")
            return False

        label = "1K" if self.block_size == 1024 else "128-byte"

        self.status(
            f"XMODEM: {os.path.basename(path)}, {len(payload)} bytes, "
            f"{label} blocks"
        )

        self.status(
            "XMODEM: waiting for the receiver "
            "(start the download on the device, ESC or Ctrl+C aborts)"
        )

        try:
            self.port.reset_input_buffer()
        except Exception:
            pass

        crc_mode = self.wait_for_start()

        if crc_mode is None:

            if self.aborted:
                self.status("XMODEM: aborted")
            else:
                self.status(
                    "XMODEM: no start character from receiver, aborted"
                )

            self.cancel()
            return False

        self.status(
            "XMODEM: receiver ready ("
            + ("CRC" if crc_mode else "checksum")
            + " mode)"
        )

        # Drop the poll characters the receiver queued up while it was
        # waiting; nothing that matters can be in the buffer yet.
        self.drain_input()

        position = 0
        index = 1
        blocks = 0

        while position < len(payload):

            if self.is_cancelled():
                self.status("XMODEM: aborted")
                self.cancel()
                return False

            remaining = len(payload) - position

            size = self.block_size

            # A short tail travels faster in a 128-byte block.
            if size == 1024 and remaining <= 128:
                size = 128

            chunk = payload[position:position + size]
            chunk = chunk.ljust(size, bytes([XMODEM_SUB]))

            if not self.send_packet(self.build_packet(index, chunk, crc_mode)):

                if self.aborted:
                    self.status("XMODEM: aborted")
                else:
                    self.status("XMODEM: transfer failed")

                self.cancel()
                return False

            position += size
            index = (index + 1) % 256
            blocks += 1

            sent = min(position, len(payload))
            percent = min(100, position * 100 // len(payload))

            self.progress(sent, len(payload), blocks)

            self.status(
                f"XMODEM: {sent}/{len(payload)} bytes "
                f"({percent}%), {blocks} blocks",
                progress=True
            )

        if not self.send_eot():
            self.status("XMODEM: no ACK for EOT, transfer may have failed")
            return False

        self.status(f"XMODEM: done, {blocks} blocks sent")

        return True


# ============================================================
# Highlight rule window
#
# Six rules, each an expression and a colour, in the spirit of
# MobaXterm's syntax highlighting dialog.
# ============================================================

SAMPLE_LINE = "[00:12:04] INFO link UP 10.0.0.5 -42.5 dBm 23.5 C ERROR retry 3"


class HighlightDialog:

    def __init__(
        self,
        rules,
        on_apply,
        parent=None,
        title="Highlight rules",
        profile=DEFAULT_RULE_PROFILE
    ):

        self.on_apply = on_apply

        # Which stock set the rows came from. Apply hands it back so the
        # choice is what the settings file remembers.
        self.profile = profile if profile in RULE_PROFILES else (
            DEFAULT_RULE_PROFILE
        )

        self.owns_root = parent is None

        if self.owns_root:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(parent)

        self.root.title(title)
        self.root.resizable(False, False)

        self.rows = []

        self.build(rules)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        if not self.owns_root:
            self.root.transient(parent)
            self.root.grab_set()

        self.update_preview()

    # --------------------------------------------------------

    def build(self, rules):

        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Expressions are Python regular expressions. Where two "
                 "match the same text the longer one wins, and on an "
                 "equal match the upper row does."
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))

        for column, heading in enumerate(
            ("On", "Expression", "Text", "Back", "Aa")
        ):
            ttk.Label(frame, text=heading).grid(
                row=1, column=column, sticky="w", padx=(0, 6)
            )

        for index in range(USER_RULE_COUNT):

            stored = rules[index] if index < len(rules) else {}

            row = {
                "enabled": tk.BooleanVar(
                    master=self.root,
                    value=stored.get("enabled", True)
                ),
                "pattern": tk.StringVar(
                    master=self.root,
                    value=stored.get("pattern", "")
                ),
                "foreground": stored.get("foreground") or "#ffffff",
                "background": stored.get("background"),
                "ignore_case": tk.BooleanVar(
                    master=self.root,
                    value=stored.get("ignore_case", True)
                ),
            }

            line = index + 2

            check_button(
                frame,
                variable=row["enabled"],
                command=self.update_preview
            ).grid(row=line, column=0, sticky="w")

            entry = ttk.Entry(
                frame,
                textvariable=row["pattern"],
                width=40
            )
            entry.grid(row=line, column=1, sticky="we", padx=(0, 6))

            row["pattern"].trace_add(
                "write",
                lambda *ignored: self.update_preview()
            )

            row["fg_button"] = tk.Button(
                frame,
                width=3,
                relief="ridge",
                command=lambda i=index: self.pick(i, "foreground")
            )
            row["fg_button"].grid(row=line, column=2, padx=(0, 4))

            row["bg_button"] = tk.Button(
                frame,
                width=3,
                relief="ridge",
                command=lambda i=index: self.pick(i, "background")
            )
            row["bg_button"].grid(row=line, column=3, padx=(0, 6))

            check_button(
                frame,
                variable=row["ignore_case"],
                command=self.update_preview
            ).grid(row=line, column=4, sticky="w")

            self.rows.append(row)

            self.paint_swatches(index)

        # Preview
        ttk.Label(frame, text="Sample:").grid(
            row=USER_RULE_COUNT + 2, column=0, columnspan=2,
            sticky="w", pady=(12, 2)
        )

        self.sample_var = tk.StringVar(master=self.root, value=SAMPLE_LINE)

        sample = ttk.Entry(
            frame,
            textvariable=self.sample_var,
            width=40
        )
        sample.grid(
            row=USER_RULE_COUNT + 3, column=0, columnspan=5,
            sticky="we"
        )

        self.sample_var.trace_add(
            "write",
            lambda *ignored: self.update_preview()
        )

        self.preview = tk.Text(
            frame,
            height=2,
            bg="#050505",
            fg="#dddddd",
            font=("Consolas", 10),
            wrap="none",
            highlightthickness=0
        )
        self.preview.grid(
            row=USER_RULE_COUNT + 4, column=0, columnspan=5,
            sticky="we", pady=(6, 0)
        )

        self.status_var = tk.StringVar(master=self.root, value="")

        ttk.Label(frame, textvariable=self.status_var).grid(
            row=USER_RULE_COUNT + 5, column=0, columnspan=5,
            sticky="w", pady=(6, 0)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(
            row=USER_RULE_COUNT + 6, column=0, columnspan=5,
            sticky="we", pady=(10, 0)
        )

        # The stock sets are a group of their own, the way the toolbar
        # boxes its controls: pressing one only fills the rows in, and
        # Apply is still what keeps them.
        profiles = ttk.Labelframe(
            buttons,
            text="Profile",
            padding=(6, 2, 6, 4)
        )
        profiles.pack(side="left")

        ttk.Button(
            profiles,
            text="Simple",
            command=lambda: self.load_profile("simple")
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            profiles,
            text="Extended",
            command=lambda: self.load_profile("extended")
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            profiles,
            text="Network",
            command=lambda: self.load_profile("network")
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            profiles,
            text="Custom",
            command=lambda: self.load_profile("custom")
        ).pack(side="left")

        ttk.Button(buttons, text="Close", command=self.close).pack(
            side="right"
        )

        ttk.Button(buttons, text="Apply", command=self.apply).pack(
            side="right", padx=(0, 6)
        )

        frame.columnconfigure(1, weight=1)

    # --------------------------------------------------------

    def paint_swatches(self, index):

        row = self.rows[index]

        row["fg_button"].configure(
            bg=row["foreground"],
            activebackground=row["foreground"]
        )

        background = row["background"]

        row["bg_button"].configure(
            text="" if background else "-",
            bg=background or "#f0f0f0",
            activebackground=background or "#f0f0f0"
        )

    def pick(self, index, which):

        row = self.rows[index]

        current = row[which] or "#ffffff"

        chosen = colorchooser.askcolor(
            color=current,
            parent=self.root,
            title=f"{which.title()} colour for rule {index + 1}"
        )[1]

        if chosen:
            row[which] = chosen

        elif which == "background":
            # Cancelling the background picker clears it
            row[which] = None

        self.paint_swatches(index)
        self.update_preview()

    def rules(self):

        return [
            {
                "enabled": row["enabled"].get(),
                "pattern": row["pattern"].get(),
                "foreground": row["foreground"],
                "background": row["background"],
                "ignore_case": row["ignore_case"].get(),
            }
            for row in self.rows
        ]

    def update_preview(self):
        """Colour the sample with the rules as they stand."""

        broken = []

        for index, row in enumerate(self.rows):

            pattern = row["pattern"].get().strip()

            if not pattern:
                continue

            try:
                re.compile(pattern)
            except re.error as e:
                broken.append(f"rule {index + 1}: {e}")

        self.status_var.set(
            "; ".join(broken) if broken else ""
        )

        saved = list(ACTIVE_RULES)

        try:

            table = set_user_rules(self.rules())

            text = self.sample_var.get()

            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", text)

            for tag in self.preview.tag_names():
                self.preview.tag_delete(tag)

            for start, end, index in find_matches(text):

                pattern, foreground, background = table[index][:3]

                tag = f"preview_{index}"

                options = {"foreground": foreground}

                if background:
                    options["background"] = background

                self.preview.tag_configure(tag, **options)

                self.preview.tag_add(
                    tag,
                    f"1.{start}",
                    f"1.{end}"
                )

        finally:

            # The preview must not change what the terminal is using
            # until Apply is pressed.
            globals()["ACTIVE_RULES"] = saved

    def load_profile(self, profile=None):
        """Fill the rows with one of the stock sets."""

        self.profile = profile or self.profile

        for index, default in enumerate(default_user_rules(self.profile)):

            row = self.rows[index]

            row["enabled"].set(default["enabled"])
            row["pattern"].set(default["pattern"])
            row["foreground"] = default["foreground"]
            row["background"] = default["background"]
            row["ignore_case"].set(default["ignore_case"])

            self.paint_swatches(index)

        self.sample_var.set(SAMPLE_LINE)

        self.update_preview()

        self.status_var.set(
            f"{self.profile.capitalize()} rules filled in"
            " - press Apply to keep them"
        )

    def apply(self):

        set_user_rules(self.rules())

        if self.on_apply:
            self.on_apply(self.rules(), self.profile)

        self.status_var.set("Applied and saved")

    def close(self):

        try:

            if not self.owns_root:
                self.root.grab_release()

            self.root.destroy()

        except Exception:
            pass

    def run(self):

        if self.owns_root:
            self.root.mainloop()
        else:
            self.root.wait_window(self.root)


# ============================================================
# XMODEM transfer window
#
# Used from both front ends. In CLI mode it keeps the transfer out
# of the terminal, which is otherwise a mess of device output and
# progress lines fighting for the same line.
# ============================================================

class XmodemDialog:

    # How long a finished transfer stays on screen before the window goes
    AUTO_CLOSE_MS = 1500

    # The buffer lock note, red enough to read on either theme
    LOCK_COLOR = "#ff5555"

    def __init__(
        self,
        port,
        pause_event=None,
        block_size=1024,
        parent=None,
        initial_path=None,
        autostart=False,
        title="XMODEM send"
    ):

        self.autostart = autostart

        self.port = port
        self.pause_event = pause_event
        self.default_block = block_size

        self.cancel_event = threading.Event()
        self.updates = queue.Queue()

        self.worker = None
        self.running = False
        self.result = None
        self.auto_close_id = None

        self.started_at = None
        self.owns_root = parent is None

        # A buffer sent mid-transfer would corrupt it, so the buffer
        # windows stop sending until this one is gone.
        self.locked_buffers = lock_buffer_dialogs()

        if self.owns_root:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(parent)

        self.root.title(title)
        self.root.resizable(False, False)

        self.build(initial_path)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        if not self.owns_root:
            self.root.transient(parent)
            self.root.grab_set()

        self.raise_window()

        if self.locked_buffers:

            # The buffer window needs a poll to notice it is locked and
            # let go of always-on-top, so this window claims the front
            # again after that.
            self.root.after(
                BufferDialog.LOCK_POLL_MS + 100, self.raise_window
            )

            self.lock_label.config(text="Buffers disabled")

    def raise_window(self):
        """Put this window in front, whatever else is on top."""

        try:

            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

        except Exception:
            pass

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    def build(self, initial_path):

        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="File:").grid(
            row=0, column=0, sticky="w"
        )

        # Every variable is tied to this window's own root. Without a
        # master they attach to whatever root tkinter saw first, which
        # in CLI mode belongs to another window in another thread.
        self.path_var = tk.StringVar(
            master=self.root,
            value=initial_path or ""
        )

        self.path_entry = ttk.Entry(
            frame,
            textvariable=self.path_var,
            width=52
        )
        self.path_entry.grid(row=0, column=1, sticky="we", padx=(6, 6))

        self.browse_button = ttk.Button(
            frame,
            text="Browse...",
            command=self.browse
        )
        self.browse_button.grid(row=0, column=2)

        ttk.Label(frame, text="Format:").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )

        formats = ttk.Frame(frame)
        formats.grid(row=1, column=1, sticky="w", pady=(10, 0), padx=(6, 0))

        self.block_var = tk.IntVar(
            master=self.root,
            value=self.default_block
        )

        ttk.Radiobutton(
            formats,
            text="XMODEM-1K (1024 byte blocks)",
            variable=self.block_var,
            value=1024
        ).pack(side="left")

        ttk.Radiobutton(
            formats,
            text="XMODEM-CRC (128 byte blocks)",
            variable=self.block_var,
            value=128
        ).pack(side="left", padx=(12, 0))

        self.progress_bar = ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=100,
            length=460
        )
        self.progress_bar.grid(
            row=2, column=0, columnspan=3, sticky="we", pady=(14, 6)
        )

        self.status_var = tk.StringVar(
            master=self.root,
            value="Pick a file, then start the receive command on the device."
        )

        ttk.Label(
            frame,
            textvariable=self.status_var,
            wraplength=520,
            justify="left"
        ).grid(row=3, column=0, columnspan=3, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="we", pady=(14, 0))

        # Packed right to left, so they read Send, Abort, Close and the
        # lock note gets the free space on the left.
        self.close_button = ttk.Button(
            buttons,
            text="Close",
            command=self.close
        )
        self.close_button.pack(side="right")

        self.abort_button = ttk.Button(
            buttons,
            text="Abort",
            command=self.abort,
            state="disabled"
        )
        self.abort_button.pack(side="right", padx=(0, 6))

        self.send_button = ttk.Button(
            buttons,
            text="Send",
            command=self.start
        )
        self.send_button.pack(side="right", padx=(0, 6))

        self.lock_label = ttk.Label(
            buttons,
            text="",
            foreground=self.LOCK_COLOR
        )
        self.lock_label.pack(side="left")

        frame.columnconfigure(1, weight=1)

    # --------------------------------------------------------
    # Actions
    # --------------------------------------------------------

    def browse(self):

        filename = filedialog.askopenfilename(
            parent=self.root,
            title="File to send"
        )

        if filename:
            self.path_var.set(filename)

    def start(self):

        if self.running:
            return

        path, tried = resolve_path(self.path_var.get())

        if not path:

            self.status_var.set(
                "No such file. Tried:\n" + "\n".join(tried)
            )
            return

        self.path_var.set(path)

        block_size = self.block_var.get()

        self.cancel_event.clear()
        self.running = True
        self.result = None
        self.started_at = None

        self.progress_bar["value"] = 0

        self.send_button.state(["disabled"])
        self.browse_button.state(["disabled"])
        self.path_entry.state(["disabled"])
        self.abort_button.state(["!disabled"])

        if self.pause_event is not None:
            self.pause_event.set()

        self.worker = threading.Thread(
            target=self.run_transfer,
            args=(path, block_size),
            daemon=True
        )
        self.worker.start()

        self.root.after(50, self.poll)

    def run_transfer(self, path, block_size):

        # Let a read already in flight finish before taking the port
        time.sleep(0.3)

        ok = False

        try:

            sender = XmodemSender(
                self.port,
                block_size=block_size,
                status=lambda message, progress=False: self.updates.put(
                    ("status", message)
                ),
                progress=lambda sent, total, blocks: self.updates.put(
                    ("progress", (sent, total, blocks))
                ),
                cancelled=self.cancel_event.is_set
            )

            ok = sender.send(path)

        except Exception as e:
            self.updates.put(("status", f"Error: {e}"))

        finally:

            if self.pause_event is not None:
                self.pause_event.clear()

            self.updates.put(("done", ok))

    def poll(self):

        try:

            while True:

                kind, payload = self.updates.get_nowait()

                if kind == "status":
                    self.status_var.set(payload.replace("XMODEM: ", ""))

                elif kind == "progress":
                    self.show_progress(*payload)

                elif kind == "done":
                    self.finish(payload)
                    return

        except queue.Empty:
            pass

        self.root.after(50, self.poll)

    def show_progress(self, sent, total, blocks):

        if self.started_at is None:
            self.started_at = time.monotonic()

        percent = sent * 100 / total if total else 0

        self.progress_bar["value"] = percent

        elapsed = max(0.001, time.monotonic() - self.started_at)
        rate = sent / elapsed

        message = (
            f"{sent:,} / {total:,} bytes  ({percent:.0f}%), "
            f"{blocks} blocks, {rate / 1024:.1f} kB/s"
        )

        if rate > 0 and sent < total:

            remaining = int((total - sent) / rate)

            message += f", {remaining // 60}m {remaining % 60:02d}s left"

        self.status_var.set(message)

    def finish(self, ok):

        self.running = False
        self.result = ok

        self.send_button.state(["!disabled"])
        self.browse_button.state(["!disabled"])
        self.path_entry.state(["!disabled"])
        self.abort_button.state(["disabled"])

        if ok:

            self.progress_bar["value"] = 100

            # A transfer that worked has nothing left to read, so the
            # window goes on its own. A failed one stays up.
            self.status_var.set(
                self.status_var.get() + "  Done, closing this window."
            )

            self.auto_close_id = self.root.after(
                self.AUTO_CLOSE_MS, self.auto_close
            )

    def auto_close(self):
        """Close after a good transfer, unless another one has started."""

        self.auto_close_id = None

        if self.running or not self.result:
            return

        self.close()

    def abort(self):

        if self.running:

            self.cancel_event.set()
            self.status_var.set("Aborting...")

    def close(self):

        if self.running:

            self.cancel_event.set()

            # Let the sender notice and send CAN before the port goes back
            self.root.after(300, self.close)
            return

        if self.pause_event is not None:
            self.pause_event.clear()

        unlock_buffer_dialogs()

        if self.auto_close_id is not None:

            try:
                self.root.after_cancel(self.auto_close_id)
            except Exception:
                pass

            self.auto_close_id = None

        try:

            if self.owns_root:
                self.root.destroy()
            else:
                self.root.grab_release()
                self.root.destroy()

        except Exception:
            pass

    def run(self):
        """Show the window and block until it is closed."""

        if self.autostart:
            self.root.after(200, self.start)

        if self.owns_root:
            self.root.mainloop()
        else:
            self.root.wait_window(self.root)

        return self.result


# ============================================================
# Command buffers
#
# Ten slots of text that can be fired at the device, kept in a
# small JSON file so they survive a restart.
# ============================================================

# ============================================================
# Settings file
#
# Defaults for the command line flags and the GUI toggles, so a
# usual setup does not have to be typed out every time. Anything
# given on the command line still wins.
# ============================================================

CONFIG_FILE = os.path.join(
    os.path.expanduser("~"),
    ".serialkit.json"
)

# Which front end the buffers and the XMODEM transfer put up when the
# session is a CLI one. The window is the richer of the two, but it
# needs a display, and a Linux session is as often as not an ssh
# session; so "auto" is a window on Windows and a prompt on Linux, and
# either can be asked for outright on either platform.
UI_CHOICES = ("auto", "gui", "cli")


def ui_choice(value, fallback="auto"):
    """One of UI_CHOICES out of a settings file, or the fallback."""

    value = str(value).strip().lower() if value is not None else ""

    return value if value in UI_CHOICES else fallback


CONFIG_DEFAULTS = {
    "front_end": "gui",          # what runs when neither --cli nor --gui
    "port": None,
    "baud": 115200,
    "timestamp": False,
    "color": True,
    "device_colors": True,
    "input_color": INPUT_COLOR,
    "local_echo": False,
    "xmodem": "1k",
    "buffer_ui": "auto",         # auto, gui or cli; see UI_CHOICES
    "transfer_ui": "auto",
    "text_transfer": False,      # kept for older settings files
    "reconnect": True,
    "highlight": True,
    "rules": [],
    "rule_profile": DEFAULT_RULE_PROFILE,
    "buffers": None,             # buffer file, None means the usual one
}


def load_config(path=CONFIG_FILE):

    config = dict(CONFIG_DEFAULTS)

    try:

        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)

        if isinstance(stored, dict):

            for key, value in stored.items():

                if key in CONFIG_DEFAULTS:
                    config[key] = value

    except Exception:
        pass

    config["buffer_ui"] = ui_choice(config["buffer_ui"])
    config["transfer_ui"] = ui_choice(config["transfer_ui"])

    # text_transfer was the older way of saying "no transfer window".
    # A file that still carries it keeps meaning what it meant, unless
    # transfer_ui has since been written and says otherwise.
    if config["text_transfer"] and config["transfer_ui"] == "auto":
        config["transfer_ui"] = "cli"

    return config


def save_config(config, path=CONFIG_FILE):

    merged = dict(CONFIG_DEFAULTS)

    for key, value in config.items():

        if key in CONFIG_DEFAULTS:
            merged[key] = value

    try:

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2, sort_keys=True)

        return True

    except Exception:
        return False


# Slots a fresh file starts with, and the range the window allows. The
# file itself carries the count from then on: the window can add and
# remove slots, and what it saves is what the next session loads.
BUFFER_COUNT = 15
BUFFER_MIN = 1
BUFFER_MAX = 50

BUFFER_FILE = os.path.join(
    os.path.expanduser("~"),
    ".serialkit_buffers.json"
)

# Where the buffers lived before the script was renamed
LEGACY_BUFFER_FILE = os.path.join(
    os.path.expanduser("~"),
    ".serial_highligher_buffers.json"
)

ESCAPE_CHARS = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "e": "\x1b",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
}


def unescape(text):
    """Turn \\n, \\r, \\t, \\e and \\xNN into the characters they name."""

    out = []
    index = 0

    while index < len(text):

        char = text[index]

        if char != "\\" or index + 1 >= len(text):
            out.append(char)
            index += 1
            continue

        marker = text[index + 1]

        if marker == "x" and index + 3 < len(text):

            try:
                out.append(chr(int(text[index + 2:index + 4], 16)))
                index += 4
                continue
            except ValueError:
                pass

        if marker in ESCAPE_CHARS:
            out.append(ESCAPE_CHARS[marker])
            index += 2
            continue

        out.append(char)
        index += 1

    return "".join(out)


def buffer_file(path=None):
    """The buffer file in use: whatever was named, or the usual one."""

    return os.path.expanduser(path) if path else BUFFER_FILE


def ensure_buffer_file(path=None):
    """
    Create the buffer file if it is not there yet.

    Returns the path when a file was written, None when one already
    existed or could not be written, so a caller can say so once.
    """

    path = buffer_file(path)

    if os.path.exists(path):
        return None

    # A named file that does not exist yet starts out as empty slots
    if save_buffers([""] * BUFFER_COUNT, None, path):
        return path

    return None


# The window's three toggles. They live in the buffer file next to the
# slots, not in the settings: a file is then a whole set of commands
# with the way they are meant to be sent, and naming another one with
# --buffers brings its own toggles along.
BUFFER_FLAG_DEFAULTS = {
    "enter": True,        # append \r\n
    "escapes": True,      # interpret \n \t \xNN
    "close": True,        # close the window after a send
}


def buffer_flags(stored=None):
    """The toggles from a file, with anything missing filled in."""

    flags = dict(BUFFER_FLAG_DEFAULTS)

    if isinstance(stored, dict):

        for name in BUFFER_FLAG_DEFAULTS:

            if name in stored:
                flags[name] = bool(stored[name])

    return flags


def load_buffers(path=BUFFER_FILE):
    """
    Read a buffer file and return its slots and its toggles.

    Two shapes are read: the current one, {"slots": [...],
    "flags": {...}}, and the bare list written by earlier versions.
    """

    items = []
    flags = None

    # Fall back to the pre-rename file, once
    if path == BUFFER_FILE and not os.path.exists(path):

        if os.path.exists(LEGACY_BUFFER_FILE):
            path = LEGACY_BUFFER_FILE

    try:

        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)

        if isinstance(stored, dict):
            flags = stored.get("flags")
            stored = stored.get("slots") or []

        items = [str(item) for item in stored][:BUFFER_MAX]

    except Exception:
        items = []

    # A file that is missing, empty or unreadable starts at the default
    # count; one that holds fewer slots keeps them, since the window is
    # what took them away.
    least = BUFFER_MIN if items else BUFFER_COUNT

    while len(items) < least:
        items.append("")

    return items, buffer_flags(flags)


def save_buffers(items, flags=None, path=BUFFER_FILE):

    try:

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "slots": list(items),
                    "flags": buffer_flags(flags),
                },
                handle,
                indent=2
            )

        return True

    except Exception:
        return False


# The CLI runs the buffer window in its own thread and root, so it can
# still be up when an XMODEM window opens. Both write to the same port,
# so a buffer sent mid-transfer would corrupt it: the window stays open
# but stops sending while the transfer window lives.
OPEN_BUFFER_DIALOGS = []

BUFFER_LOCK = threading.Event()


def lock_buffer_dialogs():
    """
    Stop the buffer windows from sending and return how many are open.

    Only a flag is set here. Each window picks it up from its own event
    loop, which in CLI mode runs in another thread, so no widget is
    touched from the calling thread.
    """

    BUFFER_LOCK.set()

    return len(OPEN_BUFFER_DIALOGS)


def unlock_buffer_dialogs():
    """Let the buffer windows send again."""

    BUFFER_LOCK.clear()


def buffers_locked():

    return BUFFER_LOCK.is_set()


class BufferDialog:
    """Pick, edit and fire one of the ten stored commands."""

    # How often the window checks whether the port has been taken
    LOCK_POLL_MS = 200

    LOCKED_TEXT = "XMODEM open, sending off"

    # Characters the status line is given. Anything longer is cut, so
    # the message cannot decide how wide the window is.
    STATUS_WIDTH = 30

    # One width for Reload, Save as and Save. It is the widest label
    # rather than each button's own size, which keeps the row even.
    BUTTON_WIDTH = 7

    def __init__(
        self,
        send,
        parent=None,
        path=BUFFER_FILE,
        title="Buffers"
    ):

        self.send_bytes = send
        self.path = path

        # Slots and toggles both come out of the file and both go back
        # into it, so a file named with --buffers is a set of commands
        # with the way they are meant to be sent.
        items, self.flags = load_buffers(path)

        # What the slot box holds, kept across rebuilds
        self.slot_text = ""

        self.owns_root = parent is None

        if self.owns_root:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(parent)

        # The file is in the title: it costs no height, and a session
        # started with --buffers is otherwise indistinguishable.
        self.title = title
        self.retitle()
        self.root.resizable(True, True)
        self.root.attributes("-topmost", True)

        self.frame = None

        self.build(items)
        self.fit()

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        if not self.owns_root:
            self.root.transient(parent)
            self.root.grab_set()

        self.locked = None
        self.lock_poll = None

        OPEN_BUFFER_DIALOGS.append(self)

        self.watch_lock()

    def retitle(self):
        """Name the file being edited in the title bar."""

        self.root.title(f"{self.title} - {os.path.basename(self.path)}")

    def watch_lock(self):
        """Follow the port lock: an XMODEM window turns sending off."""

        locked = buffers_locked()

        if locked != self.locked:

            self.locked = locked
            self.show_lock(locked)

        self.lock_poll = self.root.after(
            self.LOCK_POLL_MS, self.watch_lock
        )

    def show_lock(self, locked):
        """Grey out the fields and the Send buttons while locked."""

        state = ["disabled"] if locked else ["!disabled"]

        for widget in self.entries + self.send_buttons:

            try:
                widget.state(state)
            except Exception:
                pass

        # This window is always on top, which would bury the transfer
        # window it is waiting for, so it gives that up while locked.
        try:
            self.root.attributes("-topmost", not locked)
        except Exception:
            pass

        if locked:
            self.note(self.LOCKED_TEXT)
        elif self.status_var.get() == self.LOCKED_TEXT:
            self.note("")

    def fit(self):
        """
        Size the window to the rows it has now.

        The natural size is also the smallest useful one: the window can
        be widened for long commands, but not squeezed below its layout.
        Dropping the old floor first is what lets it shrink when slots
        are taken away.

        It ends on a fixed geometry on purpose. Left to size itself, the
        window would grow the moment a long status message arrived, and
        never shrink back; a message is clipped instead. A width the
        user dragged out is kept.
        """

        self.root.update_idletasks()

        stretched = self.root.winfo_width()

        self.root.minsize(1, 1)
        self.root.geometry("")

        self.root.update_idletasks()

        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()

        self.root.minsize(width, height)
        self.root.geometry(f"{max(width, stretched)}x{height}")

    def rebuild(self, items, note=""):
        """Keep the slots, then draw the window again."""

        self.store(items)
        self.redraw(items, note)

    def reload(self):
        """
        Read the file again, dropping whatever was typed since.

        Useful when the file was changed elsewhere, or to walk back an
        edit: the window is only ever a view of the file.
        """

        items, self.flags = load_buffers(self.path)

        self.redraw(items, "Reloaded from file")

    def redraw(self, items, note=""):
        """Build the window over again from a list of slots."""

        self.frame.destroy()

        self.build(items)
        self.fit()

        # The fresh widgets know nothing of the port lock yet
        self.locked = buffers_locked()
        self.show_lock(self.locked)

        if note and not self.locked:
            self.note(note)

    def target_slot(self, count):
        """
        The slot the box names.

        (True, number) for a slot, (True, None) for an empty box, which
        means the end of the list, and (False, None) for junk.
        """

        text = self.slot_var.get().strip()

        if not text:
            return True, None

        try:
            slot = int(text)
        except ValueError:
            self.note("Slot number, or empty for last")
            return False, None

        if not 1 <= slot <= count:
            self.note(f"No slot {slot}, there are {count}")
            return False, None

        return True, slot

    def add_slot(self):
        """A new slot after the one named, or at the end."""

        items = self.items()

        if len(items) >= BUFFER_MAX:
            self.note(f"{BUFFER_MAX} slots is the limit")
            return

        ok, slot = self.target_slot(len(items))

        if not ok:
            return

        if slot is None:
            items.append("")
            added = len(items)
        else:
            items.insert(slot, "")
            added = slot + 1

        self.rebuild(items, f"Slot {added} added")

    def remove_slot(self):
        """The slot named, or the last one."""

        items = self.items()

        if len(items) <= BUFFER_MIN:
            self.note("The last slot has to stay")
            return

        ok, slot = self.target_slot(len(items))

        if not ok:
            return

        index = len(items) - 1 if slot is None else slot - 1

        dropped = items.pop(index)
        note = f"Slot {index + 1} removed"

        if dropped:
            note += ", text and all"

        self.rebuild(items, note)

    def build(self, items):

        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        self.frame = frame
        self.count = len(items)

        self.vars = []
        self.entries = []
        self.send_buttons = []

        for index in range(self.count):

            row = index

            ttk.Label(frame, text=f"{index + 1}").grid(
                row=row, column=0, sticky="w", padx=(0, 6)
            )

            variable = tk.StringVar(master=self.root, value=items[index])
            self.vars.append(variable)

            entry = ttk.Entry(frame, textvariable=variable, width=46)
            entry.grid(row=row, column=1, sticky="we", pady=1)

            entry.bind(
                "<Return>",
                lambda event, slot=index: self.send_slot(slot)
            )

            self.entries.append(entry)

            button = ttk.Button(
                frame,
                text="Send",
                width=6,
                command=lambda slot=index: self.send_slot(slot)
            )
            button.grid(row=row, column=2, padx=(6, 0))

            self.send_buttons.append(button)

        options = ttk.Frame(frame)
        options.grid(
            row=self.count, column=0, columnspan=3,
            sticky="w", pady=(10, 0)
        )

        self.enter_var = tk.BooleanVar(
            master=self.root, value=self.flags["enter"]
        )
        self.escape_var = tk.BooleanVar(
            master=self.root, value=self.flags["escapes"]
        )
        self.close_var = tk.BooleanVar(
            master=self.root, value=self.flags["close"]
        )

        for name, variable in (
            ("enter", self.enter_var),
            ("escapes", self.escape_var),
            ("close", self.close_var),
        ):
            variable.trace_add(
                "write",
                lambda *ignored, flag=name: self.flag_changed(flag)
            )

        check_button(
            options,
            text="Append Enter",
            variable=self.enter_var
        ).pack(side="left")

        check_button(
            options,
            text=r"Interpret \n \t \xNN",
            variable=self.escape_var
        ).pack(side="left", padx=(12, 0))

        check_button(
            options,
            text="Close after send",
            variable=self.close_var
        ).pack(side="left", padx=(12, 0))

        # The status shares the button row: it is one short line, and a
        # row of its own only added height.
        bottom = ttk.Frame(frame)
        bottom.grid(
            row=self.count + 1, column=0, columnspan=3,
            sticky="we", pady=(8, 0)
        )

        # No Close button: the window's own X does that. Reload is what
        # is actually wanted next to Save. The three share one width and
        # a thin gap: at their natural sizes they crowd out the slot box
        # and the status line on a window at its smallest.
        for text, command in (
            ("Reload", self.reload),
            ("Save as", self.save_as),
            ("Save", self.save),
        ):
            ttk.Button(
                bottom, text=text, width=self.BUTTON_WIDTH, command=command
            ).pack(side="right", padx=(3, 0))

        # Slots can be added and taken away; the file keeps the count.
        # The box says which one: - drops it, + puts a new one after it,
        # and an empty box works on the end of the list. The caption is
        # what ties the three of them together.
        slots = ttk.Frame(bottom)
        slots.pack(side="left", padx=(0, 12))

        ttk.Label(slots, text="Slot").pack(side="left", padx=(0, 4))

        self.slot_var = tk.StringVar(master=self.root, value=self.slot_text)

        self.slot_var.trace_add(
            "write",
            lambda *ignored: setattr(
                self, "slot_text", self.slot_var.get()
            )
        )

        ttk.Entry(slots, textvariable=self.slot_var, width=3).pack(
            side="left"
        )

        ttk.Button(
            slots, text="-", width=2, command=self.remove_slot
        ).pack(side="left", padx=(4, 0))

        ttk.Button(
            slots, text="+", width=2, command=self.add_slot
        ).pack(side="left", padx=(4, 0))

        self.status_var = tk.StringVar(master=self.root, value="")

        # Packed last of the row, so Save and Close keep their space and
        # a long message is clipped rather than pushing them out.
        ttk.Label(
            bottom,
            textvariable=self.status_var,
            anchor="w"
        ).pack(side="left", fill="x", expand=True)

        frame.columnconfigure(1, weight=1)

        # Extra height goes to the slot rows, so a stretched window keeps
        # its options and buttons at the bottom.
        for index in range(self.count):
            frame.rowconfigure(index, weight=1)

    def flag_changed(self, name):

        self.flags = {
            "enter": self.enter_var.get(),
            "escapes": self.escape_var.get(),
            "close": self.close_var.get(),
        }

        # A toggle is written straight away, so the file opens the way
        # it was left even if the window is killed rather than closed.
        self.store()

    def store(self, items=None):
        """Write the slots and the toggles to the buffer file."""

        return save_buffers(
            self.items() if items is None else items,
            self.flags,
            self.path
        )

    def note(self, text):
        """Put a message on the status line, cut to the width it has."""

        if len(text) > self.STATUS_WIDTH:
            text = text[:self.STATUS_WIDTH - 3] + "..."

        self.status_var.set(text)

    def items(self):

        return [variable.get() for variable in self.vars]

    def save(self):

        if self.store():
            self.note("Saved")
        else:
            self.note(f"Could not write {os.path.basename(self.path)}")

    def save_as(self):
        """
        Write the slots to another file and work on that one from now on.

        The window is a view of one file, so naming a new one moves the
        view with it: Save and Reload follow, and the title says which.
        Copying a set of commands is then Save as and nothing else.
        """

        # It opens on the file in use, so Save as starts as a copy of
        # it rather than somewhere unrelated.
        where = {}

        folder = os.path.dirname(self.path)

        if folder:
            where["initialdir"] = folder

        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save buffers as",
            defaultextension=".json",
            initialfile=os.path.basename(self.path),
            filetypes=[
                ("JSON files", "*.json"),
                ("All files", "*.*")
            ],
            **where
        )

        if not filename:
            return

        if not save_buffers(self.items(), self.flags, filename):
            self.note(f"Could not write {os.path.basename(filename)}")
            return

        self.path = filename
        self.retitle()

        self.note(f"Saved {os.path.basename(filename)}")

    def send_slot(self, index):

        if buffers_locked():
            self.note(self.LOCKED_TEXT)
            return

        text = self.vars[index].get()

        if not text:
            self.note(f"Slot {index + 1} is empty")
            return

        if self.escape_var.get():
            text = unescape(text)

        if self.enter_var.get():
            text += "\r\n"

        try:
            self.send_bytes(text.encode("utf-8"))
        except Exception as e:
            self.note(f"Send failed: {e}")
            return

        self.store()

        self.note(f"Sent slot {index + 1}")

        if self.close_var.get():
            self.close()

    def close(self):

        if self in OPEN_BUFFER_DIALOGS:
            OPEN_BUFFER_DIALOGS.remove(self)

        # The poll would otherwise fire once more on a dead window
        if self.lock_poll is not None:

            try:
                self.root.after_cancel(self.lock_poll)
            except Exception:
                pass

            self.lock_poll = None

        self.store()

        try:

            if not self.owns_root:
                self.root.grab_release()

            self.root.destroy()

        except Exception:
            pass

    def run(self):

        if self.owns_root:
            self.root.mainloop()
        else:
            self.root.wait_window(self.root)


# ============================================================
# CLI front end
# ============================================================

class SerialCli:
    """
    Same serial handling and same highlight rules as the GUI, drawn
    with ANSI colours in the terminal instead of a Text widget.

    The open line is redrawn on every chunk, so a rule matches as soon
    as the whole word has arrived even though the first characters were
    already printed.
    """

    QUIT_KEY = "\x1d"          # Ctrl+]
    SEND_KEY = "\x14"          # Ctrl+T, start an XMODEM upload
    BUFFER_KEY = "\x02"        # Ctrl+B, open the command buffers
    INPUT_COLOR_KEY = "\x19"   # Ctrl+Y, turn the input colour on or off
    RULES_KEY = "\x12"         # Ctrl+R, open the highlight rules

    OPTION_KEY = "\x0f"        # Ctrl+O, then one letter, toggles a flag

    # Ctrl+G shows the key list. Not Ctrl+H: that byte is what the
    # Backspace key sends through msvcrt on Windows.
    HELP_KEY = "\x07"

    def __init__(
        self,
        port,
        baud,
        timestamp=False,
        color=True,
        highlight=True,
        local_echo=False,
        device_colors=True,
        send_path=None,
        block_size=1024,
        buffer_ui="auto",
        transfer_ui="auto",
        text_transfer=False,
        input_color=INPUT_COLOR,
        config_path=CONFIG_FILE,
        buffer_path=None,
        rule_profile=DEFAULT_RULE_PROFILE,
        reconnect=True
    ):

        self.port = port
        self.baud = baud
        self.timestamp = timestamp
        self.color = color

        # The three kinds of colour are independent. color is the master
        # switch behind --no-color; highlight is the rules alone.
        self.highlight = highlight and color
        self.local_echo = local_echo
        self.device_colors = device_colors and color

        self.send_path = send_path
        self.block_size = block_size

        # Window or prompt, per feature. text_transfer is the older
        # --text-transfer, which only ever meant "prompt".
        self.buffer_ui = ui_choice(buffer_ui)
        self.transfer_ui = ui_choice(transfer_ui)

        if text_transfer and self.transfer_ui == "auto":
            self.transfer_ui = "cli"

        # Said once a session, not once a window that cannot open
        self.warned_no_tk = False

        self.config_path = config_path
        self.buffer_path = buffer_file(buffer_path)

        # Only for the Ctrl+G list and the rule window's buttons
        self.rule_profile = rule_profile or DEFAULT_RULE_PROFILE
        self.reconnect = reconnect

        self.serial = None
        self.running = False

        self.lock = threading.Lock()

        # Held while an XMODEM transfer owns the port
        self.pause_reader = threading.Event()

        # So "not connected" is said once, not once per keystroke
        self.warned_offline = False

        # Set by the POSIX key loop so prompts can leave raw mode
        self.raw_fd = None
        self.raw_saved = None

        # Set by the Windows key loop, same idea: the console mode as we
        # found it, so prompts and exit can put it back
        self.console_handle = None
        self.console_saved = None

        # Kept so the toggle can put it back
        self.configured_input_color = input_color if color else None
        self.input_color = self.configured_input_color

        # Waiting for one more key after Ctrl+O
        self.pending_option = False

        # keep_sgr is always on: the colours have to be recorded even
        # while they are hidden, or turning them back on mid-session
        # would leave the lines already on screen plain.
        self.assembler = LineAssembler(
            keep_sgr=True,
            track_input=bool(self.input_color)
        )

        self.line_prefix = ""

    # --------------------------------------------------------
    # Rendering
    # --------------------------------------------------------

    def render(self, text, as_input=False):

        with self.lock:

            for line, styles, inputs in self.assembler.feed(text, as_input):

                self.write_line(line, styles, inputs)

            self.redraw()

            sys.stdout.flush()

    def timestamp_prefix(self):

        if not self.timestamp:
            return ""

        if not self.line_prefix:
            self.line_prefix = datetime.now().strftime(
                "[%Y-%m-%d %H:%M:%S] "
            )

        return self.line_prefix

    def redraw(self, line=None, styles=None, inputs=None):
        """Repaint the unterminated line in place."""

        column = None

        if line is None:
            line, styles, inputs = self.assembler.snapshot()

            # Only the open line carries a cursor. A device erases with
            # backspace-space-backspace, which leaves a blank at the end
            # of the buffer, so the text must be printed in full and the
            # cursor then walked back to where the device left it.
            column = self.assembler.col

        if not line:

            # Nothing on the line yet: no prefix, and no timestamp taken
            # for a line that has not started arriving.
            sys.stdout.write("\r\x1b[2K")
            return

        if self.color:

            body = colorize(
                line,
                styles if self.device_colors else None,
                inputs,
                self.input_color,
                rules=self.highlight
            )

        else:
            body = line

        sys.stdout.write("\r\x1b[2K" + self.timestamp_prefix() + body)

        if column is not None and column < len(line):
            sys.stdout.write("\x1b[%dD" % (len(line) - column))

    def write_line(self, line, styles=None, inputs=None):

        self.redraw(line, styles, inputs)

        sys.stdout.write("\r\n")

        self.line_prefix = ""

    def write_notice(self, text):

        with self.lock:

            sys.stdout.write("\r\x1b[2K" + self.styled_notice(text) + "\r\n")

            self.redraw()

            sys.stdout.flush()

    # --------------------------------------------------------
    # Serial
    # --------------------------------------------------------

    def read_serial(self):

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        while self.running:

            try:

                # An XMODEM transfer needs the port to itself
                if self.pause_reader.is_set():
                    time.sleep(0.05)
                    continue

                if not self.serial or not self.serial.is_open:

                    if not self.wait_for_port():
                        break

                    decoder = codecs.getincrementaldecoder("utf-8")(
                        errors="replace"
                    )

                    continue

                data = self.serial.read(self.serial.in_waiting or 1)

                if not data:
                    continue

                text = decoder.decode(data)

                if text:
                    self.render(text)

            except Exception as e:

                if not self.running:
                    break

                self.port_lost(e)

    def port_lost(self, error):
        """The port died under us. Drop it, and wait for it to return."""

        self.write_notice(f"[Serial error: {error}]")

        self.close_port()

        if not self.reconnect:

            self.write_notice(f"[{self.port} lost. Closing the session.]")

            self.running = False
            return

        self.write_notice(
            f"[{self.port} lost - waiting for it to come back. "
            f"Ctrl+] quits, the log above is kept.]"
        )

    def wait_for_port(self):
        """
        Poll until the port can be opened again.

        Power-cycling a board makes its USB port disappear and come back,
        which would otherwise mean restarting and losing everything
        already on screen.
        """

        if not self.reconnect:
            return False

        attempts = 0

        # Ctrl+O r during the wait gives up on the port and ends the
        # session, so the mode is checked on every turn, not just once.
        while self.running and self.reconnect:

            if self.pause_reader.is_set():
                time.sleep(0.05)
                continue

            if port_is_present(self.port):

                try:

                    self.serial = open_port(self.port, self.baud)

                    self.write_notice(
                        f"--- Reconnected to {self.port} "
                        f"@ {self.baud} 8N1 ---"
                    )

                    return True

                except Exception as e:

                    # It is listed but not ready yet, which is normal for
                    # a second or two after the device enumerates.
                    if attempts % 20 == 0:
                        self.write_notice(f"[{self.port}: {e}]")

            attempts += 1

            time.sleep(0.25)

        if self.running and not self.reconnect:

            self.write_notice(
                f"[stopped waiting for {self.port}. Closing the session.]"
            )

            self.running = False

        return False

    def send(self, data):

        if not self.serial:

            if not self.warned_offline:

                self.write_notice(
                    f"[not connected - waiting for {self.port}]"
                )

                self.warned_offline = True

            return

        self.warned_offline = False

        try:
            self.serial.write(data)

        except Exception as e:
            self.write_notice(f"[TX error: {e}]")

    # --------------------------------------------------------
    # XMODEM
    # --------------------------------------------------------

    def styled_notice(self, text):
        """Italic and dimmed, so our own messages stand apart."""

        if not self.color or not text:
            return text

        return "\x1b[3m" + ansi_code(NOTICE_COLOR, None) + text + RESET

    def transfer_status(self, message, progress=False):

        with self.lock:

            sys.stdout.write("\r\x1b[2K" + self.styled_notice(message))

            if not progress:
                sys.stdout.write("\r\n")

            sys.stdout.flush()

    # ESC or Ctrl+C abort a running transfer. In raw mode Ctrl+C is
    # delivered as a byte rather than a signal, so it is checked here.
    ABORT_KEYS = ("\x1b", "\x03")

    def transfer_cancelled(self):

        try:

            if os.name == "nt":

                import msvcrt

                while msvcrt.kbhit():

                    key = msvcrt.getwch()

                    if key in ("\x00", "\xe0"):
                        msvcrt.getwch()
                        continue

                    if key in self.ABORT_KEYS:
                        return True

                return False

            import select

            while select.select([sys.stdin], [], [], 0)[0]:

                data = os.read(sys.stdin.fileno(), 1)

                if not data:
                    return False

                if data.decode("utf-8", "replace") in self.ABORT_KEYS:
                    return True

            return False

        except Exception:
            return False

    def cooked_input(self, prompt, strip=True):
        """
        Read a line from the user, leaving raw mode while we do.

        strip=False keeps the spaces around the answer, for the places
        where the answer is text for the device rather than a command.
        """

        if self.raw_fd is not None:

            import termios

            termios.tcsetattr(
                self.raw_fd,
                termios.TCSADRAIN,
                self.raw_saved
            )

        # A prompt is ours, not the device's, so Ctrl+C goes back to
        # meaning "give up on this question" while it is open.
        self.release_console()

        try:

            sys.stdout.write("\r\x1b[2K" + prompt)
            sys.stdout.flush()

            line = sys.stdin.readline()

            return line.strip() if strip else line.rstrip("\r\n")

        except (EOFError, KeyboardInterrupt):
            return ""

        finally:

            sys.stdout.write("\r\n")
            sys.stdout.flush()

            if self.raw_fd is not None:

                import tty

                tty.setraw(self.raw_fd)

            self.hold_console()

    def prompt_transfer(self):

        if self.use_window(self.transfer_ui):
            self.dialog_transfer()
            return

        self.text_prompt_transfer()

    def dialog_transfer(self, initial_path=None, autostart=False):
        """Run the transfer in its own window, keeping the terminal clean."""

        self.write_notice("--- XMODEM window opened ---")

        try:

            dialog = XmodemDialog(
                self.serial,
                pause_event=self.pause_reader,
                block_size=self.block_size,
                initial_path=initial_path,
                autostart=autostart,
                title=f"XMODEM send - {self.port}"
            )

            if dialog.locked_buffers:
                self.write_notice("--- buffer window disabled for XMODEM ---")

            dialog.run()

        except Exception as e:

            self.pause_reader.clear()
            self.write_notice(f"[XMODEM window failed: {e}]")
            self.text_prompt_transfer()
            return

        finally:
            unlock_buffer_dialogs()
            self.flush_keyboard()

        if dialog.result:
            self.write_notice("--- XMODEM transfer complete ---")
        else:
            self.write_notice("--- XMODEM window closed ---")

    # --------------------------------------------------------
    # Command buffers
    # --------------------------------------------------------

    def show_help(self):
        """The key list, plus what this session is actually running with."""

        lines = [
            f"--- {PROGRAM} keys ---",
            "  Ctrl+]   quit",
            "  Ctrl+T   send a file with XMODEM",
            "  Ctrl+B   command buffers",
            "  Ctrl+R   highlight rules",
            "  Ctrl+Y   Typed text colour on/off",
            "  Ctrl+O   flag mode, stays open: t Timestamp,",
            "           d Device ANSI, i Typed text, c Regex highlight,",
            "           e Local echo, r Reconnect, b Buffers window or",
            "           prompt, x XMODEM window or prompt,",
            "           w write settings, Enter or ESC leaves",
            "  Ctrl+G   this list",
            "  Ctrl+C   goes to the device, it does not quit",
            "  ESC or Ctrl+C aborts a running transfer",
            "--- this session (letter = the Ctrl+O key) ---",
            f"  port                {self.port} @ {self.baud} 8N1",
            f"  Timestamp       t   [{self.on_off(self.timestamp)}]",
            f"  Regex highlight c   [{self.on_off(self.highlight)}]",
            f"  Device ANSI     d   [{self.on_off(self.device_colors)}]",
            f"  Typed text      i   [{self.on_off(self.input_color)}]"
            f" {self.input_color or ''}".rstrip(),
            f"  Local echo      e   [{self.on_off(self.local_echo)}]",
            f"  Reconnect       r   [{self.on_off(self.reconnect)}]",
            f"  Buffers         b   [{self.ui_label(self.buffer_ui)}]",
            f"  XMODEM          x   [{self.ui_label(self.transfer_ui)}]",
            f"  XMODEM blocks       "
            f"{'1K' if self.block_size == 1024 else '128 byte'}",
            f"  Highlight rules     {len(ACTIVE_RULES)} active"
            f" ({self.rule_profile} profile)",
            f"  settings            {self.config_path}",
            f"  buffers             {self.buffer_path}",
        ]

        for line in lines:
            self.write_notice(line)

    # --------------------------------------------------------
    # Flags that can be flipped mid-session
    # --------------------------------------------------------

    # Keys that leave the option mode rather than toggle something
    OPTION_EXIT_KEYS = ("\x1b", "\r", "\n", "\x0f", "q", "Q")

    def show_options(self):
        """
        The Ctrl+O menu. It stays open, so several flags can be flipped
        in a row, until Enter or ESC closes it.
        """

        for line in [
            "--- Ctrl+O ---",
            f"  t   Timestamp           [{self.on_off(self.timestamp)}]",
            f"  d   Device ANSI         [{self.on_off(self.device_colors)}]",
            f"  i   Typed text          [{self.on_off(self.input_color)}]",
            f"  c   Regex highlight     [{self.on_off(self.highlight)}]",
            f"  e   Local echo          [{self.on_off(self.local_echo)}]",
            f"  r   Reconnect           [{self.on_off(self.reconnect)}]",
            f"  b   Buffers front end   [{self.ui_label(self.buffer_ui)}]",
            f"  x   XMODEM front end    [{self.ui_label(self.transfer_ui)}]",
            "  w   write these settings to the settings file",
            "  Enter or ESC closes. Keys go to the device again after"
            " that.",
        ]:
            self.write_notice(line)

    @staticmethod
    def on_off(value):

        return "on" if value else "off"

    def use_window(self, choice):
        """
        Whether a feature should put up a window or ask in the terminal.

        "gui" and "cli" are the answer outright. "auto" is a window on
        Windows and a prompt on Linux: the terminal session there is as
        often as not an ssh one with no display to put a window on.

        Nothing opens a window without tkinter, whatever was asked for,
        so a Python built without it still runs the whole tool.
        """

        if choice == "cli":
            return False

        if not TK_AVAILABLE:

            if choice == "gui" and not self.warned_no_tk:

                self.warned_no_tk = True

                self.write_notice(
                    "[no tkinter in this Python, so the prompts are "
                    "used instead of the windows]"
                )

            return False

        if choice == "gui":
            return True

        return os.name == "nt"

    def option_summary(self):
        """One line of state, printed after each flag is flipped."""

        return "  ".join([
            f"t[{self.on_off(self.timestamp)}]",
            f"d[{self.on_off(self.device_colors)}]",
            f"i[{self.on_off(self.input_color)}]",
            f"c[{self.on_off(self.highlight)}]",
            f"e[{self.on_off(self.local_echo)}]",
            f"r[{self.on_off(self.reconnect)}]",
            f"b[{self.ui_label(self.buffer_ui)}]",
            f"x[{self.ui_label(self.transfer_ui)}]",
        ])

    def apply_option(self, char):
        """
        Handle one key of the option mode.

        Returns True while the mode should stay open, so a run such as
        Ctrl+O t d i Enter flips three flags without leaving.
        """

        if char in self.OPTION_EXIT_KEYS:

            self.write_notice("[options closed]")
            return False

        action = {
            "t": self.toggle_timestamp,
            "d": self.toggle_device_colors,
            "i": self.toggle_input_color,
            "c": self.toggle_highlight,
            "e": self.toggle_local_echo,
            "r": self.toggle_reconnect,
            "b": self.toggle_buffer_ui,
            "x": self.toggle_transfer_ui,
            "w": self.write_settings,
        }.get(char.lower())

        if not action:

            self.write_notice(
                f"[{char!r} is not an option. Enter or ESC closes.]"
            )
            return True

        action()

        self.write_notice(f"  {self.option_summary()}")

        return True

    def toggle_timestamp(self):

        self.timestamp = not self.timestamp

        # A line already under way keeps the stamp it was given, so the
        # change shows from the next line on.
        self.write_notice(f"[Timestamp {self.on_off(self.timestamp)}]")

    def toggle_device_colors(self):

        if not self.color:

            self.write_notice("[--no-color is set for this session]")
            return

        self.device_colors = not self.device_colors

        self.write_notice(
            f"[Device ANSI {self.on_off(self.device_colors)}]"
        )

    def toggle_highlight(self):
        """The rules only. Device colours and typed text carry on."""

        if not self.color:

            self.write_notice("[--no-color is set for this session]")
            return

        self.highlight = not self.highlight

        self.write_notice(f"[Regex highlight {self.on_off(self.highlight)}]")

    def toggle_local_echo(self):

        self.local_echo = not self.local_echo

        self.write_notice(f"[Local echo {self.on_off(self.local_echo)}]")

    def toggle_reconnect(self):

        self.reconnect = not self.reconnect

        self.write_notice(
            f"[Reconnect {self.on_off(self.reconnect)}]"
            if self.reconnect
            else "[Reconnect off - the session ends if the port is lost]"
        )

    def ui_label(self, choice):
        """
        How a front-end setting reads in the menus.

        "auto" is shown with what it comes to here, so the line says
        which window will actually open.
        """

        if choice == "auto":
            return f"auto/{'gui' if self.use_window(choice) else 'cli'}"

        return choice

    def toggle_buffer_ui(self):
        """Swap the buffers between the window and the prompt."""

        if self.no_windows():
            return

        self.buffer_ui = self.flip_ui(self.buffer_ui)

        self.write_notice(f"[Buffers: {self.ui_label(self.buffer_ui)}]")

    def toggle_transfer_ui(self):
        """Swap XMODEM between the window and the prompt."""

        if self.no_windows():
            return

        self.transfer_ui = self.flip_ui(self.transfer_ui)

        self.write_notice(f"[XMODEM: {self.ui_label(self.transfer_ui)}]")

    def no_windows(self):
        """True, having said so, when there is no tkinter to swap to."""

        if TK_AVAILABLE:
            return False

        self.write_notice(
            "[no tkinter in this Python, so the prompts are the only "
            "front end there is]"
        )

        return True

    def flip_ui(self, choice):
        """
        The other of gui and cli.

        An "auto" is settled first, so the key flips away from whatever
        the session has been doing rather than to a fixed side.
        """

        return "cli" if self.use_window(choice) else "gui"

    def write_settings(self):
        """Keep the flags as they stand now for the next session."""

        config = load_config(self.config_path)

        config.update({
            "port": self.port,
            "baud": self.baud,
            "timestamp": self.timestamp,
            "color": self.color,
            "highlight": self.highlight,
            "device_colors": self.device_colors,
            "input_color": self.configured_input_color,
            "local_echo": self.local_echo,
            "buffer_ui": self.buffer_ui,
            "transfer_ui": self.transfer_ui,
            "xmodem": "128" if self.block_size == 128 else "1k",
            "reconnect": self.reconnect,
            "rule_profile": self.rule_profile,
            "buffers": self.buffer_path,
        })

        if save_config(config, self.config_path):
            self.write_notice(f"[settings written to {self.config_path}]")
        else:
            self.write_notice("[could not write the settings file]")

    def open_rules(self):

        if not TK_AVAILABLE:

            self.write_notice(
                f"[the rule window needs tkinter; edit \"rules\" in "
                f"{self.config_path} instead]"
            )
            return

        try:

            config = load_config(self.config_path)

            profile = config.get("rule_profile") or self.rule_profile

            dialog = HighlightDialog(
                config.get("rules") or default_user_rules(profile),
                lambda rules, chosen: self.rules_applied(
                    config, rules, chosen
                ),
                title=f"Highlight rules - {self.port}",
                profile=profile
            )

            dialog.run()

        except Exception as e:
            self.write_notice(f"[rule window failed: {e}]")

        finally:
            self.flush_keyboard()

    def rules_applied(self, config, rules, profile=None):

        config["rules"] = rules

        if profile:
            config["rule_profile"] = profile
            self.rule_profile = profile

        save_config(config, self.config_path)

        self.write_notice(
            f"[{len([r for r in rules if r.get('pattern')])} rules applied"
            f" - {profile or config.get('rule_profile')} profile]"
        )

    def toggle_input_color(self):

        if self.input_color:

            self.input_color = None
            self.assembler.track_input = False
            self.assembler.echo_queue.clear()

            self.write_notice("[Typed text colour off]")
            return

        if not self.configured_input_color:

            self.write_notice(
                "[Typed text colour is disabled for this session]"
            )
            return

        self.input_color = self.configured_input_color
        self.assembler.track_input = True

        self.write_notice("[Typed text colour on]")

    def send_typed(self, data):
        """Send bytes and expect their echo, so they get the input colour."""

        text = data.decode("utf-8", "replace")

        if "\x1b" in text:
            self.assembler.expect_redraw()
        else:
            self.assembler.expect_echo(text)

        self.send(data)

    def open_buffers(self):
        """
        The buffers, in a window or at a prompt.

        Which one is --buffer-ui, and by default the platform: a window
        on Windows, a prompt on Linux. The two are the same buffers out
        of the same file, so the choice is only how they are worked on.
        """

        if self.use_window(self.buffer_ui):

            def run_dialog():
                try:
                    dialog = BufferDialog(
                        self.send_typed,
                        path=self.buffer_path,
                        title=f"Buffers - {self.port}"
                    )
                    dialog.run()
                except Exception as e:
                    self.write_notice(f"[Buffer window failed: {e}]")

            threading.Thread(target=run_dialog, daemon=True).start()
            return

        self.text_buffers()

    # The terminal buffer manager's commands, for the prompt and the
    # help line. A bare number is a send, so the common case is one
    # keystroke and Enter.
    BUFFER_COMMANDS = (
        "N or s N send, e N [text] edit, a [N] add, d [N] del,"
        " l list, f flags, q quit"
    )

    def text_buffers(self):
        """
        The buffers from the terminal: list, add, edit, delete, send.

        The file is read once and written back after every change, so a
        session that is killed still leaves the slots as they were last
        seen.
        """

        items, flags = load_buffers(self.buffer_path)

        self.write_notice(f"--- Buffers - {self.buffer_path} ---")
        self.list_buffers(items, flags)

        while True:

            answer = self.cooked_input("buffers> ").strip()

            if not answer:
                continue

            word, _, rest = answer.partition(" ")
            word = word.lower()
            rest = rest.strip()

            if word in ("q", "quit", "x", "exit"):
                break

            if word in ("l", "list", "ls"):
                self.list_buffers(items, flags)
                continue

            if word in ("?", "h", "help"):
                self.write_notice(f"  {self.BUFFER_COMMANDS}")
                continue

            if word in ("f", "flags"):
                self.buffer_flag_command(rest, items, flags)
                continue

            if word in ("a", "add"):
                self.buffer_add(rest, items, flags)
                continue

            if word in ("d", "del", "delete", "rm"):
                self.buffer_delete(rest, items, flags)
                continue

            if word in ("e", "edit"):
                self.buffer_edit(rest, items, flags)
                continue

            # Everything else is a send, whether or not it was spelled
            # with the s: "3" and "s 3" are the same request.
            if word in ("s", "send"):
                target = rest
            else:
                target = answer

            if self.buffer_send(target, items, flags) and flags["close"]:
                break

    def list_buffers(self, items, flags):
        """The slots as they stand, and how a send would be dressed."""

        for index, text in enumerate(items):
            self.write_notice(f"  {index + 1}: {text or '(empty)'}")

        self.write_notice(
            f"  flags: enter {self.on_off(flags['enter'])},"
            f" escapes {self.on_off(flags['escapes'])},"
            f" close {self.on_off(flags['close'])}"
        )
        self.write_notice(f"  {self.BUFFER_COMMANDS}")

    def buffer_slot(self, text, items, allow_blank=False):
        """
        A slot number from what was typed, or None if it was no good.

        A blank is a slot of its own for add and delete, which both have
        somewhere sensible to go without one; every other command needs
        a number and says so.
        """

        text = text.strip()

        if not text:

            if allow_blank:
                return "blank"

            self.write_notice("[Which slot? e.g. e 3, or e 3 reboot]")
            return None

        try:
            slot = int(text)
        except ValueError:
            self.write_notice(f"[Not a slot number: {text}]")
            return None

        if not 1 <= slot <= len(items):
            self.write_notice(f"[No slot {slot}, there are {len(items)}]")
            return None

        return slot

    def store_buffers(self, items, flags, note):
        """Write the file back and say what changed, or why it did not."""

        if save_buffers(items, flags, self.buffer_path):
            self.write_notice(f"[{note}]")
        else:
            self.write_notice(f"[{note}, but the file could not be written]")

    def buffer_edit(self, rest, items, flags):
        """
        Replace one slot's text, in one line or at a prompt.

        "e 1 login root" writes the slot there and then; "e 1" shows
        what is in it and asks. The prompt is the one that keeps the
        spaces around the text, since the line here has already been
        split on them.
        """

        number, _, inline = rest.partition(" ")

        slot = self.buffer_slot(number, items)

        if slot is None:
            return

        inline = inline.strip()

        if inline:
            items[slot - 1] = inline
            self.store_buffers(items, flags, f"Slot {slot} saved")
            return

        current = items[slot - 1]

        self.write_notice(f"  {slot}: {current or '(empty)'}")

        # Leading and trailing spaces are kept: a command that ends in
        # one is unusual but it is not ours to throw away.
        text = self.cooked_input(
            f"Slot {slot} (Enter keeps it, - clears it): ",
            strip=False
        )

        if not text:
            self.write_notice("[Unchanged]")
            return

        if text.strip() == "-":
            items[slot - 1] = ""
            self.store_buffers(items, flags, f"Slot {slot} cleared")
            return

        items[slot - 1] = text
        self.store_buffers(items, flags, f"Slot {slot} saved")

    def buffer_add(self, rest, items, flags):
        """A new empty slot after the one named, or at the end."""

        if len(items) >= BUFFER_MAX:
            self.write_notice(f"[{BUFFER_MAX} slots is the limit]")
            return

        slot = self.buffer_slot(rest, items, allow_blank=True)

        if slot is None:
            return

        if slot == "blank":
            items.append("")
            added = len(items)
        else:
            items.insert(slot, "")
            added = slot + 1

        self.store_buffers(items, flags, f"Slot {added} added")

    def buffer_delete(self, rest, items, flags):
        """Drop the slot named, or the last one."""

        if len(items) <= BUFFER_MIN:
            self.write_notice("[The last slot has to stay]")
            return

        slot = self.buffer_slot(rest, items, allow_blank=True)

        if slot is None:
            return

        index = len(items) - 1 if slot == "blank" else slot - 1

        dropped = items.pop(index)
        note = f"Slot {index + 1} removed"

        if dropped:
            note += ", text and all"

        self.store_buffers(items, flags, note)

    def buffer_flag_command(self, rest, items, flags):
        """Flip one of the file's toggles, or show them all."""

        name = rest.strip().lower()

        if not name:
            self.list_buffers(items, flags)
            return

        for known in BUFFER_FLAG_DEFAULTS:

            if known.startswith(name):
                flags[known] = not flags[known]
                self.store_buffers(
                    items,
                    flags,
                    f"{known} {self.on_off(flags[known])}"
                )
                return

        self.write_notice(
            f"[No such flag: {name}."
            f" Try {', '.join(BUFFER_FLAG_DEFAULTS)}]"
        )

    def buffer_send(self, rest, items, flags):
        """Send one slot to the device. True if something went out."""

        # A transfer owns the port, so a buffer sent mid-XMODEM would
        # land in the middle of a block.
        if buffers_locked():
            self.write_notice("[A transfer is running, nothing sent]")
            return False

        slot = self.buffer_slot(rest, items)

        if slot is None:
            return False

        text = items[slot - 1]

        if not text:
            self.write_notice(f"[Slot {slot} is empty]")
            return False

        # The file's own toggles hold here too
        if flags["escapes"]:
            text = unescape(text)

        if flags["enter"]:
            text += "\r\n"

        self.send_typed(text.encode("utf-8"))
        return True

    @staticmethod
    def buffer_index(slot, count):
        """
        Slots are labelled 1..count, matching the window.

        The count comes from the file, since the window can add and
        remove slots.
        """

        if 1 <= slot <= count:
            return slot - 1

        return None

    def flush_keyboard(self):
        """Drop keystrokes typed while the window had focus."""

        try:

            if os.name == "nt":

                import msvcrt

                while msvcrt.kbhit():
                    msvcrt.getwch()

                return

            if self.raw_fd is None:
                return

            import termios

            termios.tcflush(self.raw_fd, termios.TCIFLUSH)

        except Exception:
            pass

    def text_prompt_transfer(self):

        self.write_notice(
            "--- XMODEM send (ESC or Ctrl+C during transfer aborts) ---"
        )

        answer = self.cooked_input("File to send: ")

        if not answer.strip():
            self.transfer_status("XMODEM: cancelled")
            return

        path, tried = resolve_path(answer)

        if not path:

            self.transfer_status("XMODEM: no such file. Tried:")

            for candidate in tried:
                self.transfer_status(f"  {candidate}")

            return

        answer = self.cooked_input(
            "Block size [1] 128 CRC  [2] 1K "
            f"(default {'2' if self.block_size == 1024 else '1'}): "
        )

        if answer == "1":
            block_size = 128
        elif answer == "2":
            block_size = 1024
        else:
            block_size = self.block_size

        self.send_file(path, block_size)

    def send_file(self, path, block_size):

        self.pause_reader.set()

        # A buffer window can be open while the transfer itself runs in
        # the terminal, and both write to the same port, so the window
        # is stopped for the length of the transfer exactly as the
        # transfer window stops it.
        if lock_buffer_dialogs():
            self.write_notice("--- buffer window disabled for XMODEM ---")

        # Let a read() already in flight finish before taking the port
        time.sleep(0.3)

        try:

            sender = XmodemSender(
                self.serial,
                block_size=block_size,
                status=self.transfer_status,
                cancelled=self.transfer_cancelled
            )

            sender.send(path)

        except Exception as e:
            self.transfer_status(f"XMODEM: error: {e}")

        finally:
            unlock_buffer_dialogs()
            self.pause_reader.clear()

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    def run(self):

        enable_windows_vt()

        self.serial = open_port(self.port, self.baud)

        self.running = True

        reader = threading.Thread(target=self.read_serial, daemon=True)
        reader.start()

        self.write_notice(
            f"--- Connected to {self.port} @ {self.baud} 8N1 "
            f"(Ctrl+G for the key list, Ctrl+] to quit, "
            f"Ctrl+C goes to the device) ---"
        )

        # A named buffer file that is not there yet is made now, so
        # Ctrl+B has somewhere to save to.
        created = ensure_buffer_file(self.buffer_path)

        if created:
            self.write_notice(f"[buffer file created: {created}]")

        try:

            if os.name == "nt":
                self.key_loop_windows()
            else:
                self.key_loop_posix()

        finally:

            self.running = False

            closed = self.close_port()

            sys.stdout.write(
                f"\r\n--- Disconnected from {self.port} "
                f"@ {self.baud} 8N1 ---\r\n"
            )
            sys.stdout.flush()

            if not closed:

                # The device was pulled while a read was in flight and
                # the driver will not let go of the handle. Nothing left
                # to tidy up, so leave rather than hang.
                sys.stdout.write(
                    "--- port handle stuck, exiting anyway ---\r\n"
                )
                sys.stdout.flush()

                os._exit(0)

    def close_port(self, timeout=2.0):
        """
        Close the port without risking a hang.

        On Windows a removed USB device can leave close() blocking
        behind a pending read, so it runs on its own thread and is given
        a deadline.
        """

        port, self.serial = self.serial, None

        if port is None:
            return True

        done = threading.Event()

        def shut():

            try:
                port.close()
            except Exception:
                pass

            done.set()

        threading.Thread(target=shut, daemon=True).start()

        return done.wait(timeout)

    def handle_input(self, text):
        """
        Translate a chunk of keyboard input and send it in one write, so
        an escape sequence such as Up (\\x1b[A) reaches the device whole
        instead of byte by byte.

        Returns False when the quit key was pressed.
        """

        out = bytearray()
        echo = []
        quit_now = False
        transfer = False
        buffers = False
        toggle_input = False
        rules = False
        help_wanted = False

        for char in text:

            # While the option mode is open every key is a flag, not
            # something to send on to the device
            if self.pending_option:

                self.pending_option = self.apply_option(char)
                continue

            if char == self.OPTION_KEY:

                self.pending_option = True
                self.show_options()
                continue

            if char == self.QUIT_KEY:
                quit_now = True
                break

            if char == self.SEND_KEY:
                transfer = True
                break

            if char == self.BUFFER_KEY:
                buffers = True
                break

            if char == self.INPUT_COLOR_KEY:
                toggle_input = True
                break

            if char == self.RULES_KEY:
                rules = True
                break

            if char == self.HELP_KEY:
                help_wanted = True
                break

            if char in ("\r", "\n"):
                out += b"\r\n"
                echo.append("\n")

            elif char in ("\x08", "\x7f"):
                out += b"\x08"
                echo.append("\x08")

            else:
                out += char.encode("utf-8")

                if char >= " ":
                    echo.append(char)

        if out:

            self.send(bytes(out))

            if "\x1b" in text:
                self.assembler.expect_redraw()
            else:
                self.assembler.expect_echo(text)

        # An escape sequence is a device-side edit; echoing its
        # characters locally would just print junk.
        if self.local_echo and echo and "\x1b" not in text:
            self.render("".join(echo), as_input=True)

        if transfer:
            self.prompt_transfer()

        if buffers:
            self.open_buffers()

        if toggle_input:
            self.toggle_input_color()

        if rules:
            self.open_rules()

        if help_wanted:
            self.show_help()

        return not quit_now

    def start_pending_send(self):
        """Handle --send, once the keyboard is set up for ESC aborts."""

        if not self.send_path:
            return

        path, tried = resolve_path(self.send_path)

        if path:

            if self.use_window(self.transfer_ui):
                self.dialog_transfer(initial_path=path, autostart=True)
            else:
                self.send_file(path, self.block_size)

        else:

            self.transfer_status("XMODEM: no such file. Tried:")

            for candidate in tried:
                self.transfer_status(f"  {candidate}")

        self.send_path = None

    def take_console(self):
        """
        Stop the Windows console from acting on Ctrl+C.

        Ctrl+C belongs to the device: a target shell wants it to break
        whatever is running there. With ENABLE_PROCESSED_INPUT cleared
        the console stops raising it as a signal and delivers it as a
        plain \x03 byte, like every other key, so Ctrl+] is the only
        way out of the terminal. This is the counterpart of the raw
        mode the POSIX loop sets with tty.setraw.
        """

        self.console_handle, self.console_saved = windows_console_input()

        self.hold_console()

    def hold_console(self):

        if self.console_saved is None:
            return

        set_windows_console_mode(
            self.console_handle,
            self.console_saved & ~ENABLE_PROCESSED_INPUT
        )

    def release_console(self):
        """Put the console mode back, so Ctrl+C works at a prompt again."""

        if self.console_saved is None:
            return

        set_windows_console_mode(self.console_handle, self.console_saved)

    def key_loop_windows(self):

        import msvcrt

        self.take_console()

        try:

            self.start_pending_send()

            while self.running:

                if not msvcrt.kbhit():
                    time.sleep(0.01)
                    continue

                char = msvcrt.getwch()

                # Arrow, function and navigation keys arrive as a prefix
                # plus a code; map the ones a terminal would send.
                if char in ("\x00", "\xe0"):

                    code = msvcrt.getwch()

                    sequence = WINDOWS_SPECIAL_KEYS.get(code)

                    if sequence and not self.handle_input(sequence):
                        break

                    continue

                if not self.handle_input(char):
                    break

        finally:

            self.release_console()

            self.console_handle = None
            self.console_saved = None

    def key_loop_posix(self):

        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)

        try:

            tty.setraw(fd)

            self.raw_fd = fd
            self.raw_saved = saved

            self.start_pending_send()

            while self.running:

                ready, _, _ = select.select([fd], [], [], 0.1)

                if not ready:
                    continue

                # Read the whole burst: the terminal delivers an arrow
                # key as three bytes at once.
                data = os.read(fd, 128)

                if not data:
                    break

                if not self.handle_input(data.decode("utf-8", "replace")):
                    break

        finally:

            self.raw_fd = None
            self.raw_saved = None

            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


# ============================================================
# Port selection
# ============================================================

def list_ports():

    return list(serial.tools.list_ports.comports())


def choose_port():
    """Prompt for a port when none was given on the command line."""

    ports = list_ports()

    if not ports:
        print("No serial ports found.")
        return None

    if len(ports) == 1:
        print(f"Using {ports[0].device} ({ports[0].description})")
        return ports[0].device

    for index, port in enumerate(ports, start=1):
        print(f"  {index}) {port.device}  {port.description}")

    try:
        answer = input("Port number: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    try:
        return ports[int(answer) - 1].device
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


# ============================================================
# Main
# ============================================================

def run_gui(args=None):

    if not TK_AVAILABLE:
        print(
            "tkinter is not available in this Python. "
            "Run with --cli for the terminal front end."
        )
        return 1

    root = tk.Tk()

    app = SerialTerminal(
        root,
        config_path=args.config if args else CONFIG_FILE
    )

    # Options that mean something to the window too. Without this a
    # command line such as "-b 921600" would open the GUI and quietly
    # drop the rate.
    if args and "baud" in args.typed:
        app.baud_var.set(str(args.baud))

    if args and "xmodem" in args.typed:
        app.config["xmodem"] = args.xmodem

    if args and "buffers" in args.typed:
        app.config["buffers"] = args.buffers

    # A profile named on the command line replaces whatever the window
    # last applied, for this run and for the settings it writes back.
    if args and "rule_profile" in args.typed:

        app.config["rule_profile"] = args.rule_profile
        app.config["rules"] = profile_rules(
            args.rule_profile, app.config.get("rules")
        )

        set_user_rules(app.config["rules"])

        app.create_tags()

    def on_close():
        app.save_settings()
        app.disconnect()
        root.destroy()

    root.protocol(
        "WM_DELETE_WINDOW",
        on_close
    )

    root.mainloop()

    return 0


def run_cli(args):

    port = args.port or choose_port()

    if not port:
        return 1

    set_user_rules(session_rules(args))

    cli = SerialCli(
        port=port,
        baud=args.baud,
        timestamp=args.timestamp,
        color=not args.no_color,
        highlight=args.highlight,
        local_echo=args.local_echo,
        device_colors=args.device_colors,
        send_path=args.send,
        block_size=128 if args.xmodem == "128" else 1024,
        buffer_ui=args.buffer_ui,
        transfer_ui=args.transfer_ui,
        input_color=args.input_color,
        config_path=args.config,
        buffer_path=args.buffers,
        reconnect=args.reconnect,
        rule_profile=args.rule_profile
    )

    try:
        cli.run()

    except serial.SerialException as e:

        print(f"Connection error: {e}")
        return 1
    except KeyboardInterrupt:
        pass

    return 0


# Options that only make sense for the terminal front end. Giving one
# of them is taken as asking for --cli.
CLI_ONLY_DESTS = {
    "port",
    "timestamp",
    "no_color",
    "device_colors",
    "input_color",
    "local_echo",
    "send",
    "dialogs",
    "buffer_ui",
    "transfer_ui",
    "text_transfer",
    "reconnect",
    "highlight",
}


def typed_options(parser, argv):
    """Which options actually appear on the command line."""

    argv = list(sys.argv[1:] if argv is None else argv)

    typed = set()

    for action in parser._actions:

        for option in action.option_strings:

            for token in argv:

                if token == option or token.startswith(option + "="):
                    typed.add(action.dest)

    return typed


def parse_args(argv=None):

    parser = argparse.ArgumentParser(
        description=(
            "Serial terminal with regex highlighting. "
            "Runs as a GUI by default, or in the terminal with --cli. "
            f"Defaults are read from {CONFIG_FILE} when it exists."
        )
    )

    parser.add_argument(
        "--config",
        metavar="FILE",
        default=CONFIG_FILE,
        help=f"settings file to read, default {CONFIG_FILE}"
    )

    parser.add_argument(
        "--no-config",
        action="store_true",
        help="ignore the settings file and use the built-in defaults"
    )

    parser.add_argument(
        "--buffers",
        metavar="FILE",
        default=None,          # filled in below, once the settings are read
        help=f"command buffer file, created if it is not there, "
             f"default {BUFFER_FILE}"
    )

    parser.add_argument(
        "--save-config",
        action="store_true",
        help="write the settings in force to the settings file, "
             "then carry on"
    )

    # A throwaway pass so --config / --no-config can steer the defaults
    # below. It carries no -h of its own, or help would print here,
    # before the rest of the options exist.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=CONFIG_FILE)
    pre.add_argument("--no-config", action="store_true")

    early, _ = pre.parse_known_args(
        list(sys.argv[1:] if argv is None else argv)
    )

    config = (
        dict(CONFIG_DEFAULTS)
        if early.no_config
        else load_config(early.config)
    )

    parser.set_defaults(buffers=buffer_file(config["buffers"]))

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--cli",
        action="store_true",
        help="run as a pure CLI terminal (ANSI colours, no window)"
    )

    mode.add_argument(
        "--gui",
        action="store_true",
        help="run the Tk window (default)"
    )

    parser.add_argument(
        "-p", "--port",
        default=config["port"],
        help="serial port, e.g. COM7 or /dev/ttyUSB0 (CLI only)"
    )

    parser.add_argument(
        "-b", "--baud",
        type=int,
        default=config["baud"],
        help=f"baud rate, default {config['baud']}."
             f" Also fills in the window's baud box"
    )

    parser.add_argument(
        "-t", "--timestamp",
        action="store_true",
        default=config["timestamp"],
        help="prefix each line with a timestamp (CLI only)"
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        default=not config["color"],
        help="disable all colouring, highlight rules included (CLI only)"
    )

    parser.add_argument(
        "--color",
        dest="no_color",
        action="store_false",
        help="force colouring on, overriding the settings file (CLI only)"
    )

    colors = parser.add_mutually_exclusive_group()

    colors.add_argument(
        "--device-colors",
        dest="device_colors",
        action="store_true",
        default=config["device_colors"],
        help="keep the colours the device sends (default, CLI only)"
    )

    colors.add_argument(
        "--strip-device-colors",
        dest="device_colors",
        action="store_false",
        help="drop the device's own colours and show only the "
             "highlight rules (CLI only)"
    )

    parser.add_argument(
        "--input-color",
        metavar="HEX",
        default=config["input_color"],
        help=f"colour for text you typed, once the device echoes it "
             f"back, default {config['input_color']} (CLI only)"
    )

    parser.add_argument(
        "--no-input-color",
        dest="input_color",
        action="store_const",
        const=None,
        help="draw typed text like everything else (CLI only)"
    )

    parser.add_argument(
        "--local-echo",
        action="store_true",
        default=config["local_echo"],
        help="echo typed characters locally, for devices "
             "that do not echo (CLI only)"
    )

    parser.add_argument(
        "--send",
        metavar="FILE",
        help="send FILE with XMODEM as soon as the port is open, "
             "then stay in the session (CLI only)"
    )

    parser.add_argument(
        "--xmodem",
        choices=["128", "1k"],
        default=config["xmodem"],
        help="XMODEM block size, default 1k. Both use CRC when the "
             "receiver asks for it. Also used by the transfer window"
    )

    parser.add_argument(
        "--rules",
        dest="rule_profile",
        choices=sorted(RULE_PROFILES),
        default=config["rule_profile"],
        help="which highlight set to load: simple keeps to log words, "
             "extended adds shell syntax and interface names, network "
             "targets IPs/MACs/hex/dBm/voltages, custom is your own "
             "set out of the settings file, empty until you write one "
             "(default: %(default)s)"
    )

    highlight = parser.add_mutually_exclusive_group()

    highlight.add_argument(
        "--highlight",
        dest="highlight",
        action="store_true",
        default=config["highlight"],
        help="colour the text the rules match (default, CLI only)"
    )

    highlight.add_argument(
        "--no-highlight",
        dest="highlight",
        action="store_false",
        help="leave the rules off, keeping the device's own colours and "
             "the input colour (CLI only)"
    )

    reconnect = parser.add_mutually_exclusive_group()

    reconnect.add_argument(
        "--reconnect",
        dest="reconnect",
        action="store_true",
        default=config["reconnect"],
        help="keep the session and wait for the port to come back when "
             "the device is reset or power cycled (default, CLI only)"
    )

    reconnect.add_argument(
        "--no-reconnect",
        dest="reconnect",
        action="store_false",
        help="end the session as soon as the port is lost (CLI only)"
    )

    # The buffers and the transfer each have a window and a prompt.
    # Neither is the poor relation: the window is easier to read, the
    # prompt is the one that works over ssh with no display.
    parser.add_argument(
        "--dialogs",
        choices=UI_CHOICES,
        default=None,
        help="front end for both the buffers and XMODEM: gui for "
             "windows, cli for terminal prompts, auto for a window on "
             "Windows and a prompt on Linux. Shorthand for both of the "
             "next two (CLI only)"
    )

    parser.add_argument(
        "--buffer-ui",
        dest="buffer_ui",
        choices=UI_CHOICES,
        default=config["buffer_ui"],
        help=f"front end for Ctrl+B, the command buffers "
             f"(default {config['buffer_ui']}, CLI only)"
    )

    parser.add_argument(
        "--transfer-ui",
        dest="transfer_ui",
        choices=UI_CHOICES,
        default=config["transfer_ui"],
        help=f"front end for Ctrl+T and --send, the XMODEM transfer "
             f"(default {config['transfer_ui']}, CLI only)"
    )

    parser.add_argument(
        "--text-transfer",
        action="store_true",
        default=config["text_transfer"],
        help="the older way of writing --transfer-ui cli (CLI only)"
    )

    parser.add_argument(
        "-l", "--list-ports",
        action="store_true",
        help="list serial ports and exit"
    )

    # argparse prints this and exits on its own, before any port is
    # opened or any settings file is read.
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"{PROGRAM} {VERSION}",
        help="print the version and exit"
    )

    args = parser.parse_args(argv)

    args.config_values = config
    args.typed = typed_options(parser, argv)

    # --dialogs is the shorthand, so the named one wins where both
    # appear and neither disturbs a settings file that has its own.
    if args.dialogs:

        if "buffer_ui" not in args.typed:
            args.buffer_ui = args.dialogs

        if "transfer_ui" not in args.typed:
            args.transfer_ui = args.dialogs

    # --text-transfer stays the older spelling of --transfer-ui cli
    if args.text_transfer and "transfer_ui" not in args.typed:
        args.transfer_ui = "cli"

    return args


def session_rules(args):
    """
    The rules a CLI session starts with.

    A stored set wins, since it is what the rule window last applied.
    Naming a profile on the command line asks for that stock set
    instead, and an unconfigured install falls back to it too.
    """

    stored = args.config_values.get("rules")

    if "rule_profile" in args.typed or not stored:
        return profile_rules(args.rule_profile, stored)

    return stored


def config_from_args(args):

    return {
        "front_end": "cli" if args.cli else (
            "gui" if args.gui else args.config_values["front_end"]
        ),
        "port": args.port,
        "baud": args.baud,
        "timestamp": args.timestamp,
        "color": not args.no_color,
        "device_colors": args.device_colors,
        "input_color": args.input_color,
        "local_echo": args.local_echo,
        "xmodem": args.xmodem,
        "buffer_ui": args.buffer_ui,
        "transfer_ui": args.transfer_ui,
        # Written out as the two above, so the older key is not carried
        # forward to argue with them
        "text_transfer": False,
        "reconnect": args.reconnect,
        "highlight": args.highlight,
        "rule_profile": args.rule_profile,
        # The rules go in too. Left out, they fell back to the empty
        # default, which a stock profile hid by rebuilding itself and
        # custom could not.
        "rules": session_rules(args),
        "buffers": args.buffers,
    }


def main(argv=None):

    args = parse_args(argv)

    if args.save_config:

        path = args.config

        if save_config(config_from_args(args), path):
            print(f"Settings written to {path}")
        else:
            print(f"Could not write {path}")

    if args.list_ports:

        ports = list_ports()

        if not ports:
            print("No serial ports found.")

        for port in ports:
            print(f"{port.device}\t{port.description}")

        return 0

    # A CLI-only option on the command line implies --cli, so -p COM7
    # alone is enough; otherwise the settings file decides.
    wants_cli = (
        args.cli
        or (
            not args.gui
            and (
                bool(args.typed & CLI_ONLY_DESTS)
                or args.config_values["front_end"] == "cli"
            )
        )
    )

    if wants_cli:
        return run_cli(args)

    return run_gui(args)


if __name__ == "__main__":

    sys.exit(main())
