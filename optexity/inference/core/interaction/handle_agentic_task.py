import logging
import os
from pathlib import Path

from browser_use import Agent, BrowserSession, Tools

from optexity.action_memory.compiler import compile_cache
from optexity.inference.infra.browser import Browser
from optexity.inference.models import normalize_model
from optexity.inference.models.chat_litellm import build_agent_llm
from optexity.schema.actions.interaction_action import (
    AgenticTask,
    CloseOverlayPopupAction,
)
from optexity.schema.memory import Memory
from optexity.schema.task import Task

logger = logging.getLogger(__name__)

ACTION_CACHE_PATH_ENV = "BROWSER_USE_ACTION_CACHE_PATH"


def compile_agent_memory(
    *,
    agent_id: str,
    step_directory,
) -> None:
    cache_path = os.getenv(ACTION_CACHE_PATH_ENV)

    if not cache_path:
        return

    output_path = step_directory / "deterministic_automation.json"

    try:
        compile_cache(
            cache_path=Path(cache_path),
            output_path=output_path,
            requested_agent_id=agent_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to compile deterministic action memory " "for agent %s: %s",
            agent_id,
            exc,
        )
        return

    logger.info(
        "Generated deterministic action memory for agent %s at %s",
        agent_id,
        output_path,
    )


async def handle_agentic_task(
    agentic_task_action: AgenticTask | CloseOverlayPopupAction,
    task: Task,
    memory: Memory,
    browser: Browser,
):

    if agentic_task_action.backend == "browser_use":

        if isinstance(agentic_task_action, CloseOverlayPopupAction):
            tools = Tools(
                exclude_actions=[
                    "search",
                    "navigate",
                    "go_back",
                    "upload_file",
                    "scroll",
                    "find_text",
                    "send_keys",
                    "evaluate",
                    "switch",
                    "close",
                    "extract",
                    "dropdown_options",
                    "select_dropdown",
                    "write_file",
                    "read_file",
                    "replace_file",
                ]
            )
        else:
            tools = Tools()
        llm = build_agent_llm(normalize_model(task.llm_provider, task.llm_model_name))
        browser_session = BrowserSession(
            cdp_url=browser.cdp_url, keep_alive=agentic_task_action.keep_alive
        )

        step_directory = (
            task.logs_directory / f"step_{str(memory.automation_state.step_index)}"
        )
        step_directory.mkdir(parents=True, exist_ok=True)

        agent = Agent(
            task=agentic_task_action.task,
            llm=llm,
            browser_session=browser_session,
            use_vision=agentic_task_action.use_vision,
            tools=tools,
            calculate_cost=True,
            save_conversation_path=step_directory,
        )
        logger.debug(f"Starting browser session for agentic task {browser.cdp_url} ")
        await agent.browser_session.start()
        logger.debug(f"Finally running agentic task on browser_use {browser.cdp_url} ")
        history = await agent.run(max_steps=agentic_task_action.max_steps)

        compile_agent_memory(
            agent_id=str(agent.id),
            step_directory=step_directory,
        )

        logger.debug(f"Agentic task completed on browser_use {browser.cdp_url} ")

        agent.stop()
        if agent.browser_session:
            await agent.browser_session.stop()
            await agent.browser_session.reset()

        return history

    elif agentic_task_action.backend == "browserbase":
        raise NotImplementedError("Browserbase is not supported yet")

    return None
