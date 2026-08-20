# powertools

Small serial/terminal tools.

## serialkit.py

A self-contained cross-platform serial utility in Python, GUI and CLI in
one script: regex syntax highlighting, input highlighting, XMODEM
128/1K upload, command buffers and timestamps.

One script, two front ends — a Tk window or a pure CLI terminal with
ANSI colours — sharing the same serial handling, the same highlight
rules and the same transfer and buffer windows. Only pyserial is needed.

- **Regex highlighting** — MobaXterm-style rules, applied as the line
  arrives, over the device's own ANSI colours. Three stock sets — Simple,
  Extended and Network — and twelve rules of your own in a window.
- **Input highlighting** — what you typed, and commands recalled with
  Up/Down, are drawn in their own colour.
- **XMODEM** — 128-byte CRC or 1K blocks, from a window with progress
  and abort, or straight from the command line.
- **Command buffers** — editable slots you can fire at the device,
  fifteen by default and up to 30.
- **Reconnect** — a device reset or power cycle does not end the session
  or lose the log; the port is waited for and picked up again.
- **Timestamps**, log saving, and a settings file for your usual setup.

### Requirements

```
pip install pyserial
```

pyserial is the only third-party dependency. Everything else — the
terminal emulation, the XMODEM sender, the windows — is in the script
itself; nothing shells out to PuTTY, TeraTerm or `sx`.

tkinter is needed for the GUI and for the XMODEM, Buffers and rule
windows. The CLI runs without it: transfers and buffers fall back to
terminal prompts, and the rule window says to edit `rules` in the
settings file instead.

Runs the same on Windows and Linux:

- **Windows** — tkinter ships with the python.org installer. Ports look
  like `COM8`.
- **Linux** — `sudo apt install python3-tk` for the windows, and add
  yourself to the `dialout` group for `/dev/ttyUSB*` access
  (`sudo usermod -aG dialout $USER`, then log out and back in).

### Usage

```
python serialkit.py                      # the window, and the usual way to run it
python serialkit.py --list-ports         # list serial ports and exit
python serialkit.py --cli                # CLI, prompts for a port
python serialkit.py --cli -p COM12 -b 921600
python serialkit.py -p /dev/ttyUSB0 -b 921600
python serialkit.py --cli -p COM8 -t --local-echo
```

Run with no arguments for the window: pick the port and rate from the
toolbar, hit Connect, and everything else — XMODEM, buffers, highlight
rules — is a button away. The CLI is there for a quick session over SSH,
for a machine with no tkinter, and for scripting a transfer with
`--send`.

| Option | Meaning |
| --- | --- |
| `--cli` | Run in the terminal, no window |
| `--gui` | Force the Tk window (default when no CLI option is given) |
| `-p`, `--port` | Serial port, e.g. `COM8` or `/dev/ttyUSB0` (CLI only) |
| `-b`, `--baud` | Baud rate, default `115200`; fills in the GUI's baud box too |
| `-t`, `--timestamp` | Prefix each line with `[YYYY-MM-DD HH:MM:SS]` (CLI only) |
| `--no-color` | Disable all colouring, highlight rules included (CLI only) |
| `--color` | Force colouring on, overriding the settings file (CLI only) |
| `--device-colors` | Keep the colours the device sends (default, CLI only) |
| `--strip-device-colors` | Drop the device's colours, show only highlight rules (CLI only) |
| `--input-color HEX` | Colour for text you typed once the device echoes it back, default `#7fd1ff` (CLI only) |
| `--no-input-color` | Draw typed text like everything else (CLI only) |
| `--local-echo` | Echo typed characters locally, for devices that do not echo (CLI only) |
| `--send FILE` | Send `FILE` with XMODEM as soon as the port opens, then stay in the session (CLI only) |
| `--xmodem {128,1k}` | XMODEM block size, default `1k`; also picked up by the GUI's transfer window |
| `--buffers FILE` | Command buffer file to use, created if missing; default `~/.serialkit_buffers.json` |
| `--rules {custom,extended,network,simple}` | Which highlight set to load, default `extended`. `custom` means the set stored in the settings file |
| `--highlight` | Colour what the rules match (default, CLI only) |
| `--no-highlight` | Leave the rules off, keeping device colours and the input colour (CLI only) |
| `--reconnect` | Wait for the port and carry on when the device is reset or power cycled (default, CLI only) |
| `--no-reconnect` | End the session as soon as the port is lost (CLI only) |
| `--text-transfer` | Run XMODEM as terminal prompts instead of opening the transfer window (CLI only) |
| `--config FILE` | Settings file to read, default `~/.serialkit.json` |
| `--no-config` | Ignore the settings file, use built-in defaults |
| `--save-config` | Write the settings in force to the file, then carry on |
| `-l`, `--list-ports` | List serial ports and exit |
| `-V`, `--version` | Print the version and exit |

