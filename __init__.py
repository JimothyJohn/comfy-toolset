try:
    # ComfyUI loads this directory as a package.
    from .nodes import (  # ty: ignore[unresolved-import]
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
    )
except ImportError:
    # Imported outside a package context (pytest, tooling).
    from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
