"""Every dimension of the Helm case, in millimetres.

Frames used everywhere:

- Case frame: x runs left to right across the front, y runs from the front
  wall to the back wall, z runs up from the desk. The origin is the
  front-left-bottom outside corner.
- Plate frame: (x, v, w). x is the case x, v runs up the sloped face from its
  front edge, w is the face's outward normal. The face's top surface is w = 0,
  so a part hanging below the face has a negative w.

Values marked VENDOR come from a vendor drawing or page named in
case/README.md. Values marked ASSUMED are estimates to check on the real part
before ordering metal; the README lists each one with what to measure.
"""

import math

INCH = 25.4

# ---------------------------------------------------------------------------
# Overall shape (design choices). The face, front wall and back wall are one
# bent cover screwed up from the bottom, so nothing shows on the face; the
# module sits on a printed cradle standing on the floor.
# ---------------------------------------------------------------------------
SLOPE_DEG = 15.0
SLOPE = math.radians(SLOPE_DEG)
WIDTH = 145.0  # case width, x
FACE_LENGTH = 140.5  # face length along the slope, v; leaves 5 mm clear above and below the logo
FRONT_HEIGHT = 18.0  # desk to the top of the face at its front edge

DEPTH = FACE_LENGTH * math.cos(SLOPE)  # case depth, y
BACK_HEIGHT = FRONT_HEIGHT + FACE_LENGTH * math.sin(SLOPE)

# ---------------------------------------------------------------------------
# Waveshare ESP32-P4-WIFI6-Touch-LCD-5, turned to landscape (VENDOR: Waveshare
# dimension drawing). Native portrait 720 x 1280; mounted with its USB-C
# short edge facing the left wall, so firmware rotates the display 90 degrees.
# ---------------------------------------------------------------------------
MODULE_SX = 126.9  # cover glass along case x, as mounted
MODULE_SV = 70.7  # cover glass along plate v, as mounted
MODULE_THICKNESS = 11.6
TOUCH_X = 110.32  # viewing area, centred on the glass
TOUCH_V = 62.28
DISPLAY_ACTIVE = (TOUCH_X, TOUCH_V)  # lit area, x by v as mounted (render)
DISPLAY_PIXELS = (1280, 720)
# Mounted glass up with its USB-C edge to the left, the board's button edge
# (RESET, BOOT, POWER) faces the front and its 40-pin header edge the back.
MODULE_PCB = (118.5, 64.5)  # VENDOR, drawing
MODULE_PCB_INSET_USB = 1.55  # glass edge to PCB edge on the USB side (derived from the drawing)
MODULE_PCB_INSET_V = (MODULE_SV - MODULE_PCB[1]) / 2  # PCB centred on the glass (derived)
MODULE_PCB_REAR = 6.0 + 1.6  # glass front to the PCB's rear face (derived: 11.6 - 4 - 1.6, plus the PCB)
# USB-C centres along the left (short) edge, from the module's front edge:
# the drawing gives 23.26 mm from the header edge to "USB" (native) and 17.95
# between the two.
MODULE_USB_UART = MODULE_SV - MODULE_PCB_INSET_V - 23.26 - 17.95  # "USB TO UART" (CH343P): flashing
MODULE_USB_NATIVE = MODULE_SV - MODULE_PCB_INSET_V - 23.26  # "USB": the deck link, through the ribbon
MODULE_USB_DEPTH = 9.3  # glass to the USB-C centres: on the PCB's rear face (derived by scaling the drawing, measure)
# 40-pin 2.54 mm female header on the PCB's rear face along the back edge.
# Pins 1 and 2 are 14.17 mm from the PCB's far short edge (VENDOR, wiki
# size image); the rows sit 3.1 and 5.6 mm in from the PCB edge and the
# socket stands 5.1 mm proud (derived by scaling the drawing).
HEADER_PIN1_FROM_FAR_EDGE = 14.17
HEADER_ROWS_IN = (3.1, 5.6)
HEADER_HEIGHT = 5.1
HEADER_PLUGS = 20.0  # jumper housings plugged in from below, plus the wires' bend (ASSUMED)

