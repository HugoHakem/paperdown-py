from importlib import resources
from pathlib import Path

from paperdown_py.cli import collect_inputs, count_image_blocks, default_config_path, sanitize_stem


def test_collect_inputs_finds_pdfs(tmp_path: Path) -> None:
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "notes.txt").write_text("ignore")

    assert [p.name for p in collect_inputs(tmp_path)] == ["a.pdf", "b.pdf"]


def test_sanitize_stem_removes_path_unsafe_characters() -> None:
    assert sanitize_stem('a/b:c*') == "a_b_c_"


def test_count_image_blocks() -> None:
    assert (
        count_image_blocks(
            [
                [{"label": "image"}, {"label": "text"}],
                [{"label": "image"}],
            ]
        )
        == 2
    )


def test_default_config_is_ollama() -> None:
    assert default_config_path().name == "glmocr-local-ollama.yaml"


def test_backend_configs_are_packaged() -> None:
    config_dir = resources.files("paperdown_py").joinpath("configs")

    assert config_dir.joinpath("glmocr-local-ollama.yaml").is_file()
    assert config_dir.joinpath("glmocr-local-vllm.yaml").is_file()
    assert config_dir.joinpath("glmocr-local-mlx.yaml").is_file()
