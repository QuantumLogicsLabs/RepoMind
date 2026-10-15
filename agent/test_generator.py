"""agent/test_generator.py

Autonomous Test Generator:
Generates structured TestSuiteSpec from inferred missing behavioral requirements
and code context.
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from agent.coverage_analyzer import MissingTestRequirement
from agent.test_schemas import TestAssertionSpec, TestCaseSpec, TestSuiteSpec

logger = logging.getLogger(__name__)


class AutonomousTestGenerator:
    """Generates structured TestSuiteSpec objects for missing behavioral requirements."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self.llm = llm
        if llm:
            self._build_prompt()

    def _build_prompt(self) -> None:
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are an expert test engineer for the RepoMind AI repository.\n"
                        "Your job is to generate a structured TestSuiteSpec containing high quality pytest test cases "
                        "for the given behavioral requirements.\n"
                        "\n"
                        "STRICT RULES:\n"
                        "1. Every test case must target a specific symbol and verify observable behavior.\n"
                        "2. Use pytest style, async tests with is_async=True when testing async functions.\n"
                        "3. Return ONLY structured data matching the TestSuiteSpec schema."
                    ),
                ),
                (
                    "human",
                    (
                        "Target file: {target_file}\n"
                        "Test file: {test_file}\n"
                        "Source code context:\n{source_code}\n\n"
                        "Missing requirements:\n{requirements}\n\n"
                        "Generate a complete TestSuiteSpec."
                    ),
                ),
            ]
        )

    def generate_spec_fallback(
        self,
        target_file: str,
        test_file: str,
        requirements: list[MissingTestRequirement],
    ) -> TestSuiteSpec:
        """Deterministic fallback spec generator when LLM is offline or in mock mode."""
        test_cases: list[TestCaseSpec] = []
        imports = [
            "import pytest",
            "from unittest.mock import MagicMock, patch",
        ]

        for req in requirements:
            symbol = req.target_symbol
            clean_name = symbol.replace(".", "_")
            if req.scenario_type == "happy_path":
                test_cases.append(
                    TestCaseSpec(
                        test_name=f"test_{clean_name}_success",
                        target_symbol=symbol,
                        description=f"Verify success path for {symbol}.",
                        is_async=req.is_async,
                        assertions=[
                            TestAssertionSpec(
                                assertion_type="is_not_none",
                                actual_expr="result",
                            )
                        ],
                    )
                )
            elif req.scenario_type == "error_handling":
                test_cases.append(
                    TestCaseSpec(
                        test_name=f"test_{clean_name}_error_handling",
                        target_symbol=symbol,
                        description=f"Verify error handling for {symbol}.",
                        is_async=req.is_async,
                        assertions=[
                            TestAssertionSpec(
                                assertion_type="raises",
                                actual_expr="ValueError",
                            )
                        ],
                    )
                )
            else:
                test_cases.append(
                    TestCaseSpec(
                        test_name=f"test_{clean_name}_{req.scenario_type}",
                        target_symbol=symbol,
                        description=req.description,
                        is_async=req.is_async,
                        assertions=[
                            TestAssertionSpec(
                                assertion_type="true",
                                actual_expr="True",
                            )
                        ],
                    )
                )

        return TestSuiteSpec(
            target_file=target_file,
            test_file=test_file,
            imports=imports,
            test_cases=test_cases,
        )

    def generate_spec(
        self,
        target_file: str,
        test_file: str,
        source_code: str,
        requirements: list[MissingTestRequirement],
    ) -> TestSuiteSpec:
        """
        Generate structured TestSuiteSpec using LLM structured output if available,
        or deterministic fallback generator.
        """
        if not requirements:
            return TestSuiteSpec(target_file=target_file, test_file=test_file)

        if self.llm is not None:
            try:
                chain = self.prompt | self.llm.with_structured_output(TestSuiteSpec)
                req_text = "\n".join(
                    [f"- {r.scenario_name}: {r.description}" for r in requirements]
                )
                res = chain.invoke(
                    {
                        "target_file": target_file,
                        "test_file": test_file,
                        "source_code": source_code[:2000],
                        "requirements": req_text,
                    }
                )
                if isinstance(res, TestSuiteSpec):
                    return res
            except Exception as e:
                logger.warning(
                    f"LLM test spec generation failed ({e}); using deterministic spec generator."
                )

        return self.generate_spec_fallback(target_file, test_file, requirements)
