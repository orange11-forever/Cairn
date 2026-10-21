from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CitationId = Annotated[str, Field(pattern=r"^S[1-6]$")]
TaskId = Annotated[str, Field(pattern=r"^T([1-9]|1[0-9]|20)$")]
StageId = Annotated[str, Field(pattern=r"^P[1-5]$")]
MilestoneId = Annotated[str, Field(pattern=r"^M[1-8]$")]


class CitedPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    citation_ids: list[CitationId] = Field(alias="citationIds", min_length=1, max_length=6)


class ProposedStage(CitedPlanItem):
    id: StageId
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=600)


class ProposedMilestone(CitedPlanItem):
    id: MilestoneId
    stage_id: StageId = Field(alias="stageId")
    name: str = Field(min_length=1, max_length=160)
    acceptance_criteria: str = Field(alias="acceptanceCriteria", min_length=1, max_length=600)


class ProposedTask(CitedPlanItem):
    id: TaskId
    stage_id: StageId = Field(alias="stageId")
    milestone_id: MilestoneId | None = Field(alias="milestoneId")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=600)
    acceptance_criteria: str = Field(alias="acceptanceCriteria", min_length=1, max_length=600)
    priority: Literal["low", "medium", "high", "critical"]
    depends_on: list[TaskId] = Field(alias="dependsOn", max_length=19)


class ProjectPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    status: Literal["planned", "insufficient_evidence"]
    summary: str = Field(min_length=1, max_length=1000)
    assumptions: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(max_length=6)
    citation_ids: list[CitationId] = Field(alias="citationIds", max_length=6)
    stages: list[ProposedStage] = Field(max_length=5)
    milestones: list[ProposedMilestone] = Field(max_length=8)
    tasks: list[ProposedTask] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_graph(self) -> "ProjectPlanDraft":
        if self.status == "insufficient_evidence":
            if self.stages or self.milestones or self.tasks:
                raise ValueError("insufficient evidence cannot contain a proposed plan")
            return self
        if not self.stages or not self.milestones or not self.tasks or not self.citation_ids:
            raise ValueError("a plan requires stages, milestones, tasks and evidence")
        stages = {stage.id for stage in self.stages}
        milestones = {milestone.id: milestone for milestone in self.milestones}
        tasks = {task.id for task in self.tasks}
        if (
            len(stages) != len(self.stages)
            or len(milestones) != len(self.milestones)
            or len(tasks) != len(self.tasks)
        ):
            raise ValueError("plan item IDs must be unique")
        for milestone in self.milestones:
            if milestone.stage_id not in stages:
                raise ValueError("milestone references an unknown stage")
        for task in self.tasks:
            if task.stage_id not in stages:
                raise ValueError("task references an unknown stage")
            if task.milestone_id is not None and (
                task.milestone_id not in milestones
                or milestones[task.milestone_id].stage_id != task.stage_id
            ):
                raise ValueError("task milestone must belong to its stage")
            if (
                task.id in task.depends_on
                or not set(task.depends_on) <= tasks
                or len(set(task.depends_on)) != len(task.depends_on)
            ):
                raise ValueError("task dependencies must be unique known predecessors")
        pending = {task.id: set(task.depends_on) for task in self.tasks}
        resolved: set[str] = set()
        while pending:
            ready = {
                task_id for task_id, predecessors in pending.items() if predecessors <= resolved
            }
            if not ready:
                raise ValueError("task dependencies must not contain a cycle")
            resolved.update(ready)
            pending = {
                task_id: predecessors
                for task_id, predecessors in pending.items()
                if task_id not in ready
            }
        return self