Port settings are 8N1. Any option marked CLI only implies `--cli`, so
`-p COM8` alone is enough. `-b` and `--xmodem` are not among them: they
mean something to both front ends, so they leave the choice of front end
to `--cli` / `--gui` / `front_end`.

### Settings file

`~/.serialkit.json` holds the defaults, so a usual setup does not have to
be typed out every run. Precedence is **command line > settings file >
built-in defaults**.

Write it from whatever you are running now:

```
python serialkit.py -p COM8 -b 921600 -t --strip-device-colors --save-config
```

```json
{
  "baud": 921600,
  "buffers": null,
  "color": true,
  "device_colors": false,
  "front_end": "cli",
  "input_color": "#7fd1ff",
  "local_echo": false,
  "port": "COM8",
  "highlight": true,
  "reconnect": true,
  "rule_profile": "extended",
  "rules": [
    {
      "enabled": true,
      "pattern": "\\bBOOT\\b",
      "foreground": "#ff00ff",
      "background": null,
      "ignore_case": true
    }
  ],
  "text_transfer": false,
  "timestamp": true,
  "xmodem": "1k"
}
```

- `front_end` picks what starts when neither `--cli` nor `--gui` is
  given. `--gui` or `--cli` on the command line still wins, and so does
  any CLI-only option.
- `rules` holds the twelve entries from the rule window, written when
  you press Apply there. Both front ends load them at startup. An
  install with no stored rules falls back to the `rule_profile` set.
  Every rule in force comes from here — there is no built-in layer
  underneath.
- `highlight` turns the rules on or off. It is one of three independent
  kinds of colour: `highlight` for the rules, `device_colors` for the
  device's own ANSI, `input_color` for text you typed. `color` is the
  master switch above all three, and only `--no-color` clears it.
- `rule_profile` remembers which set the rule window last loaded:
  `simple`, `extended`, `network` or `custom`. `--rules NAME` overrides
  it for a run and loads that set instead of the stored rules — except
  for `custom`, which has no stock set of its own: it *is* the stored
  rules, so `--rules custom` keeps them rather than blanking them.
- `buffers` is the command buffer file. `null` means the usual
  `~/.serialkit_buffers.json`; `--buffers FILE` overrides it for a run.
  Only the path lives here: the slots, their count and the window's
  toggles all live in that file.
- `reconnect` keeps a session alive across a device reset or power
  cycle. `--no-reconnect` starts with it off, `Ctrl+O` `r` flips it in a
  CLI session, and the GUI has a **Reconnect** checkbox in the
  Connection box.
- The GUI writes its toolbar state — port, baud, Timestamp, Typed text,
  Device ANSI, Regex, Local echo, Reconnect — when the window closes, so
  it comes back the same way.
- `--config FILE` reads a different file, handy for one profile per
  board. `--no-config` ignores the file entirely.
- Unknown keys are ignored and an unreadable file falls back to the
  built-in defaults, so a bad edit never stops the tool starting.
- `--color` forces colouring back on when the file has it off.

