from cairn_api.knowledge.assistant_schemas import KnowledgeSkillItem

BUILTIN_GUIDANCE = {
    "knowledge-summary": "根据本轮证据概括资料的目标、关键事实与结论。每项事实须有引用，不补造缺失信息。",
    "next-step-analysis": "区分当前证据支持的事实、缺失信息和建议；把行动明确标为建议并给出引用，不声称已修改项目对象。",
}
BUILTIN_SKILLS = [
    KnowledgeSkillItem(
        id="knowledge-summary",
        name="资料摘要",
        description="概括当前资料的目标、关键事实与结论。",
        defaultQuestion="请概括当前项目资料的目标、关键事实与结论，并给出引用。",
        capabilities=["knowledge.read"],
        sourceType="builtin",
        runnable=True,
        warnings=[],
    ),
    KnowledgeSkillItem(
        id="next-step-analysis",
        name="下一步建议",
        description="从当前证据提出明确标为建议的下一步行动。",
        defaultQuestion="根据当前项目资料，下一步可以做什么？请区分事实、缺失信息与建议。",
        capabilities=["knowledge.read"],
        sourceType="builtin",
        runnable=True,
        warnings=[],
    ),
]