# Placement on the face (design choices)
MODULE_X = 9.05  # USB edge, case x; leaves room for the ribbon plug beside the left wall
MODULE_V = 51.0  # front edge, plate v
SCREEN_WINDOW_X = 111.8  # window over the 110.32 x 62.28 viewing area (ASSUMED, bench check)
SCREEN_WINDOW_V = 63.8
SCREEN_WINDOW_RADIUS = 1.5
# Window centre offset from the module centre (the LCD-5's viewing area is
# centred on its glass)
WINDOW_OFFSET = (0.0, 0.0)

# The printed cradle under the module, on four legs screwed up through the
# floor into heat-set inserts (ASSUMED sizes, a printed part)
CRADLE_T = 3.0
CRADLE_FOAM = 1.5  # foam between the module's back and the cradle, compressed
CRADLE_INSET = 10.0  # the cradle starts this far behind the module's front edge
CRADLE_HEADER_GAP = 1.5  # the cradle stops this far in front of the header's socket
CRADLE_LEG_D = 8.0
CRADLE_LEGS = ((35.0, 12.0), (110.0, 12.0), (35.0, 52.0), (110.0, 52.0))  # x, v from the module front-left corner

# ---------------------------------------------------------------------------
# Keys: Cherry MX on Adafruit NeoKey socket breakouts (4978). Any keycap with a
# standard MX cross stem fits, so machined aluminum caps are a straight swap.
# ---------------------------------------------------------------------------
KEY_PITCH = 0.75 * INCH  # 19.05
KEY_HOLE = 14.00  # Cherry: 14 mm +/- 0.05 for a 1.5 mm plate (VENDOR)
KEY_PLATE_TO_PCB = 5.0  # plate top to switch PCB top (VENDOR, Cherry MX)
NEOKEY_PCB = (0.75 * INCH, 0.85 * INCH)  # 19.05 x 21.59 (VENDOR, Adafruit 4978)
NEOKEY_PCB_THICKNESS = 1.6  # ASSUMED
KEY_STACK_DEPTH = 13.0  # plate top to the bottom of socket, pins and wires (ASSUMED)
SWITCH_TOP_HEIGHT = 6.6  # plate top to the switch's top housing top (ASSUMED)
MX_STEM = (4.0, 3.6)  # Cherry MX cross stem: outside diameter, height above the housing (ASSUMED, render)
KEYCAP = 17.6  # flat low-profile cap, square base (ASSUMED until the caps are chosen)
KEYCAP_HEIGHT = 5.0  # ASSUMED
# The largest machined aluminum cap the fit check proves fits (square base,
# height): the swap needs no case change while caps stay inside this.
ALU_KEYCAP_MAX = (18.6, 14.0)
KEY_COLUMN_X = 16.0  # left edge of the four-key block
KEY_V = 15.0
KEY_XS = tuple(KEY_COLUMN_X + KEY_PITCH / 2 + i * KEY_PITCH for i in range(4))
KEY_BLOCK_CENTRE_X = KEY_COLUMN_X + 2 * KEY_PITCH

# ---------------------------------------------------------------------------
# Knob: Adafruit 5880 I2C encoder board under a machined knob whose skirt
# hides the encoder's nut
# ---------------------------------------------------------------------------
ENCODER_BOARD = 1.00 * INCH  # VENDOR, Adafruit fab print; encoder at the centre
ENCODER_BODY = (13.4, 12.5)  # Bourns PEC11R body (VENDOR for PEC11R; ASSUMED for 5880's encoder)
ENCODER_BODY_HEIGHT = 6.5  # mounting surface above PCB, upper bound of PEC11R's 5.5 to 6.5
ENCODER_HOLE = 7.5  # M7 x 0.75 bushing; coupon tests 7.2 and 7.5 (ASSUMED until the coupon)
KNOB_D = 24.0  # DROK 6 mm aluminum knob: 24 mm flange, 14.5 mm tall (VENDOR, Amazon listing)
KNOB_HEIGHT = 14.5
KNOB_X = 112.0
KNOB_V = 15.0