### CLI mode

- **Ctrl+G** prints the key list, then every flag with its current
  value and the `Ctrl+O` letter that flips it:

  ```
  --- this session (letter = the Ctrl+O key) ---
    port                COM12 @ 921600 8N1
    Timestamp       t   [on]
    Regex highlight c   [on]
    Device ANSI     d   [off]
    Typed text      i   [on] #7fd1ff
    Local echo      e   [off]
    Reconnect       r   [on]
    XMODEM blocks       1K
    Highlight rules     11 active (extended profile)
    settings            C:\Users\you\.serialkit.json
  ```
- The tool's own messages — banners, the Ctrl+G list, transfer progress,
  errors — are drawn italic and dimmed (`NOTICE_COLOR` at the top of the
  script), so they are never mistaken for something the device said.
  They keep that look whatever Timestamp, Typed text, Device ANSI or
  Regex highlight are set to; only `--no-color`, which strips every
  escape, leaves them plain. The GUI does the same with a `notice` tag
  the highlight rules skip.

  | Key | Does |
  | --- | --- |
  | `Ctrl+]` | Quit |
  | `Ctrl+T` | Send a file with XMODEM |
  | `Ctrl+B` | Command buffers |
  | `Ctrl+R` | Highlight rules |
  | `Ctrl+Y` | Typed text colour on/off |
  | `Ctrl+O` | Flag mode: toggle as many as you like — see below |
  | `Ctrl+G` | The key list |
  | `ESC` / `Ctrl+C` | Abort a running transfer |

  Not Ctrl+H: that byte is what Backspace sends through `msvcrt` on
  Windows, so binding it would cost you Backspace.
- **Ctrl+O** prints the flags with their current state and stays open,
  so a run such as `Ctrl+O` `t` `d` `i` `Enter` flips three of them in
  one go. Every key is a flag while the mode is open — `Enter` or `ESC`
  closes it and hands the keyboard back to the device. Each flip prints
  a one line summary: `t[on]  d[off]  i[off]  c[on]  e[on]  r[on]`.
  Everything a command line flag sets can be changed without restarting:

  | Key | Flips | GUI equivalent |
  | --- | --- | --- |
  | `t` | **Timestamp**, as `-t` does | Log box |
  | `d` | **Device ANSI**, the device's own colours | Colours box |
  | `i` | **Typed text**, same as `Ctrl+Y` | Colours box |
  | `c` | **Regex highlight**, the rules only — Device ANSI and Typed text carry on | Colours box, **Regex** |
  | `e` | **Local echo** | Send box |
  | `r` | **Reconnect** — wait for the port after a reset instead of ending the session | Connection box |
  | `w` | Writes the flags as they stand to the settings file | closing the window |
  | `Enter` / `ESC` / `q` / `Ctrl+O` | Leaves the mode | |
  | anything else | Says so and stays open | |

  The names match the GUI toolbar, so a flag reads the same in both
  front ends.

  The device's colours keep being recorded while they are hidden, so
  turning them back on colours the line still being drawn as well as
  everything that follows; lines already printed keep the look they were
  printed with. A toggle lasts for the session unless you press `w`.
- Typed keys go straight to the device; what you see back is the device
  echo unless `--local-echo` is set.
- If the device goes away mid-session — unplugged, or power cycled so
  its USB port re-enumerates — the session stays up and waits for it,
  keeping everything already on screen:

  ```
  [Serial error: ClearCommError failed (PermissionError(13, 'Access is denied.'))]
  [COM8 lost - waiting for it to come back. Ctrl+] quits, the log above is kept.]
  [not connected - waiting for COM8]
  --- Reconnected to COM8 @ 921600 8N1 ---
  ```

  The port is retried four times a second, and only actually opened once
  it is listed again. Anything typed while it is away is dropped with
  one notice, not one per keystroke. `Ctrl+]` still quits at any point,
  including while waiting. `--no-reconnect` ends the session as soon as
  the port disappears instead: `[COM8 lost. Closing the session.]`, and
  `Ctrl+O` `r` flips the same thing mid-session — turning it off while
  the session is already waiting gives up on the port there and then.

  Windows can leave the port handle stuck behind a read that will never
  finish. Closing it is given two seconds on its own thread, and if the
  driver still will not let go the process says so and exits rather than
  hanging. Writes use a two second timeout for the same reason.
