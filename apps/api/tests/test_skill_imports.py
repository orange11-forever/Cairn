import base64
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.assistant_schemas import SkillImportSource
from cairn_api.knowledge.skill_imports import preview_skill
from pydantic import TypeAdapter, ValidationError

CONTENT = "---\nname: 合成技能\ndescription: 依据本轮知识概括结论\n---\n只使用本轮证据并引用。"
adapter: TypeAdapter[SkillImportSource] = TypeAdapter(SkillImportSource)


def test_markdown_preview_is_bounded_and_deterministic() -> None:
    source = adapter.validate_python(
        {"type": "markdown", "fileName": "SKILL.md", "content": CONTENT}
    )
    preview = preview_skill(source)
    assert preview.name == "合成技能" and preview.runnable
    assert preview.digest == preview_skill(source).digest


@pytest.mark.parametrize(
    "header",
    [
        "name: x\nname: y\ndescription: ok",
        "name: &a x\ndescription: *a",
        "name: !unsafe x\ndescription: ok",
    ],
)
def test_yaml_duplicate_anchor_and_tag_are_safe_422(header: str) -> None:
    source = adapter.validate_python(
        {"type": "markdown", "fileName": "SKILL.md", "content": f"---\n{header}\n---\nbody"}
    )
    with pytest.raises(ApiProblem) as error:
        preview_skill(source)
    assert error.value.status_code == 422


def test_zip_keeps_text_references_but_cannot_enable_scripts() -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr("skill/SKILL.md", CONTENT)
        package.writestr("skill/references/example.txt", "合成参考")
        package.writestr("skill/scripts/run.py", "print('never run')")
    source = adapter.validate_python(
        {
            "type": "zip",
            "fileName": "skill.zip",
            "contentBase64": base64.b64encode(archive.getvalue()).decode(),
        }
    )
    preview = preview_skill(source)
    assert not preview.runnable and preview.warnings
    assert preview.resources[0].content == "合成参考"


@pytest.mark.parametrize("path", ["../SKILL.md", "/SKILL.md", "x\\SKILL.md"])
def test_zip_unsafe_paths_are_rejected(path: str) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr(path, CONTENT)
    with pytest.raises(ApiProblem):
        preview_skill(
            adapter.validate_python(
                {
                    "type": "zip",
                    "fileName": "skill.zip",
                    "contentBase64": base64.b64encode(archive.getvalue()).decode(),
                }
            )
        )


def test_github_uses_fixed_public_contents_api_without_credentials_or_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            str(request.url)
            == "https://api.github.com/repos/example/public/contents/skills/test/SKILL.md"
        )
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "type": "file",
                "encoding": "base64",
                "sha": "a" * 40,
                "content": base64.b64encode(CONTENT.encode()).decode(),
                "download_url": "http://127.0.0.1/private",
            },
        )

    source = adapter.validate_python(
        {
            "type": "github",
            "url": "https://github.com/example/public",
            "path": "skills/test/SKILL.md",
        }
    )
    assert preview_skill(
        source, client=httpx.Client(transport=httpx.MockTransport(handler))
    ).runnable


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://github.com:443/a/b",
        "https://secret@github.com/a/b",
        "https://github.com/a/b?token=secret",
        "https://localhost/a/b",
    ],
)
def test_github_rejects_arbitrary_hosts_and_credentials_without_fetch(url: str) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("must not fetch unsafe URL")

    with pytest.raises(ApiProblem) as error:
        preview_skill(
            adapter.validate_python({"type": "github", "url": url}),
            client=httpx.Client(transport=httpx.MockTransport(forbidden)),
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize("invalid", [CONTENT + "\x00", CONTENT + "\ud800"])
def test_malformed_text_is_422_before_database_or_provider(invalid: str) -> None:
    with pytest.raises((ApiProblem, ValidationError)) as error:
        preview_skill(
            adapter.validate_python(
                {"type": "markdown", "fileName": "SKILL.md", "content": invalid}
            )
        )
    if isinstance(error.value, ApiProblem):
        assert error.value.status_code == 422
    else:
        assert error.value.errors()[0]["type"] == "string_unicode"


def test_unsupported_zip_codec_is_safe_422_before_decompression() -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr("SKILL.md", CONTENT)
    raw = bytearray(archive.getvalue())
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        position = raw.index(signature) + offset
        raw[position : position + 2] = (99).to_bytes(2, "little")
    source = adapter.validate_python(
        {"type": "zip", "fileName": "skill.zip", "contentBase64": base64.b64encode(raw).decode()}
    )
    with pytest.raises(ApiProblem) as error:
        preview_skill(source)
    assert error.value.status_code == 422
    assert error.value.code == "invalid_skill"
