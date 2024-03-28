
# %% add repo root to python path
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

# %% load the API keys
import os

openai_token_path = Path("~/.config/openai.token").expanduser()
tavily_token_path = Path("~/.config/tavily.token").expanduser()
os.environ["OPENAI_API_KEY"] = openai_token_path.read_text().strip()
os.environ["TAVILY_API_KEY"] = tavily_token_path.read_text().strip()
# %%
from gpt_researcher import GPTResearcher
import asyncio


async def main():
    """
    This is a sample script that shows how to run a research report.
    """
    # Query
    # query = "What happened in the latest burning man floods?"
    # query = "Who should I vote for in the upcoming election?"
    query = "Which brand of creatine should I buy?"

    # Report Type
    report_type = "research_report"

    # Run Research
    researcher = GPTResearcher(query=query, report_type=report_type, config_path=None)
    report = await researcher.run()
    return report


if __name__ == "__main__":
    asyncio.run(main())

# %%