- The connect and disconnect banners name the port and rate
  (`--- Disconnected from COM8 @ 921600 8N1 ---`), so scrollback shows
  which port a session was on.
- Arrows, Home/End, Page Up/Down, Insert and Delete are sent as the usual
  VT escape sequences (Up is `\x1b[A`), so shell history and line editing
  work on the device. Each sequence is written in one go. With
  `--local-echo` these keys are not echoed locally, since only the device
  knows what its line buffer looks like.
- Colours use truecolor escapes. Windows Terminal and modern shells are
  fine; legacy `conhost` approximates them. Use `--no-color` to pipe the
  output to a file.

### GUI mode

The toolbar is split into titled boxes, one per job:

| Box | Holds |
| --- | --- |
| **Connection** | port picker, Refresh, baud, Connect, Disconnect, Reconnect |
| **Send** | XMODEM..., Buffers..., Local echo |
| **Colours** | Typed text, Device ANSI, Regex, Highlight rules... |
| **Log** | Timestamp, Clear, Save |

Click the black terminal area first, then type — keystrokes are sent to
the port. Arrows and navigation keys are sent as the same VT sequences
the CLI uses.

The toolbar wraps onto more rows as the window narrows, so nothing is
cut off when the window is snapped to a Windows tile or a half-screen
layout. A box is never split across rows.

**Local echo** shows what is sent — typed keys, Enter, Backspace and
anything fired from the Buffers window — for a device that does not echo
by itself. Arrows and navigation keys are left out: they are a
device-side line edit, not text.

**Regex** turns the highlight rules off without touching Typed text or
Device ANSI, and re-colours what is already on screen when it goes back
on.

A device that is reset or power cycled does not end the session here
either, as long as **Reconnect** is ticked: the status bar shows
`Waiting for COM8...` and then `Connected: COM8 @ 921600 8N1`, with the
same notices in the terminal. **Disconnect** stops it waiting, and so
does unticking Reconnect while it waits.

The tool's own lines — banners, errors, transfer notes — are drawn in
italic grey and are skipped by the highlight rules, so they cannot be
confused with device output whatever the colour toggles are set to.

### Command buffers

Slots of text you can fire at the device, fifteen to start with.
**Ctrl+B** in a CLI session, or **Buffers...** in the GUI toolbar, opens
the same window: editable fields numbered from 1, each with a **Send**
button. Enter in a field sends that slot.

A **Slot** box at the bottom with **-** and **+** next to it changes the
slot count, between 1 and 30. Type a slot number and **-** removes that
slot while **+** puts a new empty one after it; with the box empty they
work on the end of the list. Either way the new count is written to the
buffer file straight away, so the window opens with the slots you left
it with. Removing a slot that holds text drops the text too.

The window can be resized when a slot holds a long command; it will not
shrink below the layout.

Options along the bottom:

- **Append Enter** — add `\r\n` to what is sent (on by default).
- **Interpret `\n` `\t` `\xNN`** — also `\r`, `\e` for escape, and `\\`
  for a literal backslash. So `\x1b[A` sends the Up arrow.
- **Close after send** — off if you want to fire several in a row.

All three are kept in the buffer file itself the moment they are
clicked, so the window opens with them as you left them and a file
named with `--buffers` brings its own along.

`--buffers FILE` picks a different file, so one set of commands can live
per project or per device. A file that is not there yet is created with
fifteen empty slots — at CLI startup, and when the GUI opens the window.
The path is written by `--save-config` and by Ctrl+O w, Ctrl+G shows
which file the session is on, and the window's title bar carries the
file name next to the port.

