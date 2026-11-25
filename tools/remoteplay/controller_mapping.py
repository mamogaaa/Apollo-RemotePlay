"""Remote Play controller to Apollo input fields (no transport dependency)."""

BUTTONS = {
    0x88: 0x1000,
    0x89: 0x2000,
    0x8A: 0x4000,
    0x8B: 0x8000,
    0x80: 1,
    0x81: 2,
    0x82: 4,
    0x83: 8,
    0x84: 0x100,
    0x85: 0x200,
    0x8C: 0x10,
    0x8D: 0x20,
    0x8E: 0x400,
    0x8F: 0x40,
    0x90: 0x80,
    0x91: 0x100000,
}


def map_controller(controller):
    buttons = sum(
        flag for code, flag in BUTTONS.items() if controller.buttons.get(code, 0)
    )
    lx, ly, rx, ry = controller.axes
    return (
        buttons,
        controller.buttons.get(0x86, 0),
        controller.buttons.get(0x87, 0),
        lx,
        max(-32768, min(32767, -ly)),
        rx,
        max(-32768, min(32767, -ry)),
    )
