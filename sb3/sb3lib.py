"""sb3lib -- a small, dependency-free emitter for Scratch 3 projects (.sb3).

It writes a project.json that the real Scratch 3 GUI, scratch-vm and TurboWarp
can load, and zips it together with its SVG costume assets.

Programs are built as Python *expression trees*: reporters and booleans are
nested Python calls; scripts are Python lists whose first element is usually a
hat; C-blocks take Python lists as their bodies. Nothing is serialized until
``Project.to_json()`` / ``Project.save()``, so every node can be reused freely
(each use is emitted as a fresh copy with its own block id).

Quick example
-------------
::

    import sys; sys.path.insert(0, "sb3")
    from sb3lib import *

    p = Project()                          # stage + one sprite ("Sprite1")
    s = p.sprite
    total = p.var("total", 0)              # global (stage) variable
    i = s.var("i", 0)                      # sprite-local variable
    A = p.list("A", [0.1, 0.2, 0.3])       # global list, floats round-trip exactly
    go = p.broadcast("go")

    s.add_script([
        when_flag(),
        set_var(total, 0),
        set_var(i, 1),
        repeat(length_of(A), [
            change_var(total, item_of(A, i)),
            change_var(i, 1),
        ]),
        broadcast_and_wait(go),
    ])

    # custom block with number arguments, "run without screen refresh" on
    dot = Proc("dot %s %s", ["n", "k"], warp=True)
    s.add_script([
        define(dot),
        set_var(total, mul(dot.arg("n"), add(dot.arg("k"), 1))),
    ])
    s.add_script([when_received(go), dot(3, 4)])

    p.save("out/demo.sb3")                 # -> dict with sizes

Values accepted wherever a reporter input is expected
-----------------------------------------------------
* Python ``int`` / ``float`` / ``str`` / ``bool`` -> a literal shadow of the
  right kind (number, positive number, integer, text, colour ...). Floats are
  written with ``repr`` (shortest round-tripping form), so they parse back to
  the identical IEEE double in JavaScript.
* ``Var`` (from ``p.var`` / ``target.var``) -> the orange variable reporter.
* ``List`` -> the list reporter (``data_listcontents``).
* any reporter/boolean node (``add(...)``, ``item_of(...)``, ``proc.arg(..)``).

Boolean (hexagonal) inputs only accept boolean nodes (``lt``, ``gt``, ``eq``,
``and_``, ``or_``, ``not_``, ``list_contains``, ``str_contains``, boolean
``Proc`` args); passing anything else raises ``TypeError`` because the Scratch
editor cannot represent it.

API overview
------------
Project / targets
    Project(sprite_name="Sprite1", sprite_visible=True, sprite_xy=(0, 0))
    p.stage, p.sprite                     Target objects
    p.var(name, value=0)                  global variable  (== p.stage.var)
    p.list(name, items=())                global list      (== p.stage.list)
    p.broadcast(name)                     broadcast message
    target.var(name, value=0)             sprite-local variable
    target.list(name, items=())           sprite-local list
    target.add_script(blocks, x=None, y=None)   blocks = [hat, stmt, ...]
    p.to_json() -> dict                   project.json as a dict
    p.project_json_bytes() -> bytes
    p.save(path) -> {"path", "project_json_bytes", "sb3_bytes", "n_blocks"}
    p.block_count() -> {target_name: n_blocks}

Hats
    when_flag(), when_received(msg), define(proc)
Events
    broadcast(msg), broadcast_and_wait(msg)        msg: Broadcast or name str
Data (v: Var, L: List)
    set_var(v, x), change_var(v, x), show_var(v), hide_var(v)
    add_to_list(L, x), delete_of_list(L, i), delete_all(L),
    insert_at(L, i, x), replace_item(L, i, x)
    item_of(L, i), length_of(L), item_num_of(L, x), list_contains(L, x)
    show_list(L), hide_list(L)
Operators
    add, sub, mul, div, mod (a, b);  round_(x);  mathop(op, x)
        op in: abs floor ceiling sqrt sin cos tan asin acos atan ln log "e ^" "10 ^"
    lt, gt, eq (a, b);  and_, or_ (p, q);  not_(p)
    join(a, b), letter_of(i, s), str_length(s), str_contains(s, t), random(a, b)
Control
    repeat(n, body), repeat_until(cond, body), forever(body),
    if_(cond, body), if_else(cond, body, else_body), wait(sec),
    wait_until(cond), stop(option="this script")   # "all" | "this script" | "other scripts in sprite"
Sensing
    timer(), reset_timer()
Motion / looks (sprite only)
    goto_xy(x, y), change_x(dx), change_y(dy), set_x(x), set_y(y),
    x_position(), y_position(), point_in_direction(deg),
    show(), hide(), say(x), set_size(pct)
Pen extension ("pen" is added to project.extensions automatically)
    pen_clear(), pen_down(), pen_up(), pen_stamp(),
    set_pen_size(x), change_pen_size(x),
    set_pen_color(c)          c: "#rrggbb" literal, or any reporter; a number
                              r*65536 + g*256 + b is the fastest way to set RGB
    set_pen_param(param, x), change_pen_param(param, x)
                              param: "color" | "saturation" | "brightness" | "transparency"
Custom blocks
    P = Proc(spec, argnames, warp=True)   spec uses %s (number/text) and %b (boolean),
                                          e.g. Proc("dense %s %s", ["i", "j"]).
                                          If spec has no %, " %s" is appended per arg.
    define(P)                             hat; use as the first element of a script
    P(*args)  or call(P, *args)           the call statement
    P.arg(name)                           argument reporter for use inside the body
Escape hatch
    block(opcode, inputs={NAME: (kind, value)}, fields={NAME: value_or_obj},
          mutation=None, shape="stack"|"reporter"|"boolean"|"hat"|"cap")
    kinds: NUM POSNUM WHOLE INT ANGLE COLOR TEXT BOOL STACK BCAST, or
           menu(menu_opcode, field_name) for menu-shadow inputs.

Helpers
    round_sig(values, sig=6) -> list of floats rounded to `sig` significant digits
    count_evals(node) -> number of block evaluations to evaluate a reporter tree once

Encoding notes (what is emitted, and what we were unsure of)
------------------------------------------------------------
* Inputs follow the sb3 compressed form used by scratch-vm's serializer:
  ``[1, prim]`` unobscured shadow, ``[2, id]`` block without shadow (booleans,
  substacks), ``[3, id_or_prim, shadow_prim]`` block covering a shadow.
  Primitive codes: 4 math_number, 5 positive, 6 whole, 7 integer, 8 angle,
  9 colour, 10 text, 11 broadcast menu, 12 variable, 13 list.
* Literal numbers are written as JSON *strings* inside shadows (like the GUI
  does, e.g. ``[4, "0.1"]``); variable values and list items are written as
  JSON *numbers*.
* Obscured-shadow default values are "" (number/text) and "#000000" (colour).
  The GUI writes whatever the shadow previously held, so any value is valid.
* Procedure prototypes use ``argument_reporter_string_number`` shadows with
  ``%s``; Scratch 3 has no pure "number" argument type (``%n`` exists only for
  sb2 imports), so "number arguments" are %s arguments. The ``warp`` mutation
  attribute is written as the string "true"/"false" like the GUI;
  scratch-vm JSON.parses it (sequencer.stepToProcedure).
* Block ids are deterministic ("b1", "b2", ... per save); variables "v*",
  lists "l*", broadcasts "m*", procedure argument ids "a*".
* Layout (topLevel x/y) is a size *estimate* (stack block ~48 units tall,
  +8 per reporter nesting level, ~7 units per label character); scripts are
  stacked in columns. Right-click -> "Clean up blocks" in the editor if needed.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import numbers
import zipfile

__all__ = [
    # project
    "Project", "Target", "Var", "List", "Broadcast", "Proc",
    # kinds
    "NUM", "POSNUM", "WHOLE", "INT", "ANGLE", "COLOR", "TEXT", "BOOL", "STACK",
    "BCAST", "menu", "block",
    # hats / events
    "when_flag", "when_received", "define", "broadcast", "broadcast_and_wait",
    # data
    "set_var", "change_var", "show_var", "hide_var", "add_to_list",
    "delete_of_list", "delete_all", "insert_at", "replace_item", "item_of",
    "length_of", "item_num_of", "list_contains", "show_list", "hide_list",
    # operators
    "add", "sub", "mul", "div", "mod", "round_", "mathop", "lt", "gt", "eq",
    "and_", "or_", "not_", "join", "letter_of", "str_length", "str_contains",
    "random",
    # control
    "repeat", "repeat_until", "forever", "if_", "if_else", "wait", "wait_until",
    "stop",
    # sensing
    "timer", "reset_timer",
    # motion / looks
    "goto_xy", "change_x", "change_y", "set_x", "set_y", "x_position",
    "y_position", "point_in_direction", "show", "hide", "say", "set_size",
    # pen
    "pen_clear", "pen_down", "pen_up", "pen_stamp", "set_pen_size",
    "change_pen_size", "set_pen_color", "set_pen_param", "change_pen_param",
    # procedures
    "call",
    # helpers
    "round_sig", "count_evals", "STAGE_SVG", "DOT_SVG",
]

# --------------------------------------------------------------------------
# input kinds
# --------------------------------------------------------------------------
NUM, POSNUM, WHOLE, INT, ANGLE, COLOR, TEXT = (
    "num", "posnum", "whole", "int", "angle", "color", "text")
BOOL, STACK, BCAST = "bool", "stack", "broadcast"

_PRIM_CODE = {NUM: 4, POSNUM: 5, WHOLE: 6, INT: 7, ANGLE: 8, COLOR: 9, TEXT: 10}
_SHADOW_DEFAULT = {NUM: "", POSNUM: "", WHOLE: "", INT: "", ANGLE: "",
                   COLOR: "#000000", TEXT: ""}


class menu:
    """Input kind for a menu shadow block, e.g. menu("pen_menu_colorParam", "colorParam")."""

    def __init__(self, opcode, field, default=""):
        self.opcode, self.field, self.default = opcode, field, default

    def __repr__(self):
        return f"menu({self.opcode!r}, {self.field!r})"


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------
class Node:
    """Anything that can be emitted as a block."""
    shape = "reporter"


class Var(Node):
    """A scalar variable. Usable directly as a reporter input."""
    shape = "reporter"

    def __init__(self, name, vid, value, target):
        self.name, self.id, self.value, self.target = name, vid, value, target

    def __repr__(self):
        return f"Var({self.name!r})"


class List(Node):
    """A list. Usable as a reporter (the list contents) or as a list field."""
    shape = "reporter"

    def __init__(self, name, lid, items, target):
        self.name, self.id, self.items, self.target = name, lid, items, target

    def __repr__(self):
        return f"List({self.name!r}, n={len(self.items)})"


class Broadcast:
    def __init__(self, name, bid):
        self.name, self.id = name, bid

    def __repr__(self):
        return f"Broadcast({self.name!r})"


class Block(Node):
    """Generic block node. Prefer the helper functions; use `block()` as escape hatch."""

    def __init__(self, opcode, inputs=None, fields=None, mutation=None,
                 shape="stack", special=None):
        self.opcode = opcode
        self.inputs = dict(inputs or {})      # name -> (kind, value)
        self.fields = dict(fields or {})      # name -> str | Var | List | Broadcast | (value, id)
        self.mutation = mutation
        self.shape = shape                    # stack | cap | hat | reporter | boolean
        self.special = special                # internal: ("define", Proc)

    def __repr__(self):
        return f"Block({self.opcode})"


class Arg(Node):
    """A custom-block argument reporter (only valid inside that block's definition)."""

    def __init__(self, name, is_bool=False):
        self.name, self.is_bool = name, is_bool
        self.shape = "boolean" if is_bool else "reporter"


def block(opcode, inputs=None, fields=None, mutation=None, shape="stack"):
    """Escape hatch: any opcode. inputs = {NAME: (kind, value)}; kinds see module doc."""
    return Block(opcode, inputs, fields, mutation, shape)


# --------------------------------------------------------------------------
# custom blocks
# --------------------------------------------------------------------------
class Proc:
    """A custom block ("My Blocks").

    spec: proccode with %s (number or text) / %b (boolean) placeholders, e.g.
          "dense %s %s". If it contains no '%', " %s" is appended per arg.
    argnames: names for the arguments, in order.
    warp: the "run without screen refresh" checkbox.
    """
    _counter = 0

    def __init__(self, spec, argnames=(), warp=True):
        argnames = list(argnames)
        if "%" not in spec:
            spec = spec + "".join(" %s" for _ in argnames)
        kinds = []
        k = 0
        while True:
            k = spec.find("%", k)
            if k < 0:
                break
            if spec[k + 1:k + 2] in ("s", "b", "n"):
                kinds.append(spec[k + 1])
                k += 2
            else:
                k += 1
        if len(kinds) != len(argnames):
            raise ValueError(f"spec {spec!r} has {len(kinds)} placeholders but "
                             f"{len(argnames)} argnames were given")
        if len(set(argnames)) != len(argnames):
            raise ValueError("argument names must be unique")
        self.proccode = spec
        self.argnames = argnames
        self.argkinds = kinds
        Proc._counter += 1
        self._uid = Proc._counter
        self.argids = [f"a{self._uid}_{j}" for j in range(len(argnames))]
        self.warp = bool(warp)

    def arg(self, name):
        if name not in self.argnames:
            raise KeyError(f"{name!r} is not an argument of {self.proccode!r}")
        return Arg(name, self.argkinds[self.argnames.index(name)] == "b")

    def __call__(self, *args):
        return call(self, *args)

    def __repr__(self):
        return f"Proc({self.proccode!r}, warp={self.warp})"


def call(proc, *args):
    if len(args) != len(proc.argnames):
        raise TypeError(f"{proc.proccode!r} takes {len(proc.argnames)} args, got {len(args)}")
    inputs = {}
    for aid, kind, a in zip(proc.argids, proc.argkinds, args):
        inputs[aid] = (BOOL if kind == "b" else TEXT, a)
    mutation = {
        "tagName": "mutation", "children": [],
        "proccode": proc.proccode,
        "argumentids": json.dumps(proc.argids),
        "warp": "true" if proc.warp else "false",
    }
    return Block("procedures_call", inputs, None, mutation, "stack")


def define(proc):
    """Hat: procedures_definition (+ prototype shadow) for `proc`."""
    return Block("procedures_definition", shape="hat", special=("define", proc))


# --------------------------------------------------------------------------
# block helpers
# --------------------------------------------------------------------------
def _r(op, **inputs):
    return Block(op, {k: v for k, v in inputs.items()}, shape="reporter")


def _b(op, **inputs):
    return Block(op, {k: v for k, v in inputs.items()}, shape="boolean")


def _s(op, inputs=None, fields=None, mutation=None, shape="stack"):
    return Block(op, inputs, fields, mutation, shape)


# hats / events
def when_flag():
    return Block("event_whenflagclicked", shape="hat")


class _BRef:
    """Field value referring to a broadcast (by object or by name)."""

    def __init__(self, msg):
        self.msg = msg


def when_received(msg):
    return Block("event_whenbroadcastreceived", fields={"BROADCAST_OPTION": _BRef(msg)},
                 shape="hat")


def broadcast(msg):
    return _s("event_broadcast", {"BROADCAST_INPUT": (BCAST, msg)})


def broadcast_and_wait(msg):
    return _s("event_broadcastandwait", {"BROADCAST_INPUT": (BCAST, msg)})


# data
def _need(obj, cls, what):
    if not isinstance(obj, cls):
        raise TypeError(f"expected a {cls.__name__} for {what}, got {obj!r}")
    return obj


def set_var(v, x):
    return _s("data_setvariableto", {"VALUE": (TEXT, x)}, {"VARIABLE": _need(v, Var, "set_var")})


def change_var(v, x):
    return _s("data_changevariableby", {"VALUE": (NUM, x)}, {"VARIABLE": _need(v, Var, "change_var")})


def show_var(v):
    return _s("data_showvariable", None, {"VARIABLE": _need(v, Var, "show_var")})


def hide_var(v):
    return _s("data_hidevariable", None, {"VARIABLE": _need(v, Var, "hide_var")})


def add_to_list(L, x):
    return _s("data_addtolist", {"ITEM": (TEXT, x)}, {"LIST": _need(L, List, "add_to_list")})


def delete_of_list(L, i):
    return _s("data_deleteoflist", {"INDEX": (INT, i)}, {"LIST": _need(L, List, "delete_of_list")})


def delete_all(L):
    return _s("data_deletealloflist", None, {"LIST": _need(L, List, "delete_all")})


def insert_at(L, i, x):
    return _s("data_insertatlist", {"ITEM": (TEXT, x), "INDEX": (INT, i)},
              {"LIST": _need(L, List, "insert_at")})


def replace_item(L, i, x):
    return _s("data_replaceitemoflist", {"INDEX": (INT, i), "ITEM": (TEXT, x)},
              {"LIST": _need(L, List, "replace_item")})


def item_of(L, i):
    return Block("data_itemoflist", {"INDEX": (INT, i)}, {"LIST": _need(L, List, "item_of")},
                 shape="reporter")


def length_of(L):
    return Block("data_lengthoflist", None, {"LIST": _need(L, List, "length_of")}, shape="reporter")


def item_num_of(L, x):
    return Block("data_itemnumoflist", {"ITEM": (TEXT, x)}, {"LIST": _need(L, List, "item_num_of")},
                 shape="reporter")


def list_contains(L, x):
    return Block("data_listcontainsitem", {"ITEM": (TEXT, x)},
                 {"LIST": _need(L, List, "list_contains")}, shape="boolean")


def show_list(L):
    return _s("data_showlist", None, {"LIST": _need(L, List, "show_list")})


def hide_list(L):
    return _s("data_hidelist", None, {"LIST": _need(L, List, "hide_list")})


# operators
def add(a, b): return _r("operator_add", NUM1=(NUM, a), NUM2=(NUM, b))
def sub(a, b): return _r("operator_subtract", NUM1=(NUM, a), NUM2=(NUM, b))
def mul(a, b): return _r("operator_multiply", NUM1=(NUM, a), NUM2=(NUM, b))
def div(a, b): return _r("operator_divide", NUM1=(NUM, a), NUM2=(NUM, b))
def mod(a, b): return _r("operator_mod", NUM1=(NUM, a), NUM2=(NUM, b))
def round_(x): return _r("operator_round", NUM=(NUM, x))
def random(a, b): return _r("operator_random", FROM=(NUM, a), TO=(NUM, b))
def lt(a, b): return _b("operator_lt", OPERAND1=(TEXT, a), OPERAND2=(TEXT, b))
def gt(a, b): return _b("operator_gt", OPERAND1=(TEXT, a), OPERAND2=(TEXT, b))
def eq(a, b): return _b("operator_equals", OPERAND1=(TEXT, a), OPERAND2=(TEXT, b))
def and_(p, q): return _b("operator_and", OPERAND1=(BOOL, p), OPERAND2=(BOOL, q))
def or_(p, q): return _b("operator_or", OPERAND1=(BOOL, p), OPERAND2=(BOOL, q))
def not_(p): return _b("operator_not", OPERAND=(BOOL, p))
def join(a, b): return _r("operator_join", STRING1=(TEXT, a), STRING2=(TEXT, b))
def letter_of(i, s): return _r("operator_letter_of", LETTER=(WHOLE, i), STRING=(TEXT, s))
def str_length(s): return _r("operator_length", STRING=(TEXT, s))
def str_contains(s, t): return _b("operator_contains", STRING1=(TEXT, s), STRING2=(TEXT, t))


_MATHOPS = {"abs", "floor", "ceiling", "sqrt", "sin", "cos", "tan", "asin",
            "acos", "atan", "ln", "log", "e ^", "10 ^"}


def mathop(op, x):
    if op not in _MATHOPS:
        raise ValueError(f"mathop {op!r} not in {sorted(_MATHOPS)}")
    return Block("operator_mathop", {"NUM": (NUM, x)}, {"OPERATOR": op}, shape="reporter")


# control
def _body(stmts):
    if isinstance(stmts, Node):
        stmts = [stmts]
    return list(stmts)


def repeat(n, body):
    return _s("control_repeat", {"TIMES": (WHOLE, n), "SUBSTACK": (STACK, _body(body))})


def repeat_until(cond, body):
    return _s("control_repeat_until", {"CONDITION": (BOOL, cond), "SUBSTACK": (STACK, _body(body))})


def forever(body):
    return _s("control_forever", {"SUBSTACK": (STACK, _body(body))}, shape="cap")


def if_(cond, body):
    return _s("control_if", {"CONDITION": (BOOL, cond), "SUBSTACK": (STACK, _body(body))})


def if_else(cond, body, else_body):
    return _s("control_if_else", {"CONDITION": (BOOL, cond), "SUBSTACK": (STACK, _body(body)),
                                  "SUBSTACK2": (STACK, _body(else_body))})


def wait(sec):
    return _s("control_wait", {"DURATION": (POSNUM, sec)})


def wait_until(cond):
    return _s("control_wait_until", {"CONDITION": (BOOL, cond)})


_STOP = ("all", "this script", "other scripts in sprite", "other scripts in stage")


def stop(option="this script"):
    if option not in _STOP:
        raise ValueError(f"stop option must be one of {_STOP}")
    hasnext = option.startswith("other")
    return _s("control_stop", None, {"STOP_OPTION": option},
              {"tagName": "mutation", "children": [], "hasnext": "true" if hasnext else "false"},
              shape="stack" if hasnext else "cap")


# sensing
def timer(): return Block("sensing_timer", shape="reporter")
def reset_timer(): return _s("sensing_resettimer")


# motion / looks
def goto_xy(x, y): return _s("motion_gotoxy", {"X": (NUM, x), "Y": (NUM, y)})
def change_x(dx): return _s("motion_changexby", {"DX": (NUM, dx)})
def change_y(dy): return _s("motion_changeyby", {"DY": (NUM, dy)})
def set_x(x): return _s("motion_setx", {"X": (NUM, x)})
def set_y(y): return _s("motion_sety", {"Y": (NUM, y)})
def x_position(): return Block("motion_xposition", shape="reporter")
def y_position(): return Block("motion_yposition", shape="reporter")
def point_in_direction(d): return _s("motion_pointindirection", {"DIRECTION": (ANGLE, d)})
def show(): return _s("looks_show")
def hide(): return _s("looks_hide")
def say(x): return _s("looks_say", {"MESSAGE": (TEXT, x)})
def set_size(p): return _s("looks_setsizeto", {"SIZE": (NUM, p)})


# pen
_PEN_PARAM = menu("pen_menu_colorParam", "colorParam", "color")
_PEN_PARAMS = ("color", "saturation", "brightness", "transparency")


def pen_clear(): return _s("pen_clear")
def pen_down(): return _s("pen_penDown")
def pen_up(): return _s("pen_penUp")
def pen_stamp(): return _s("pen_stamp")
def set_pen_size(x): return _s("pen_setPenSizeTo", {"SIZE": (NUM, x)})
def change_pen_size(x): return _s("pen_changePenSizeBy", {"SIZE": (NUM, x)})
def set_pen_color(c): return _s("pen_setPenColorToColor", {"COLOR": (COLOR, c)})


def set_pen_param(param, x):
    if isinstance(param, str) and param not in _PEN_PARAMS:
        raise ValueError(f"pen param must be one of {_PEN_PARAMS}")
    return _s("pen_setPenColorParamTo", {"COLOR_PARAM": (_PEN_PARAM, param), "VALUE": (NUM, x)})


def change_pen_param(param, x):
    if isinstance(param, str) and param not in _PEN_PARAMS:
        raise ValueError(f"pen param must be one of {_PEN_PARAMS}")
    return _s("pen_changePenColorParamBy", {"COLOR_PARAM": (_PEN_PARAM, param), "VALUE": (NUM, x)})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def round_sig(values, sig=6):
    """Round each number to `sig` significant digits (returns Python floats)."""
    fmt = f".{int(sig)}g"
    return [float(format(float(v), fmt)) for v in values]


def count_evals(node):
    """Block evaluations to evaluate `node` once (reporters/booleans incl. nested;
    variable reporters count 1, literals/shadows 0)."""
    if isinstance(node, (Var, List, Arg)):
        return 1
    if isinstance(node, Block):
        n = 1
        for kind, v in node.inputs.values():
            if kind == STACK:
                continue
            if isinstance(v, Node):
                n += count_evals(v)
        return n
    return 0


def _plain(v):
    """Convert numpy scalars etc. to plain Python values; validate."""
    if isinstance(v, bool):
        return v
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"non-finite number {v!r} cannot be stored in JSON")
        return f
    if isinstance(v, str):
        return v
    raise TypeError(f"unsupported value {v!r} ({type(v).__name__})")