**Save** writes the file, **Reload** reads it back and throws away
whatever was typed since — handy when the file was edited elsewhere, or
to walk back a change. **Save as** asks for another file, writes the
slots and toggles there, and moves the window onto it: the title bar
follows, and Save and Reload work on the new file from then on. That is
how a set of commands is copied per project or per device without
`--buffers`. There is no Close button; the window's own X does that, and
it saves on the way out.

Slots are saved to `~/.serialkit_buffers.json` whenever one is sent, on
**Save**, when a slot is added or removed, and when the window closes,
so they survive a restart. The file holds the whole set — the slots, how
many there are, and the three toggles:

```json
{
  "slots": ["reboot", "ifconfig", ""],
  "flags": {
    "enter": true,
    "escapes": true,
    "close": true
  }
}
```

A missing or unreadable file just starts out empty with fifteen slots.
The bare list written by earlier versions is still read, and turns into
the shape above on the first save. Buffers written before the script was
renamed (`~/.serial_highligher_buffers.json`) are still read if the new
file does not exist yet, and move over on the first save.

Without tkinter, or with `--text-transfer`, Ctrl+B lists the slots in the
terminal and asks for a number to send, or `e N` to edit slot `N`.

### Highlight rules

Edit `HIGHLIGHT_RULES` at the top of the script. Each entry is
`(regex, foreground, background)`, with an optional fourth field for
regex flags; `background` may be `None`. Matching is case-insensitive
unless a rule supplies its own flags — pass `0` for a rule that must
respect case. Matches are taken left to right and never overlap; where
two rules start at the same place, the longer match wins.

```python
HIGHLIGHT_RULES = [
    (r"\bERROR\b", "#ff4444", "#330000"),
    (r"\bINFO\b",  "#00ff88", None),
    (r"\b0[xX][0-9A-Fa-f]+\b", "#00d7c0", None, 0),   # case-sensitive
    ...
]
```

Hex is covered out of the box:

| Looks like | Where the rule lives |
| --- | --- |
| `0xDEADBEEF`, `0X0F` | built in, always on |
| `\xde\xad` byte escapes | built in, always on |
| `de ad be ef 00 11` dump columns | built in, always on |

The dump rule wants four or more pairs in a row and at least one hex
letter among them, so a column of plain decimal numbers such as
`10 20 30 40 50` is left alone.

Watch out for rules that are looser than they look. The temperature rule
is case-sensitive and refuses a preceding hex digit for exactly this
reason: as `\d+\s*C\b` matched case-insensitively, it turned the `3c`
inside `0x3c` into "3 degrees".

Rules apply to both front ends. Highlighting is re-evaluated on the open
line as data arrives, so a word is coloured as soon as it is complete,
not only after the newline.

#### The rule window

Twelve rules of your own, without touching the script: **Ctrl+R** in a
CLI session, or **Highlight rules...** in the GUI toolbar.

Each row is an expression plus its colours:

- **On** — use this rule or skip it.
- **Expression** — a Python regular expression.
- **Text** / **Back** — foreground and background swatches; click to
  pick. Cancelling the background picker clears it, for a rule that only
  changes the text colour.
- **Aa** — case-insensitive when ticked.

Below the rows, a sample line is coloured live as you type, so an
expression can be checked before it is used. Edit the sample to try it
against a line of your own. A broken expression is reported under the
sample and simply does not match — it never stops the terminal.

The **Profile** box at the bottom holds **Simple**, **Extended**,
**Network** and **Custom**; each fills the twelve rows with a stock set,
and **Apply** is still what keeps them. **Custom** fills them with
nothing — it is the blank sheet to write a set of your own on, so
closing the window without pressing Apply is what walks that back.

**Simple** is the narrow set — ten rules, each mostly a word list, so a
busy log stays mostly plain:

