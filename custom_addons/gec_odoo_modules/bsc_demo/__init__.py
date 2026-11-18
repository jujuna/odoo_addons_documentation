from .demo_builder import build_demo


def post_init_hook(env):
    build_demo(env)
