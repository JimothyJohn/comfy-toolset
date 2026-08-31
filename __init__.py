try:
    # ComfyUI loads this directory as a package.
    from .loop_nodes import (  # ty: ignore[unresolved-import]
        LOOP_NODE_CLASS_MAPPINGS,
        LOOP_NODE_DISPLAY_NAME_MAPPINGS,
    )
    from .nodes import (  # ty: ignore[unresolved-import]
        NODE_CLASS_MAPPINGS as _BASE_CLASS_MAPPINGS,
    )
    from .nodes import (  # ty: ignore[unresolved-import]
        NODE_DISPLAY_NAME_MAPPINGS as _BASE_DISPLAY_NAME_MAPPINGS,
    )
except ImportError:
    # Imported outside a package context (pytest, tooling).
    from loop_nodes import (
        LOOP_NODE_CLASS_MAPPINGS,
        LOOP_NODE_DISPLAY_NAME_MAPPINGS,
    )
    from nodes import (
        NODE_CLASS_MAPPINGS as _BASE_CLASS_MAPPINGS,
    )
    from nodes import (
        NODE_DISPLAY_NAME_MAPPINGS as _BASE_DISPLAY_NAME_MAPPINGS,
    )

NODE_CLASS_MAPPINGS = {**_BASE_CLASS_MAPPINGS, **LOOP_NODE_CLASS_MAPPINGS}
NODE_DISPLAY_NAME_MAPPINGS = {
    **_BASE_DISPLAY_NAME_MAPPINGS,
    **LOOP_NODE_DISPLAY_NAME_MAPPINGS,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