| Row | Colour | Catches |
| --- | --- | --- |
| 1 | red on dark red | `ERROR` `ERR` `ERRNO` `FAIL(ED/URE)` `EXCEPTION` `ASSERT(ION)` `PANIC` `ABORT` `DOWN` |
| 2 | green | `PASS(ED)` `OK` `SUCCESS` `DONE` `INFO` `UP` `CONNECTED` |
| 3 | yellow on dark yellow | `WARNING` `WARN` `TIMEOUT` `RETRY/RETRIES` `BUSY` `DROP(PED)` |
| 4 | orange on dark orange | `DISCONNECTED` |
| 5 | grey | `DEBUG` and `12:04:55(.123)` clock times |
| 6 | magenta | `RX` / `TX`, case-sensitive so a word like "extra" is left alone |
| 7 | blue | IPv4 addresses |
| 8 | magenta | MAC addresses |
| 9 | teal | `0x1f00` and `\xNN`, case-sensitive |
| 10 | yellow | `"quoted strings"` |

**Extended** is the MobaXterm set, translated to Python regex and
trimmed to English wording — eleven rules:

| Row | Colour | Catches |
| --- | --- | --- |
| 1 | red on dark red | `ERROR`, `FAIL(ED/URE)`, denied, refused, not permitted, rejected, invalid, unsupported, not implemented, segfault, corrupt, overflow, underrun, `no ... found`, crash, core dump, administratively down, `(ee)`, `(ni)`, and a `false`/`no`/`ko` in value position |
| 2 | green | `INFO`, `CONNECTED`, `UP`, session opened, accepted, allowed, enabled, success(ful/fully/eeded), a `true`/`yes`/`ok` in value position, and a column reading `up` or `active` |
| 3 | yellow on dark yellow | `WARNING`/`WARN`, cannot, could not, unable to, not found, closed/terminated/stopped, exited, out of space/memory, low memory/disk, unknown user, disabled, deprecated, shutdown, discard, `(ww)`, `(??)`, and shell expansions `$VAR` `${...}` `$(...)` `$?` |
| 4 | orange on dark orange | `DISCONNECTED` |
| 5 | grey | `DEBUG` and `12:04:55(.123)` clock times |
| 6 | blue | IPv4 addresses, `\033[...m` and `\e[...` escapes, `[12:04:55]`-style brackets, `/dev/null`, `\|\|`, `&&` |
| 7 | magenta | MAC addresses, localhost, null, none, shell keywords (`if` `then` `fi` `while` `done` `case` `esac` ...), interface names (`GigabitEthernet0/1`, `vlan10`, `bvi1`, `Dot11Radio0`) |
| 8 | teal | `0x1f00`, `\xNN`, and runs of hex bytes (`de ad be ef`), case-sensitive |
| 9 | cyan | `-v` / `--long-option`, last login, launching, checking, loading, creating, building, booting, starting, notice, info, `(ii)`, `(!!)`, shell builtins (`echo` `export` `alias` `printf` ...) and switch config keywords (`switchport`, `spanning-tree`, `access-list`, `running-config` ...) |
| 10 | amber | dBm readings |
| 11 | magenta | temperatures (`-40 °C`, `85C`), case-sensitive |

**Network** targets network gear and embedded/firmware output — nine
rules:

