"""Offline tests for PAIM-13 live eval harness infrastructure.

All offline — no network, no model, no Ollama.
"""

from __future__ import annotations

import asyncio

from pydantic_ai.messages import TextPart

from tests.support.paim13_live_harness import CountingPydanticModel
from tests.support.test_doubles import FakeModel, RaisingFakeModel

# ==============================================================================
# CountingPydanticModel — literal request counting (C29-M01 through C29-M05)
# ==============================================================================


class TestCountingPydanticModelLiteral:
    """Literal async tests for CountingPydanticModel request counting.

    C29-M01: wrapper is instance of Model (in test_pydantic_ai_eval.py)
    C29-M02: one request → count == 1, delegate called once
    C29-M03: two requests → count == 2
    C29-M04: delegate raises → count == 1, exception propagates
    C29-M05: request_stream delegates and does not corrupt non-stream count
    """

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _run(coro):
        """Run an async coroutine synchronously via asyncio."""
        return asyncio.run(coro)

    # ── C29-M02 ──────────────────────────────────────────────────────────

    def test_one_request_increments_count(self) -> None:
        """C29-M02: one request → count == 1, delegate called once."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            pre = fake.invocation_count
            response = await counter.request(
                messages=[],
                model_settings=None,
                model_request_parameters=None,  # type: ignore[arg-type]
            )

            assert counter.state.request_count == 1
            assert fake.invocation_count == pre + 1
            assert isinstance(response.parts[0], TextPart)
            assert response.parts[0].content == "ok"

        self._run(_test())

    # ── C29-M03 ──────────────────────────────────────────────────────────

    def test_two_requests_increments_count(self) -> None:
        """C29-M03: two requests → count == 2."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            await counter.request(messages=[], model_settings=None, model_request_parameters=None)  # type: ignore[arg-type]
            await counter.request(messages=[], model_settings=None, model_request_parameters=None)  # type: ignore[arg-type]

            assert counter.state.request_count == 2
            assert fake.invocation_count == 2

        self._run(_test())

    # ── C29-M04 ──────────────────────────────────────────────────────────

    def test_failed_request_is_counted(self) -> None:
        """C29-M04: delegate raises → attempted request count == 1,
        exact exception propagates."""

        async def _test() -> None:
            raising = RaisingFakeModel()
            counter = CountingPydanticModel(raising)

            import pytest

            with pytest.raises(RuntimeError, match="Simulated model failure"):
                await counter.request(
                    messages=[],
                    model_settings=None,
                    model_request_parameters=None,  # type: ignore[arg-type]
                )

            # The failed semantic request is still counted as an attempt
            assert counter.state.request_count == 1

        self._run(_test())

    # ── C29-M05 ──────────────────────────────────────────────────────────

    def test_request_stream_delegates(self) -> None:
        """C29-M05: request_stream delegates correctly and does not
        corrupt non-stream semantic request count.

        Uses ``WrapperModel``'s inherited ``request_stream``
        (``@asynccontextmanager`` that yields a ``StreamedResponse``).
        """

        async def _test() -> None:
            from pydantic_ai.models import ModelRequestParameters

            fake = FakeModel()
            counter = CountingPydanticModel(fake)
            params = ModelRequestParameters(function_tools=[])

            # WrapperModel.request_stream is an @asynccontextmanager
            # that delegates to the wrapped model's request_stream.
            async with counter.request_stream(
                messages=[],
                model_settings=None,
                model_request_parameters=params,
            ) as stream:
                # StreamedResponse is an async iterable; verify it delegates
                # (CompletedStreamedResponse with no events is empty)
                _ = stream

            # request_stream must not increment the non-stream request count
            assert counter.state.request_count == 0

        self._run(_test())

    def test_stream_does_not_affect_non_stream_count(self) -> None:
        """request_stream does not corrupt non-stream semantic request count
        when both paths are used."""

        async def _test() -> None:
            from pydantic_ai.models import ModelRequestParameters

            fake = FakeModel()
            counter = CountingPydanticModel(fake)
            params = ModelRequestParameters(function_tools=[])

            # One stream call (async with, not async for)
            async with counter.request_stream(
                messages=[],
                model_settings=None,
                model_request_parameters=params,
            ) as stream:
                async for _chunk in stream:
                    pass

            # One non-stream call
            await counter.request(messages=[], model_settings=None, model_request_parameters=params)

            # Only the non-stream call should be counted
            assert counter.state.request_count == 1

        self._run(_test())


# ==============================================================================
# CountingPydanticModel — exact response identity/value preservation
# ==============================================================================


class TestCountingPydanticModelResponsePreservation:
    """Verify that CountingPydanticModel preserves exact response."""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_response_identity_preserved(self) -> None:
        """Exact response identity/value preserved through wrapper."""

        async def _test() -> None:
            fake = FakeModel()
            counter = CountingPydanticModel(fake)

            response = await counter.request(
                messages=[],
                model_settings=None,
                model_request_parameters=None,  # type: ignore[arg-type]
            )

            assert isinstance(response.parts[0], TextPart)
            assert response.parts[0].content == "ok"
            assert len(response.parts) == 1

        self._run(_test())


# ==============================================================================
# Architecture assertions — CountingPydanticModel exact type evidence
# ==============================================================================