def _lit(v):
    """Literal -> string for a shadow field (GUI style)."""
    v = _plain(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e16 and not (v == 0 and math.copysign(1, v) < 0):
            return str(int(v))
        return repr(v)
    return v


STAGE_SVG = (
    '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="480" height="360" '
    'viewBox="0 0 480 360"><rect x="0" y="0" width="480" height="360" fill="#ffffff"/></svg>'
)
DOT_SVG = (
    '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
    'viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#4c97ff" stroke="#3373cc" '
    'stroke-width="1"/></svg>'
)


def _costume(name, svg, cx, cy):
    data = svg.encode("utf-8")
    md5 = hashlib.md5(data).hexdigest()
    meta = {"name": name, "dataFormat": "svg", "assetId": md5, "md5ext": md5 + ".svg",
            "rotationCenterX": cx, "rotationCenterY": cy}
    return meta, (md5 + ".svg", data)


# --------------------------------------------------------------------------
# targets and project
# --------------------------------------------------------------------------
class Target:
    def __init__(self, project, name, is_stage):
        self.project = project
        self.name = name
        self.is_stage = is_stage
        self.vars = {}      # name -> Var
        self.lists = {}     # name -> List
        self.scripts = []   # (blocks, x, y)

    # variables ------------------------------------------------------------
    def var(self, name, value=0):
        self.project._check_name("var", name, self)
        v = Var(name, self.project._new_id("v"), _plain(value), self)
        self.vars[name] = v
        return v

    def list(self, name, items=()):
        self.project._check_name("list", name, self)
        if hasattr(items, "tolist"):
            items = items.tolist()
        items = [_plain(x) for x in items]
        L = List(name, self.project._new_id("l"), items, self)
        self.lists[name] = L
        return L

    # scripts --------------------------------------------------------------
    def add_script(self, blocks, x=None, y=None):
        blocks = _body(blocks)
        if not blocks:
            raise ValueError("empty script")
        for j, b in enumerate(blocks):
            if not isinstance(b, Block) or b.shape in ("reporter", "boolean"):
                raise TypeError(f"script element {j} is not a stack block: {b!r}")
            if j > 0 and b.shape == "hat":
                raise TypeError("a hat block may only start a script")
            if b.shape == "cap" and j != len(blocks) - 1:
                raise TypeError(f"{b.opcode} is a cap block and must be last")
        if self.is_stage:
            sprite_only = ("motion_", "looks_say", "looks_show", "looks_hide",
                           "looks_setsizeto", "pen_penDown", "pen_penUp", "pen_stamp",
                           "pen_setPen", "pen_changePen")
            for b in _walk(blocks):
                if isinstance(b, Block) and b.opcode.startswith(sprite_only):
                    raise TypeError(f"{b.opcode} is not available on the stage")
        self.scripts.append((blocks, x, y))
        return blocks


def _walk(nodes):
    """Yield all nodes in a list of statements, recursively."""
    stack = list(nodes)
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, Block):
            for kind, v in n.inputs.values():
                if kind == STACK:
                    stack.extend(v)
                elif isinstance(v, Node):
                    stack.append(v)