| Row | Colour | Catches |
| --- | --- | --- |
| 1 | red on dark red | `ERROR`/`ERR`/`FAIL`, link down, carrier lost, no carrier, CRC error, checksum, frame/packet/bit error, collision, runts, giants, drops, input/output error, overrun, underrun, timeout, unreachable, no route, auth failed/denied, hard/soft fault, bus error, parity error, stack overflow |
| 2 | green on dark green | `INFO`, `CONNECTED`/`UP`, link up, carrier detect, negotiated, established, reachable, associated, registered, ready, boot ok, flash ok, calibration ok/done, programmed, initialized, synced |
| 3 | yellow on dark yellow | `WARNING`/`WARN`, retransmit, duplex/speed mismatch, flapping, STP, spanning-tree, BPDU, topology change, over/undervoltage, brownout, low battery, watchdog, reset, reboot(ing) |
| 4 | orange on dark orange | `DISCONNECTED` |
| 5 | grey | `DEBUG`, clock times, and `seq=12` / `ack: 7` / `pkt #3` counters |
| 6 | blue | IPv4 addresses, with an optional `/24` prefix length |
| 7 | magenta | MAC addresses, short and long interface names (`Gi0/1`, `Eth1`, `Po2`, `TenGigE0/0/0/1`, `Vlan10`), and a 4-8 digit hex register in front of `=` `:` `<`; case-sensitive |
| 8 | teal | `0x1f00`, `\xNN`, and runs of hex bytes, case-sensitive |
| 9 | cyan | dBm, V/mV/kV, mA, MHz and temperatures, case-sensitive |

In rows 1, 2, 3 and 5 the bare level words skip a bracketed `[ERROR]`,
which the device's own colouring usually already marks.

**Custom** is the odd one out: it has no stock set, so what it means
depends on where you name it. The **Custom** button in the window clears
the rows, to write a set from scratch. `--rules custom` on the command
line does the opposite and loads the set already in the settings file,
since that set *is* the custom profile and rebuilding it from the name
would be throwing it away.

Extended is what an unconfigured install starts with; `--rules NAME`
picks another for a run, and the choice is written back to the settings
file as `rule_profile` once you press Apply. Nothing is saved until
Apply, so closing the window instead discards the rows.
**Apply** stores the rules in the settings file and re-colours what is
already on screen. Every rule in force is one of these twelve — nothing
runs underneath them. Where two rules match at the same place the longer
match wins, and on an equal match the upper row does.

### How the line is rendered

Both front ends feed incoming data through the same line assembler,
which keeps the open line as a character buffer with a cursor:

- `LF` ends a line; `CR` only moves the cursor to column 0, so a device
  redrawing the line in place (shell history via Up/Down, tab
  completion, progress output) overwrites it instead of producing a new
  line for every redraw.
- `BS` steps the cursor back, the usual `BS space BS` erases. Both front
  ends put the cursor where the device left it — the CLI walks it back
  with `CSI D` after repainting the line, the GUI moves its insert mark
  — so a backspace looks like a backspace instead of leaving the cursor
  stranded at the end of the line.
- CSI edits are applied: `K` erase in line, `C`/`D` cursor right/left,
  `G` column, `P` delete characters, `@` insert blanks.
- Other escape sequences (cursor save, screen erase, OSC titles) are
  dropped. Sequences split across two reads are held until the rest
  arrives.

### XMODEM upload

Press **Ctrl+T** in a CLI session, or click **XMODEM...** in the GUI
toolbar. Both open the same small window:

- a file field with **Browse...**
- the format: **XMODEM-1K (1024 byte blocks)** or **XMODEM-CRC (128 byte
  blocks)**
- a progress bar with bytes, blocks, kB/s and time left
- **Send**, **Abort**, **Close**

The window keeps the transfer out of the terminal, which otherwise mixes
device output with progress lines. While it runs, the terminal reader is
paused so nothing else touches the port; it resumes when the window
closes.

An open buffer window stays up but stops sending while the transfer
window lives, since both write to the same port; its fields grey out and
say why, the transfer window notes **Buffers disabled** in red, and they
come back when the transfer window closes. A transfer
that finishes closes its window on its own after a moment; one that
fails or is aborted stays up with the reason on it.

From the command line, `--send` opens the same window with the file
filled in and starts immediately, then drops back into the session:

```
python serialkit.py -p COM8 --send firmware.bin --xmodem 1k
python serialkit.py -p COM8 --send config.txt --xmodem 128
```

The path may be quoted, use `~`, environment variables, forward or back
slashes, and a Windows path works while running under WSL
(`C:\Users\me\fw.bin` is also tried as `/mnt/c/Users/me/fw.bin`). A
drive letter typed without its colon is repaired. If nothing matches,
every form that was tried is listed.

