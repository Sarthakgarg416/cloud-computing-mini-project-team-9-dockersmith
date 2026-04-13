"""
CLI entry point for docksmith commands.
"""

import argparse
import sys

from internal.build.engine import BuildEngine
from internal.store.image_store import ImageStore
from internal.runtime.container import ContainerRuntime


def cmd_build(args):
    engine = BuildEngine(
        context_dir=args.context,
        tag=args.t,
        no_cache=args.no_cache,
    )
    engine.build()


def cmd_images(args):
    store = ImageStore()
    store.list_images()


def cmd_rmi(args):
    store = ImageStore()
    store.remove_image(args.name_tag)


def cmd_run(args):
    env_overrides = {}
    if args.e:
        for pair in args.e:
            k, _, v = pair.partition("=")
            env_overrides[k] = v

    runtime = ContainerRuntime()
    runtime.run(
        name_tag=args.name_tag,
        cmd_override=args.cmd if args.cmd else None,
        env_overrides=env_overrides,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="docksmith",
        description="A simplified Docker-like build and runtime system.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build
    # --no-cache is declared before 'context' so argparse accepts it in any position:
    #   docksmith build -t name:tag <context> [--no-cache]
    #   docksmith build -t name:tag --no-cache <context>
    build_parser = subparsers.add_parser("build", help="Build an image from a Docksmithfile")
    build_parser.add_argument("-t", metavar="name:tag", required=True, help="Name and tag for the image")
    build_parser.add_argument("--no-cache", action="store_true", help="Skip all cache lookups and writes for this build")
    build_parser.add_argument("context", help="Build context directory")

    # images
    subparsers.add_parser("images", help="List all images in the local store")

    # rmi
    rmi_parser = subparsers.add_parser("rmi", help="Remove an image")
    rmi_parser.add_argument("name_tag", metavar="name:tag", help="Image to remove")

    # run
    run_parser = subparsers.add_parser("run", help="Run a container from an image")
    run_parser.add_argument("name_tag", metavar="name:tag", help="Image to run")
    run_parser.add_argument("cmd", nargs="?", default=None, help="Command override")
    run_parser.add_argument("-e", metavar="KEY=VALUE", action="append", help="Environment variable override (repeatable)")

    args = parser.parse_args()

    dispatch = {
        "build": cmd_build,
        "images": cmd_images,
        "rmi": cmd_rmi,
        "run": cmd_run,
    }
    dispatch[args.command](args)