# ---------------------------------------------------------------------------
# Speaker: the 8 ohm 2 W speaker that comes with the LCD-5 (GH1.25 plug),
# under a field of slots above the keys
# ---------------------------------------------------------------------------
# Its size is not published (ASSUMED: Waveshare's own 8 ohm 2 W cavity
# speaker, 2030 type B, is 30 x 20 x 6.8 mm; measure the one in the box)
SPEAKER_BOX = (30.0, 20.0, 6.8)
SPEAKER_HOLDER_WALL = 1.6  # printed gasket frame around it, bonded under the face
SPEAKER_X = KEY_BLOCK_CENTRE_X
SPEAKER_V = 38.0
SLOT_SIZE = (1.8, 7.0)  # one slot, x by v (sheet minimum is 1.6)
SLOT_PITCH = 3.6
SLOT_COUNT = 14

# ---------------------------------------------------------------------------
# Light bar: Adafruit NeoPixel Stick 1426
# ---------------------------------------------------------------------------
LIGHT_STICK = (51.1, 10.2)  # VENDOR, Adafruit 1426
LIGHT_STICK_THICKNESS = 3.2  # PCB plus 5050 LEDs (ASSUMED)
LIGHT_WINDOW = (49.0, 6.0)  # covers the eight LEDs (ASSUMED: LED span about 49.5 mm)
LIGHT_WINDOW_RADIUS = 1.0
LIGHT_X = KNOB_X
LIGHT_V = 38.0
LIGHT_HOLDER = (57.0, 15.0)  # printed white holder, x by v
LIGHT_HOLDER_DEPTH = 6.0  # below the face underside
LIGHT_DIFFUSER = 1.6  # white plastic between LEDs and the face

# ---------------------------------------------------------------------------
# Service slot: a closed slot in the left wall over the module's USB edge, for
# the flashing cable
# ---------------------------------------------------------------------------
USB_PLUG_OVERMOLD = (12.35, 6.5)  # typical maximum plug body (ASSUMED: measure your cable)
PORT_BAY_V = (MODULE_V + 19.0, MODULE_V + 52.0)  # spans both USB-C receptacles
PORT_BAY_BELOW_FACE = MODULE_USB_DEPTH + USB_PLUG_OVERMOLD[1] / 2 + 0.5  # slot bottom, below the module face
PORT_BAY_RADIUS = 1.5

# ---------------------------------------------------------------------------
# Everyday USB-C entry (power and the deck link): a panel jack low in the back
# wall, wired inside to the module's native USB port
# ---------------------------------------------------------------------------
# Adafruit 6153 USB-C panel jack to 6-pin JST PH lead (VENDOR: datasheet image
# on the product page). Its CC pins are pulled down with 5.1k inside, so a Mac
# powers it like any USB-C device; D+ and D- come out on the lead.
BACK_JACK_HOLE = 11.4  # Adafruit: drill 11 to 13.5 mm; M11 x 1 thread
BACK_JACK_FLANGE = (13.8, 3.0)  # outside the wall: diameter, thickness
BACK_JACK_BODY_D = 11.0
BACK_JACK_LENGTH = 14.5  # thread behind the flange (takes a panel up to 7 mm)
BACK_JACK_NUT = (14.0, 3.0)  # hex nut inside: across flats, thickness
BACK_JACK_LEAD_D = 3.5  # six wires, 175 mm (ASSUMED bundle diameter)
BACK_JACK_X = 30.0  # behind the module's left half
BACK_JACK_Z = 15.0  # centre above the desk: the lowest that keeps the hole 6 mm from the bottom bend
# Adafruit 4090 USB-C breakout, receptacle on one short edge (VENDOR: 20.4 x 14.2 x 5.0)
BREAKOUT = (20.4, 14.2, 5.0)  # along x, along y, height
BREAKOUT_TAPE = 1.0  # foam tape under it
BREAKOUT_XY = (12.5, 66.0)  # receptacle edge (facing the left wall), front edge
BREAKOUT_USB_HEIGHT = 4.2  # receptacle centre above the board's underside (ASSUMED)
# Adafruit 6370 slim right-angle USB-C ribbon, 100 mm: the ribbon leaves each
# plug along the plug's narrow axis, so in the native port it drops straight
# down beside the module. Head and ribbon width estimated from Adafruit's
# photo against a quarter; the head thickness is ASSUMED.
RIBBON_PLUG_HEAD = (12.0, 7.3, 3.5)  # along the receptacle's wide side, along its narrow side, out of the receptacle
RIBBON_WIDTH = 5.8
RIBBON_THICKNESS = 0.4  # ASSUMED
RIBBON_DROP_END = 12.0  # the ribbon's straight drop ends this far above the floor, then turns to the breakout