Order of operations: issue the receive command on the device, then Send.
The sender waits up to 60 s for the receiver's start character.

#### Without a window

`--text-transfer` (or a Python without tkinter) falls back to prompts in
the terminal:

```
--- XMODEM send (ESC or Ctrl+C during transfer aborts) ---
File to send: /home/me/firmware.bin
Block size [1] 128 CRC  [2] 1K (default 2):
XMODEM: receiver ready (CRC mode)
XMODEM: 262144/262144 bytes (100%), 256 blocks
XMODEM: done, 256 blocks sent
```

#### Protocol notes

- `C` from the receiver selects CRC-16; a plain `NAK` falls back to the
  8-bit checksum. Both block sizes work either way.
- `1k` sends 1024-byte `STX` blocks and drops to a 128-byte block for a
  tail of 128 bytes or less, which every XMODEM-1K receiver accepts.
- The last block is padded with `0x1A`, as the protocol requires — the
  receiver's file may be a little longer than the source.
- Only `ACK`, `NAK` and `CAN` are read as replies. Receivers poll with
  `C` every few seconds before the transfer, and those leftovers would
  otherwise be mistaken for the first block's answer, causing a resend
  that the receiver rejects as a duplicate sequence number.
- Failed blocks are retried up to 10 times, then the transfer is
  cancelled with `CAN`. **Abort** in the window, or **ESC** / **Ctrl+C**
  in text mode, stops at any point: the sender sends `CAN CAN CAN` so
  the receiver gives up too, and the session continues.

### Input colour

What you type is drawn in its own colour, `INPUT_COLOR` at the top of the
script (default `#7fd1ff`). Since the characters on screen come from the
device's echo, the terminal remembers what it sent and marks the echo
when it comes back in the same order, within 10 seconds. Device output
that merely happens to contain the same letters is left alone, and so is
anything that arrives after the wait expires.

The colour survives a device that repaints its line after every
keystroke, as bootloaders tend to: a repaint that rewrites the same
character keeps whatever that character already was, so the prompt stays
plain and the command stays yours. A dropped echo character no longer
strands the rest of the line either, and the terminal waits 10 seconds
for an echo, which is enough for a device busy erasing flash.

Commands recalled with Up/Down are coloured too. They are not an echo of
anything typed, so after an arrow is sent the terminal watches the line
redraw for up to 2 seconds: characters that change are the recalled
command and count as input, characters that stay the same are the prompt
and are left alone. The window closes at the next newline, so an
unrelated log line is never caught by it. The same applies to any other
key that makes the device repaint the line, such as Home/End edits.

Priority runs input colour, then highlight rules, then the device's own
colours — so a command you typed stays your colour even if a rule matches
it.

- CLI: `--input-color '#ff9900'` to change it, `--no-input-color` to
  start with it off, **Ctrl+Y** to flip it during a session. (Ctrl+I is
  not used for this: that byte is Tab, and the device needs it for
  completion.) `--no-input-color` disables it for the whole session, so
  Ctrl+Y says so rather than turning it on.
- GUI: the **Typed text** checkbox in the **Colours** box.
- With `--local-echo` the characters are marked as you type them, since
  no echo is coming back.

### Device colours

If the device sends its own ANSI colours, they are kept by default and
recorded per character, so they survive an in-place redraw. Highlight
rules are drawn on top: where a rule matches, the rule's colour wins;
everywhere else the device's colour is used.

- CLI: `--strip-device-colors` to show only the highlight rules,
  `--device-colors` to keep them (default), `--no-color` for no colour
  at all.
- GUI: the **Device ANSI** checkbox in the **Colours** box. It applies to text
  received after the toggle; what is already on screen keeps its colour.

Recognised: the 8 base and 8 bright colours, `38;5;n` / `48;5;n`
256-colour, `38;2;r;g;b` / `48;2;r;g;b` truecolor, and bold as bright.
