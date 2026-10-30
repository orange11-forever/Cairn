import base64
from io import BytesIO

import pytest
from cairn_api.knowledge.assistant_schemas import AssistantSettingsRequest
from PIL import Image
from pydantic import ValidationError


def avatar_png(color: str = "blue", size: tuple[int, int] = (128, 128)) -> str:
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def settings(avatar: str | None) -> AssistantSettingsRequest:
    return AssistantSettingsRequest.model_validate(
        {
            "expectedRevision": 0,
            "name": "自定义助手",
            "instructions": "",
            "enabledSkillIds": [],
            "avatarDataUrl": avatar,
        }
    )


def test_assistant_avatar_accepts_small_png_or_explicit_removal() -> None:
    avatar = avatar_png()
    assert settings(avatar).avatar_data_url == avatar
    assert settings(None).avatar_data_url is None


@pytest.mark.parametrize(
    "avatar",
    [
        "https://example.com/tracker.png",
        "data:image/svg+xml;base64," + base64.b64encode(b'<svg onload="alert(1)"></svg>').decode(),
        "data:image/png;base64," + base64.b64encode(b"not a PNG").decode(),
        "data:image/png;base64,invalid!!",
        "data:image/png;base64," + "A" * 90001,
        avatar_png(size=(129, 128)),
    ],
)
def test_assistant_avatar_rejects_remote_active_invalid_or_oversize_images(avatar: str) -> None:
    with pytest.raises(ValidationError):
        settings(avatar)