class Project:
    def __init__(self, sprite_name="Sprite1", sprite_visible=True, sprite_xy=(0, 0),
                 sprite_svg=DOT_SVG, sprite_center=(8, 8), stage_svg=STAGE_SVG):
        self._ids = {}
        self.stage = Target(self, "Stage", True)
        self.sprite = Target(self, sprite_name, False)
        self.sprite_visible = bool(sprite_visible)
        self.sprite_xy = sprite_xy
        self.broadcasts = {}
        self._stage_costume = _costume("backdrop1", stage_svg, 240, 180)
        self._sprite_costume = _costume("costume1", sprite_svg, *sprite_center)

    # ids ------------------------------------------------------------------
    def _new_id(self, prefix):
        self._ids[prefix] = self._ids.get(prefix, 0) + 1
        return f"{prefix}{self._ids[prefix]}"

    def _check_name(self, kind, name, target):
        if not isinstance(name, str) or not name:
            raise ValueError("names must be non-empty strings")
        attr = "vars" if kind == "var" else "lists"
        if name in getattr(target, attr):
            raise ValueError(f"{kind} {name!r} already exists on {target.name}")
        other = self.sprite if target.is_stage else self.stage
        if name in getattr(other, attr):
            raise ValueError(f"{kind} {name!r} would clash between stage and sprite")

    # convenience ------------------------------------------------------------
    def var(self, name, value=0):
        return self.stage.var(name, value)

    def list(self, name, items=()):
        return self.stage.list(name, items)

    def broadcast(self, name):
        if name in self.broadcasts:
            return self.broadcasts[name]
        b = Broadcast(name, self._new_id("m"))
        self.broadcasts[name] = b
        return b

    def _bcast(self, msg):
        if isinstance(msg, Broadcast):
            if self.broadcasts.get(msg.name) is not msg:
                raise ValueError(f"{msg!r} belongs to another project")
            return msg
        if isinstance(msg, str):
            return self.broadcast(msg)
        raise TypeError(f"expected Broadcast or str, got {msg!r}")

    # serialization -----------------------------------------------------------
    def to_json(self):
        em = _Emitter(self)
        targets = []
        for t in (self.stage, self.sprite):
            blocks = em.emit_target(t)
            d = {
                "isStage": t.is_stage,
                "name": t.name,
                "variables": {v.id: [v.name, v.value] for v in t.vars.values()},
                "lists": {L.id: [L.name, L.items] for L in t.lists.values()},
                "broadcasts": ({b.id: b.name for b in self.broadcasts.values()}
                               if t.is_stage else {}),
                "blocks": blocks,
                "comments": {},
                "currentCostume": 0,
                "costumes": [dict((self._stage_costume if t.is_stage else self._sprite_costume)[0])],
                "sounds": [],
                "volume": 100,
                "layerOrder": 0 if t.is_stage else 1,
            }
            if t.is_stage:
                d.update({"tempo": 60, "videoTransparency": 50, "videoState": "on",
                          "textToSpeechLanguage": None})
            else:
                d.update({"visible": self.sprite_visible, "x": self.sprite_xy[0],
                          "y": self.sprite_xy[1], "size": 100, "direction": 90,
                          "draggable": False, "rotationStyle": "all around"})
            targets.append(d)
        # broadcasts referenced only through blocks were registered during emission;
        # refresh the stage's broadcast table.
        targets[0]["broadcasts"] = {b.id: b.name for b in self.broadcasts.values()}
        exts = []
        if em.uses_pen:
            exts.append("pen")
        return {
            "targets": targets,
            "monitors": [],
            "extensions": exts,
            "meta": {"semver": "3.0.0", "vm": "0.2.0", "agent": "sb3lib/0.1 (python)"},
        }

    def project_json_bytes(self):
        return json.dumps(self.to_json(), separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")

    def assets(self):
        out = dict([self._stage_costume[1], self._sprite_costume[1]])
        return out

    def save(self, path, compresslevel=6):
        pj = self.project_json_bytes()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as z:
            z.writestr("project.json", pj)
            for name, data in sorted(self.assets().items()):
                z.writestr(name, data)
        data = buf.getvalue()
        with open(path, "wb") as f:
            f.write(data)
        return {"path": str(path), "project_json_bytes": len(pj), "sb3_bytes": len(data),
                "n_blocks": sum(self.block_count().values())}

    def block_count(self):
        d = self.to_json()
        return {t["name"]: len(t["blocks"]) for t in d["targets"]}


# --------------------------------------------------------------------------
# emitter
# --------------------------------------------------------------------------
class _Emitter:
    def __init__(self, project):
        self.p = project
        self.n = 0
        self.uses_pen = False
        self.blocks = None
        self.target = None

    def nid(self):
        self.n += 1
        return f"b{self.n}"

    def emit_target(self, t):
        self.blocks = {}
        self.target = t
        col_x, y, col_w = 0, 0, 0
        COL_H = 1600
        for stmts, x0, y0 in t.scripts:
            w, h = _estimate_stack(stmts)
            if x0 is None or y0 is None:
                if y > 0 and y + h > COL_H:
                    col_x += col_w + 80
                    y, col_w = 0, 0
                x0, y0 = col_x, y
                y += h + 60
                col_w = max(col_w, w)
            self.emit_script(stmts, x0, y0)
        return self.blocks

    def _check_var(self, v):
        if v.target is not self.target and not v.target.is_stage:
            raise ValueError(f"{v!r} is local to {v.target.name} but used in {self.target.name}")
        if v.target.project is not self.p:
            raise ValueError(f"{v!r} belongs to another project")

    def emit_script(self, stmts, x, y):
        first = stmts[0]
        if first.shape == "hat":
            hid = self.emit_block(first, None, top=(x, y))
            if len(stmts) > 1:
                nxt = self.emit_stack(stmts[1:], hid)
                self.blocks[hid]["next"] = nxt
        else:
            self.emit_stack(stmts, None, top=(x, y))

    def emit_stack(self, stmts, parent, top=None):
        prev = None
        first = None
        for j, b in enumerate(stmts):
            if not isinstance(b, Block) or b.shape in ("reporter", "boolean", "hat"):
                raise TypeError(f"not a stack block: {b!r}")
            if b.shape == "cap" and j != len(stmts) - 1:
                raise TypeError(f"{b.opcode} is a cap block and must be last in its stack")
            bid = self.emit_block(b, prev if prev else parent, top=top if j == 0 else None)
            if prev:
                self.blocks[prev]["next"] = bid
            else:
                first = bid
            prev = bid
        return first

    def emit_block(self, b, parent, top=None, shadow=False):
        bid = self.nid()
        d = {"opcode": b.opcode, "next": None, "parent": parent, "inputs": {}, "fields": {},
             "shadow": shadow, "topLevel": top is not None}
        if top is not None:
            d["x"], d["y"] = int(top[0]), int(top[1])
        self.blocks[bid] = d
        if b.opcode.startswith("pen_"):
            self.uses_pen = True

        if b.special and b.special[0] == "define":
            self._emit_define(b.special[1], bid, d)
            return bid

        for name, (kind, val) in b.inputs.items():
            enc = self.emit_input(kind, val, bid)
            if enc is not None:
                d["inputs"][name] = enc
        for name, val in b.fields.items():
            d["fields"][name] = self.emit_field(val)
        if b.mutation is not None:
            d["mutation"] = dict(b.mutation)
        return bid

    def _emit_define(self, proc, bid, d):
        pid = self.nid()
        d["inputs"]["custom_block"] = [1, pid]
        proto = {"opcode": "procedures_prototype", "next": None, "parent": bid, "inputs": {},
                 "fields": {}, "shadow": True, "topLevel": False,
                 "mutation": {
                     "tagName": "mutation", "children": [],
                     "proccode": proc.proccode,
                     "argumentids": json.dumps(proc.argids),
                     "argumentnames": json.dumps(proc.argnames),
                     "argumentdefaults": json.dumps(
                         ["false" if k == "b" else "" for k in proc.argkinds]),
                     "warp": "true" if proc.warp else "false",
                 }}
        self.blocks[pid] = proto
        for aid, name, kind in zip(proc.argids, proc.argnames, proc.argkinds):
            rid = self.nid()
            self.blocks[rid] = {
                "opcode": "argument_reporter_boolean" if kind == "b"
                else "argument_reporter_string_number",
                "next": None, "parent": pid, "inputs": {}, "fields": {"VALUE": [name, None]},
                "shadow": True, "topLevel": False}
            proto["inputs"][aid] = [1, rid]

    def emit_field(self, val):
        if isinstance(val, (Var, List)):
            self._check_var(val)
            return [val.name, val.id]
        if isinstance(val, (Broadcast, _BRef)):
            b = self.p._bcast(val.msg if isinstance(val, _BRef) else val)
            return [b.name, b.id]
        if isinstance(val, tuple) and len(val) == 2:
            return [val[0], val[1]]
        if isinstance(val, str):
            return [val, None]
        raise TypeError(f"bad field value {val!r}")

    def emit_reporter(self, node, parent):
        """Emit an expression node; returns block id or a compact primitive array."""
        if isinstance(node, Var):
            self._check_var(node)
            return [12, node.name, node.id]
        if isinstance(node, List):
            self._check_var(node)
            return [13, node.name, node.id]
        if isinstance(node, Arg):
            bid = self.nid()
            self.blocks[bid] = {
                "opcode": "argument_reporter_boolean" if node.is_bool
                else "argument_reporter_string_number",
                "next": None, "parent": parent, "inputs": {},
                "fields": {"VALUE": [node.name, None]}, "shadow": False, "topLevel": False}
            return bid
        if isinstance(node, Block):
            if node.shape not in ("reporter", "boolean"):
                raise TypeError(f"{node.opcode} is a {node.shape} block, not a reporter")
            return self.emit_block(node, parent)
        raise TypeError(f"not an expression: {node!r}")

    def emit_input(self, kind, val, parent):
        if kind == STACK:
            if not val:
                return None
            return [2, self.emit_stack(val, parent)]
        if kind == BOOL:
            if val is None:
                return None
            if not isinstance(val, Node) or val.shape != "boolean":
                raise TypeError(f"boolean input needs a boolean block, got {val!r}")
            return [2, self.emit_reporter(val, parent)]
        if kind == BCAST:
            b = self.p._bcast(val)
            return [1, [11, b.name, b.id]]
        if isinstance(kind, menu):
            mid = self.nid()
            default = val if isinstance(val, str) else kind.default
            self.blocks[mid] = {"opcode": kind.opcode, "next": None, "parent": parent,
                                "inputs": {}, "fields": {kind.field: [default, None]},
                                "shadow": True, "topLevel": False}
            if isinstance(val, Node):
                return [3, self.emit_reporter(val, parent), mid]
            return [1, mid]
        if kind not in _PRIM_CODE:
            raise ValueError(f"unknown input kind {kind!r}")
        code = _PRIM_CODE[kind]
        if isinstance(val, Node):
            return [3, self.emit_reporter(val, parent), [code, _SHADOW_DEFAULT[kind]]]
        if val is None:
            return [1, [code, _SHADOW_DEFAULT[kind]]]
        return [1, [code, _lit(val)]]


# --------------------------------------------------------------------------
# layout estimate
# --------------------------------------------------------------------------
def _expr_size(v):
    """(width, nesting depth) estimate for an input value."""
    if isinstance(v, (Var, List, Arg)):
        name = v.name
        return 14 + 7 * len(name), 1
    if isinstance(v, Block):
        w = 20 + 6 * len(v.opcode.split("_", 1)[-1])
        depth = 0
        for kind, x in v.inputs.values():
            cw, cd = _expr_size(x)
            w += cw + 8
            depth = max(depth, cd)
        for f in v.fields.values():
            w += 14 + 7 * len(getattr(f, "name", f if isinstance(f, str) else "xx"))
        return w, depth + 1
    if v is None:
        return 40, 0
    if isinstance(v, Broadcast):
        return 30 + 7 * len(v.name), 0
    if isinstance(v, (str, numbers.Real)):
        return max(40, 8 + 7 * len(_lit(v))), 0
    return 40, 0


def _estimate_block(b):
    """(width, height) of a stack/hat block, including its substacks."""
    w = 30 + 6 * len(b.opcode.split("_", 1)[-1])
    depth = 0
    subs = []
    for kind, x in b.inputs.values():
        if kind == STACK:
            subs.append(x)
            continue
        cw, cd = _expr_size(x)
        w += cw + 8
        depth = max(depth, cd)
    for f in b.fields.values():
        w += 20 + 7 * len(getattr(f, "name", f if isinstance(f, str) else "xx"))
    if b.special and b.special[0] == "define":
        proc = b.special[1]
        w += 7 * len(proc.proccode) + 30 * len(proc.argnames)
        return w, 90
    h = 48 + 8 * depth
    if b.shape == "hat":
        h += 20
    for sub in subs:
        sw, sh = _estimate_stack(sub) if sub else (0, 24)
        w = max(w, 16 + sw)
        h += sh + 24
    return w, h


def _estimate_stack(stmts):
    w, h = 0, 0
    for b in stmts:
        bw, bh = _estimate_block(b)
        w, h = max(w, bw), h + bh
    return w, h


if __name__ == "__main__":  # tiny smoke test: python sb3/sb3lib.py out.sb3
    import sys
    p = Project()
    x = p.var("x", 0)
    p.sprite.add_script([when_flag(), set_var(x, add(40, 2))])
    print(p.save(sys.argv[1] if len(sys.argv) > 1 else "sb3lib_smoke.sb3"))
