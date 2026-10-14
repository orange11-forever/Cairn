from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_protocols import AnswerProtocol
from cairn_api.knowledge.answer_provider import AnswerProvider


class AnswerModelOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    model: str | None
    protocol: AnswerProtocol | None


@dataclass(frozen=True)
class ConfiguredAnswerModel:
    info: AnswerModelOption
    provider: AnswerProvider


def selected_answer_model(
    models: dict[str, ConfiguredAnswerModel], model_id: str | None
) -> ConfiguredAnswerModel:
    selected = next(iter(models.values()), None) if model_id is None else models.get(model_id)
    if selected is None:
        if model_id is None:
            raise ApiProblem(
                status_code=503, code="answer_unavailable", message="生成式回答暂时不可用"
            )
        raise ApiProblem(
            status_code=503,
            code="model_not_available",
            message="所选模型已不可用，请重新读取模型清单并在助手配置中选择可用模型",
        )
    return selected
