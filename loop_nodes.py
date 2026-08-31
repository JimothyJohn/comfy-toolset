"""Counted-loop nodes built on ComfyUI node expansion.

A ComfyUI graph is a DAG, so a node can't literally feed into itself.
The supported mechanism (docs.comfy.org/custom-nodes/backend/expansion)
is node expansion: when the loop body finishes a pass, Repeat Close
clones the subgraph between Repeat Open and itself via GraphBuilder and
returns ``{"result": ..., "expand": ...}``; the executor splices the
copy in and runs it, carrying this pass's outputs in as the next pass's
inputs. Unrolling repeats until the counted passes are exhausted.

Unlike the while-loop reference pattern, no condition or counter wiring
is needed: Repeat Close reads the ``iterations`` widget value from the
dynprompt and threads a ``_remaining`` counter through each expansion
itself. The only loop wiring is FLOW_CONTROL plus your value slots.

These are the only nodes in the pack that touch a ComfyUI import
(``comfy_execution.graph_utils`` — the stable, documented expansion
API). The import is guarded so the module stays importable and testable
without ComfyUI; tests substitute GraphBuilder.
"""

try:
    from comfy_execution.graph_utils import (  # ty: ignore[unresolved-import]
        GraphBuilder,
        is_link,
    )
except ImportError:  # outside ComfyUI (tests patch GraphBuilder)
    GraphBuilder = None

    def is_link(obj):
        return isinstance(obj, list) and len(obj) == 2


try:
    from .nodes import ANY  # ty: ignore[unresolved-import]
except ImportError:
    from nodes import ANY

NUM_SLOTS = 4
_SLOT_NAMES = tuple(f"value{i}" for i in range(NUM_SLOTS))


class RepeatOpen:
    """Start of a counted loop. Pair with Repeat Close.

    ``iterations`` is the total number of passes (the body always runs
    at least once). ``index`` counts 0-based passes — drive per-shot
    prompts/seeds with it. ``_remaining`` is internal plumbing set by
    Repeat Close during expansion: leave it unconnected.
    """

    CATEGORY = "toolset"
    FUNCTION = "start"
    RETURN_TYPES = ("FLOW_CONTROL", "INT", "INT") + (ANY,) * NUM_SLOTS
    RETURN_NAMES = ("flow_control", "index", "iterations") + _SLOT_NAMES

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict[str, tuple] = {name: (ANY,) for name in _SLOT_NAMES}
        optional["_remaining"] = (
            "INT",
            {
                "forceInput": True,
                "tooltip": "Internal loop counter — leave unconnected.",
            },
        )
        return {
            "required": {
                "iterations": ("INT", {"default": 3, "min": 1, "max": 4096}),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        # Accepting `input_types` skips backend type validation; the
        # wildcard value slots accept any socket type by design.
        return True

    def start(self, iterations, _remaining=None, **kwargs):
        remaining = iterations if _remaining is None else _remaining
        index = iterations - remaining
        values = tuple(kwargs.get(name) for name in _SLOT_NAMES)
        # The FLOW_CONTROL output's value is never read: Repeat Close
        # declares it rawLink and uses the link itself to find this node.
        return ("flow", index, iterations) + values


class RepeatClose:
    """End of a counted loop. Pair with Repeat Open.

    Wire flow_control from Repeat Open, feed the loop-carried values
    into the value slots, and read the final values from the outputs.
    Everything between the pair re-executes ``iterations`` times, each
    pass seeing the previous pass's value slots.
    """

    CATEGORY = "toolset"
    FUNCTION = "finish"
    RETURN_TYPES = (ANY,) * NUM_SLOTS
    RETURN_NAMES = _SLOT_NAMES

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flow_control": ("FLOW_CONTROL", {"rawLink": True}),
            },
            "optional": {name: (ANY,) for name in _SLOT_NAMES},
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    @staticmethod
    def _upstream_edges(close_id, dynprompt):
        """Map each node upstream of ``close_id`` to its downstream children."""
        upstream = {}
        stack = [close_id]
        while stack:
            node_id = stack.pop()
            inputs = dynprompt.get_node(node_id).get("inputs", {})
            for value in inputs.values():
                if is_link(value):
                    parent_id = value[0]
                    if parent_id not in upstream:
                        upstream[parent_id] = []
                        stack.append(parent_id)
                    upstream[parent_id].append(node_id)
        return upstream

    @staticmethod
    def _contained(open_id, close_id, upstream):
        """Nodes reachable downstream from the open node — the loop body."""
        contained = {open_id, close_id}
        stack = [open_id]
        while stack:
            for child_id in upstream.get(stack.pop(), ()):
                if child_id not in contained:
                    contained.add(child_id)
                    stack.append(child_id)
        return contained

    def finish(self, flow_control, dynprompt=None, unique_id=None, **kwargs):
        if dynprompt is None or unique_id is None:
            raise RuntimeError(
                "RepeatClose requires ComfyUI's executor (dynprompt/unique_id)."
            )
        if not is_link(flow_control):
            raise ValueError(
                "RepeatClose: flow_control must be connected straight from "
                "a Repeat Open node."
            )
        open_id = flow_control[0]
        open_inputs = dynprompt.get_node(open_id).get("inputs", {})
        iterations = open_inputs.get("iterations")
        if iterations is None:
            raise ValueError(
                "RepeatClose: flow_control is not connected to a Repeat Open node."
            )
        if is_link(iterations):
            raise ValueError(
                "RepeatClose: 'iterations' on Repeat Open must be a widget "
                "value, not a connection — the loop count is read before "
                "the graph runs."
            )
        remaining = open_inputs.get("_remaining")
        if remaining is None:
            remaining = iterations

        if remaining <= 1:
            return tuple(kwargs.get(name) for name in _SLOT_NAMES)

        # Unroll one more pass: clone the loop body, feed this pass's
        # outputs in as the clone's starting values.
        builder = GraphBuilder
        if builder is None:
            raise RuntimeError(
                "RepeatClose: comfy_execution.graph_utils is unavailable — "
                "loop expansion only works inside ComfyUI."
            )
        upstream = self._upstream_edges(unique_id, dynprompt)
        contained = self._contained(open_id, unique_id, upstream)

        graph = builder()
        # "Recurse" keeps the clone-of-self id from growing per pass;
        # other clones keep their original ids (GraphBuilder prefixes
        # them uniquely per expansion).
        for node_id in contained:
            info = dynprompt.get_node(node_id)
            node = graph.node(
                info["class_type"], "Recurse" if node_id == unique_id else node_id
            )
            node.set_override_display_id(node_id)
        for node_id in contained:
            info = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for key, value in info.get("inputs", {}).items():
                if is_link(value) and value[0] in contained:
                    node.set_input(key, graph.lookup_node(value[0]).out(value[1]))
                else:
                    node.set_input(key, value)

        clone_open = graph.lookup_node(open_id)
        clone_open.set_input("_remaining", remaining - 1)
        for name in _SLOT_NAMES:
            clone_open.set_input(name, kwargs.get(name))

        clone_close = graph.lookup_node("Recurse")
        return {
            "result": tuple(clone_close.out(i) for i in range(NUM_SLOTS)),
            "expand": graph.finalize(),
        }


LOOP_NODE_CLASS_MAPPINGS = {
    "RepeatOpen": RepeatOpen,
    "RepeatClose": RepeatClose,
}

LOOP_NODE_DISPLAY_NAME_MAPPINGS = {
    "RepeatOpen": "Repeat Open (Loop Start)",
    "RepeatClose": "Repeat Close (Loop End)",
}
