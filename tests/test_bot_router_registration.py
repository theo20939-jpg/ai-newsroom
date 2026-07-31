"""Phase 16 callback-runtime fix: guards that `bot.main`'s dispatcher actually carries the M6
image-preview callback router - the persistent `telegram_bot` service (docker-compose.yml) is
only useful if this wiring stays intact. No network access, no Docker required.
"""
from bot.handlers import router as root_router
from bot.handlers.image_preview import router as image_preview_router


def test_root_router_includes_image_preview_router() -> None:
    assert image_preview_router in root_router.sub_routers


def test_root_router_sub_router_names_include_image_preview() -> None:
    names = [sub.name for sub in root_router.sub_routers]
    assert "image_preview" in names


def test_bot_main_registers_root_router_on_its_dispatcher() -> None:
    import ast
    import inspect

    import bot.main as bot_main

    source = inspect.getsource(bot_main.main)
    tree = ast.parse(source)
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "include_router" in calls
    assert "start_polling" in calls