# ---------------------------------------------------------------------------
# Logo: wheel + "helm" (H1), laser engraved on the anodized face by a local
# fiber laser shop. Not a cut: it lives only in the engraving files.
# ---------------------------------------------------------------------------
LOGO_X = MODULE_X + MODULE_SX / 2  # centred on the screen window
LOGO_V = 127.75  # window back edge 118.25 + 5 + half the 9.0 mm mark
LOGO_CLEAR = 4.0  # engraving to any cut, to the face's side edges, and to where a bend starts

# ---------------------------------------------------------------------------
# SendCutSend sheet rules (docs/research/case.md; hardware from SendCutSend's
# hardware catalog, read 2026-11-09)
# ---------------------------------------------------------------------------
SHEET_T = 0.063 * INCH  # 5052 H32 aluminum, 1.6002 mm
BEND_RADIUS = 0.035 * INCH  # fixed by SendCutSend for 5052 at 0.063 inch
K_FACTOR = 0.42
MIN_FLANGE = 0.303 * INCH
BEND_FEATURE_CLEARANCE = 0.472 * INCH / 2  # half the die width, from the bend centreline
MAX_BEND_DEG = 130.0
MIN_HOLE = SHEET_T  # 5052 page: hole or slot at least equal to thickness
MIN_EDGE_WEB = 2 * SHEET_T  # hole to edge
MIN_WEB = SHEET_T  # between two cuts (conservative; the spec panel's bridge minimum is 0.61 mm)
HARDWARE_EDGE = 0.250 * INCH  # S-M3-0: centre to edge or bend
S_M3_HOLE = 0.168 * INCH  # S-M3-0 self-clinching nut
S_M3_PROUD = 0.059 * INCH  # nut height above the sheet
M3_CLEARANCE = 3.4  # screw holes in the base
SIDE_CLEARANCE = 1.1  # the cover's edges to the side walls

# Bottom screws: up through the base into the cover's flange nuts
BASE_SCREW_Y = 9.6  # from the front and back outside faces
BASE_SCREWS_X = (15.0, WIDTH / 2, WIDTH - 15.0)
BOTTOM_FLANGE = 16.2  # flange length from the outside face

# ---------------------------------------------------------------------------
# Printed parts
# ---------------------------------------------------------------------------
PRINT_INSERT_D = 4.0  # M3 heat-set insert, about 4.6 mm OD x 5.7 mm (ASSUMED: match your inserts)
PRINT_INSERT_DEPTH = 6.5

# ---------------------------------------------------------------------------
# Test coupon
# ---------------------------------------------------------------------------
COUPON_KEY_HOLES = (13.95, 14.00, 14.05, 14.10)
COUPON_KNOB_HOLES = (7.2, 7.5)
COUPON_SIZE = (130.0, 38.0)
COUPON_DOT_D = 2.0
COUPON_DOT_PITCH = 4.0


def plate_to_case(x, v, w, front_height=FRONT_HEIGHT):
    """Map a plate-frame point to the case frame."""
    y = v * math.cos(SLOPE) - w * math.sin(SLOPE)
    z = front_height + v * math.sin(SLOPE) + w * math.cos(SLOPE)
    return (x, y, z)


def underside_z(y, plate_t):
    """z of the face's underside directly above case depth y."""
    return FRONT_HEIGHT + y * math.tan(SLOPE) - plate_t / math.cos(SLOPE)


def cradle_leg_points():
    """Plate (x, v) of the cradle legs."""
    return [(MODULE_X + dx, MODULE_V + dv) for dx, dv in CRADLE_LEGS]


def slot_centres():
    """Plate (x, v) of each speaker slot, centred on the speaker."""
    n = SLOT_COUNT
    return [(SPEAKER_X + (i - (n - 1) / 2) * SLOT_PITCH, SPEAKER_V) for i in range(n)]