class TestCountingPydanticModelArchitecture:
    """Offline architecture assertions for CountingPydanticModel.

    These verify that the counting model satisfies the Pydantic AI Model
    contract required by production constructors.
    """

    def test_isinstance_model(self) -> None:
        """CountingPydanticModel is an isinstance of Model."""
        from pydantic_ai.models import Model as PydanticModel

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert isinstance(counter, PydanticModel)

    def test_isinstance_wrapper_model(self) -> None:
        """CountingPydanticModel is an isinstance of WrapperModel."""
        from pydantic_ai.models.wrapper import WrapperModel

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert isinstance(counter, WrapperModel)

    def test_settings_preserved_default(self) -> None:
        """CountingPydanticModel.settings == delegate.settings (default None)."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.settings == fake.settings

    def test_settings_preserved_non_default(self) -> None:
        """CountingPydanticModel.settings == delegate.settings (non-default)."""
        from pydantic_ai.settings import ModelSettings

        fake = FakeModel(settings=ModelSettings(temperature=0.5, max_tokens=100))
        counter = CountingPydanticModel(fake)
        assert counter.settings == fake.settings
        assert counter.settings == {"temperature": 0.5, "max_tokens": 100}

    def test_profile_preserved(self) -> None:
        """CountingPydanticModel.profile == delegate.profile."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.profile == fake.profile

    def test_model_name_preserved(self) -> None:
        """CountingPydanticModel.model_name == delegate.model_name."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.model_name == fake.model_name

    def test_system_preserved(self) -> None:
        """CountingPydanticModel.system == delegate.system."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.system == fake.system

    def test_base_url_preserved_with_non_none(self) -> None:
        """CountingPydanticModel forwards a non-None base_url from the delegate."""

        fake = FakeModel(base_url="http://test-ollama:11434/v1")
        counter = CountingPydanticModel(fake)
        assert counter.base_url == "http://test-ollama:11434/v1"
        assert counter.base_url == fake.base_url

    def test_base_url_preserved_none(self) -> None:
        """CountingPydanticModel forwards None base_url from the delegate."""

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.base_url is None
        assert counter.base_url == fake.base_url

    def test_model_id_preserved(self) -> None:
        """CountingPydanticModel.model_id == delegate.model_id."""
        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        assert counter.model_id == fake.model_id

    def test_customize_request_parameters_delegation(self) -> None:
        """CountingPydanticModel delegates customize_request_parameters."""
        from pydantic_ai.models import ModelRequestParameters

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        params = ModelRequestParameters(function_tools=[])
        result = counter.customize_request_parameters(params)
        assert result == fake.customize_request_parameters(params)

    def test_request_preparation_transparency(self) -> None:
        """CountingPydanticModel does not alter request/tool shape.

        Verifies that ``prepare_request()`` on the wrapper produces the
        same result as on the delegate when given identical inputs.
        """
        from pydantic_ai.models import ModelRequestParameters

        fake = FakeModel()
        counter = CountingPydanticModel(fake)

        params = ModelRequestParameters(function_tools=[])
        fake_result = fake.prepare_request(model_settings=None, model_request_parameters=params)
        counter_result = counter.prepare_request(
            model_settings=None, model_request_parameters=params
        )

        # The merged settings and customized parameters should be equivalent
        assert fake_result[0] == counter_result[0], "merged model_settings must match"
        # ModelRequestParameters dataclass equality works field-by-field
        assert fake_result[1] == counter_result[1], "customized ModelRequestParameters must match"

    def test_pydantic_ai_fast_agent_construction(self) -> None:
        """PydanticAIFastAgent accepts CountingPydanticModel."""
        from dnd_assistant.application.pydantic_ai_fast_agent import (
            PydanticAIFastAgent,
        )
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer,
        )
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from dnd_assistant.tools.registry import ToolRegistry
        from tests.support.paim13_live_harness import (
            make_deterministic_context_builder,
        )

        registry = ToolRegistry()
        tool_bridge = PydanticAIToolBridge(registry=registry)
        context_builder = make_deterministic_context_builder()
        catalog = build_tool_registry_schema(registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        agent = PydanticAIFastAgent(run_preparer=preparer, model=counter)
        assert agent is not None

    def test_pydantic_ai_agent_runtime_construction(self) -> None:
        """PydanticAIAgentRuntime accepts CountingPydanticModel."""
        from dnd_assistant.application.pydantic_ai_agent_runtime import (
            PydanticAIAgentRuntime,
        )
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer,
        )
        from dnd_assistant.application.pydantic_ai_tool_bridge import (
            PydanticAIToolBridge,
        )
        from dnd_assistant.tools.catalog import build_tool_registry_schema
        from dnd_assistant.tools.registry import ToolRegistry
        from tests.support.paim13_live_harness import (
            make_deterministic_context_builder,
        )

        registry = ToolRegistry()
        tool_bridge = PydanticAIToolBridge(registry=registry)
        context_builder = make_deterministic_context_builder()
        catalog = build_tool_registry_schema(registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=catalog,
            tool_bridge=tool_bridge,
        )

        fake = FakeModel()
        counter = CountingPydanticModel(fake)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counter)
        assert runtime is not None
