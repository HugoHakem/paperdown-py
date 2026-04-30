from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


SUPPORTED_INPUT_SUFFIXES = {".pdf"}
DEFAULT_ABANDON_LABELS = [
    "chart",
    "image",
    "header",
    "footer",
    "number",
    "footnote",
    "aside_text",
    "reference",
    "footer_image",
    "header_image",
]


@dataclass(frozen=True)
class ConvertOptions:
    output: Path
    config: Path
    overwrite: bool
    timeout: int
    no_layout_vis: bool
    disable_image_extraction: bool
    log_level: str


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve-mlx":
        return serve_mlx(args)
    if args.command == "convert":
        return convert(args)
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperdown-py",
        description="Local-first GLM-OCR PDF to Markdown workflow.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve-mlx", help="Run the mlx-vlm OpenAI-compatible server.")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--host", default=None)
    serve.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args passed to mlx_vlm.server.")

    convert_parser = subcommands.add_parser("convert", help="Convert one PDF or a directory of PDFs.")
    convert_parser.add_argument("input", type=Path)
    convert_parser.add_argument("--output", type=Path, default=Path("md"))
    convert_parser.add_argument("--config", type=Path, default=default_config_path())
    convert_parser.add_argument("--overwrite", action="store_true")
    convert_parser.add_argument("--timeout", type=int, default=1800)
    convert_parser.add_argument("--no-layout-vis", action="store_true")
    convert_parser.add_argument("--disable-image-extraction", action="store_true")
    convert_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return parser


def default_config_path() -> Path:
    config = resources.files("paperdown_py").joinpath("configs/glmocr-local-ollama.yaml")
    return Path(str(config))


def serve_mlx(args: argparse.Namespace) -> int:
    if importlib.util.find_spec("mlx_vlm") is None:
        raise SystemExit(
            "mlx-vlm is not installed. On Apple Silicon, install it with: uv sync --extra mlx"
        )
    command = [
        sys.executable,
        "-m",
        "mlx_vlm.server",
        "--trust-remote-code",
        "--port",
        str(args.port),
    ]
    if args.host:
        command.extend(["--host", args.host])
    if args.extra and args.extra[0] == "--":
        args.extra = args.extra[1:]
    command.extend(args.extra)
    return subprocess.call(command)


def convert(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0")
    if not args.config.is_file():
        raise SystemExit(f"Config file not found: {args.config}")

    inputs = collect_inputs(args.input)
    options = ConvertOptions(
        output=args.output,
        config=args.config,
        overwrite=args.overwrite,
        timeout=args.timeout,
        no_layout_vis=args.no_layout_vis,
        disable_image_extraction=args.disable_image_extraction,
        log_level=args.log_level,
    )

    options.output.mkdir(parents=True, exist_ok=True)
    parser_kwargs: dict[str, Any] = {
        "config_path": str(options.config),
        "timeout": options.timeout,
        "log_level": options.log_level,
    }
    if options.disable_image_extraction:
        parser_kwargs["_dotted"] = {
            "pipeline.layout.label_task_mapping.skip": [],
            "pipeline.layout.label_task_mapping.abandon": DEFAULT_ABANDON_LABELS,
        }

    from glmocr import GlmOcr

    failures = 0
    with GlmOcr(**parser_kwargs) as parser:
        for input_path in inputs:
            try:
                convert_one(parser, input_path, options)
            except Exception as exc:
                failures += 1
                print(f"failed: {input_path}: {exc}", file=sys.stderr)

    print(
        f"done: processed={len(inputs) - failures} failed={failures} output={options.output}",
        file=sys.stderr,
    )
    return 1 if failures else 0


def collect_inputs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
            raise SystemExit(f"Unsupported input type: {input_path.suffix}")
        return [input_path.resolve()]
    if input_path.is_dir():
        paths = sorted(
            p.resolve()
            for p in input_path.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
        )
        if not paths:
            raise SystemExit(f"No PDFs found in {input_path}")
        return paths
    raise SystemExit(f"Input path does not exist: {input_path}")


def convert_one(parser: Any, input_path: Path, options: ConvertOptions) -> None:
    start = time.perf_counter()
    output_dir = options.output / sanitize_stem(input_path.stem)
    log_path = output_dir / "log.jsonl"
    if log_path.exists() and not options.overwrite:
        print(f"skip: {input_path}", file=sys.stderr)
        return
    if output_dir.exists() and options.overwrite:
        shutil.rmtree(output_dir)

    print(f"parse: {input_path}", file=sys.stderr)
    result = parser.parse(
        input_path,
        save_layout_visualization=not options.no_layout_vis,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    result.save(
        output_dir=options.output,
        save_layout_visualization=not options.no_layout_vis,
    )

    markdown = result.markdown_result or ""
    (output_dir / "index.md").write_text(markdown, encoding="utf-8")
    append_log(
        log_path,
        {
            "pdf_path": str(input_path),
            "output_dir": str(output_dir),
            "markdown_path": str(output_dir / "index.md"),
            "image_blocks": count_image_blocks(result.json_result),
            "saved_images": count_files(output_dir / "imgs"),
            "disable_image_extraction": options.disable_image_extraction,
            "timing": {"total_s": round(time.perf_counter() - start, 3)},
            "usage": getattr(result, "_usage", None),
        },
    )
    print(f"done: {input_path.name} -> {output_dir / 'index.md'}", file=sys.stderr)


def sanitize_stem(value: str) -> str:
    unsafe = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in unsafe or ord(ch) < 32 else ch for ch in value)
    cleaned = cleaned.rstrip(" .")
    return cleaned or "result"


def count_image_blocks(json_result: Any) -> int:
    if not isinstance(json_result, list):
        return 0
    total = 0
    for page in json_result:
        if isinstance(page, list):
            total += sum(
                1
                for region in page
                if isinstance(region, dict) and region.get("label") == "image"
            )
    return total


def count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def append_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(entry, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")

if __name__ == "__main__":
    raise SystemExit(main())
