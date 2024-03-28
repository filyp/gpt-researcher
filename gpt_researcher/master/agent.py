import asyncio
import os
import time
from pathlib import Path
from gpt_researcher.config import Config
from gpt_researcher.master.functions import *
from gpt_researcher.context.compression import ContextCompressor
from gpt_researcher.memory import Memory

context_cache_dir = Path(__file__).resolve().parents[2] / "context_cache"


# def load_cache(cache_item_path):
#     """
#     cache_item_path is a directory, where several txt files with contexts are stored
#     loads each of them and returns a list of contexts
#     """
#     contexts = []
#     # they have a format of 0.txt, 1.txt, 2.txt, ...
#     files = cache_item_path.glob("*.txt")
#     # sort by number
#     files = sorted(files, key=lambda x: int(x.stem))
#     for file_ in files:
#         context = file_.read_text()
#         contexts.append(context)
#     return contexts


# def save_cache(cache_item_path, context):
#     """
#     cache_item_path is a directory, where several txt files with contexts will be stored
#     """
#     assert not cache_item_path.exists(), f"Cache item path {cache_item_path} already exists"
#     cache_item_path.mkdir()
#     for i, context_item in enumerate(context):
#         path = cache_item_path / f"{i}.txt"
#         path.write_text(context_item)


class GPTResearcher:
    """
    GPT Researcher
    """
    def __init__(self, query, report_type="research_report", source_urls=None, config_path=None, websocket=None):
        """
        Initialize the GPT Researcher class.
        Args:
            query:
            report_type:
            config_path:
            websocket:
        """
        self.query = query
        self.agent = None
        self.role = None
        self.report_type = report_type
        self.websocket = websocket
        self.cfg = Config(config_path)
        self.retriever = get_retriever(self.cfg.retriever)
        self.context = []
        self.source_urls = source_urls
        self.memory = Memory(self.cfg.embedding_provider)
        self.visited_urls = set()

    async def run(self):
        """
        Runs the GPT Researcher
        Returns:
            Report
        """
        print(f"🔎 Running research for '{self.query}'...")
        
        # prepare cache
        cache_path = context_cache_dir / self.query
        os.environ["CACHE_PATH"] = str(cache_path)
        os.environ["USE_CACHED"] = str(cache_path.exists())
        if not cache_path.exists():
            cache_path.mkdir()
            (cache_path / "sub_query_search").mkdir()
            (cache_path / "scraped").mkdir()
            await stream_output("logs", f"📚 Creating cache for the query: {self.query}...", self.websocket)
        else:
            await stream_output("logs", f"📚 Using cached data for research task: {self.query}...", self.websocket)
            
        # Generate Agent
        if os.environ["USE_CACHED"] != "True":
            self.agent, self.role = await choose_agent(self.query, self.cfg)
            # save to cache
            (Path(os.environ["CACHE_PATH"]) / "agent.txt").write_text(self.agent)
            (Path(os.environ["CACHE_PATH"]) / "role.txt").write_text(self.role)
        else:
            # load from cache
            self.agent = (Path(os.environ["CACHE_PATH"]) / "agent.txt").read_text()
            self.role = (Path(os.environ["CACHE_PATH"]) / "role.txt").read_text()
            
        await stream_output("logs", self.agent, self.websocket)

        # If specified, the researcher will use the given urls as the context for the research.
        if self.source_urls:
            self.context = await self.get_context_by_urls(self.source_urls)
        else:
            self.context = await self.get_context_by_search(self.query)

        # Write Research Report
        if self.report_type == "custom_report":
            self.role = self.cfg.agent_role if self.cfg.agent_role else self.role
        await stream_output("logs", f"✍️ Writing {self.report_type} for research task: {self.query}...", self.websocket)
        report = await generate_report(query=self.query, context=self.context,
                                       agent_role_prompt=self.role, report_type=self.report_type,
                                       websocket=self.websocket, cfg=self.cfg)
        time.sleep(2)
        return report

    async def get_context_by_urls(self, urls):
        """
            Scrapes and compresses the context from the given urls
        """
        new_search_urls = await self.get_new_urls(urls)
        await stream_output("logs",
                            f"🧠 I will conduct my research based on the following urls: {new_search_urls}...",
                            self.websocket)
        scraped_sites = scrape_urls(new_search_urls, self.cfg)
        return await self.get_similar_content_by_query(self.query, scraped_sites)

    async def get_context_by_search(self, query):
        """
           Generates the context for the research task by searching the query and scraping the results
        Returns:
            context: List of context
        """
        context = []

        # Generate Sub-Queries including original query
        path = Path(os.environ["CACHE_PATH"]) / "sub_queries.json"
        if os.environ["USE_CACHED"] != "True":
            # generate sub queries
            sub_queries = await get_sub_queries(query, self.role, self.cfg) + [query]
            # save to cache
            path.write_text(json.dumps(sub_queries, indent=4))
        else:
            # load from cache
            sub_queries = json.loads(path.read_text())

        await stream_output("logs",
                            f"🧠 I will conduct my research based on the following queries: {sub_queries}...",
                            self.websocket)

        # Using asyncio.gather to process the sub_queries asynchronously
        context = await asyncio.gather(*[self.process_sub_query(sub_query) for sub_query in sub_queries])
        return context
    
    async def process_sub_query(self, sub_query: str):
        """Takes in a sub query and scrapes urls based on it and gathers context.

        Args:
            sub_query (str): The sub-query generated from the original query

        Returns:
            str: The context gathered from search
        """
        await stream_output("logs", f"\n🔎 Running research for '{sub_query}'...", self.websocket)
        scraped_sites = await self.scrape_sites_by_query(sub_query)
        content = await self.get_similar_content_by_query(sub_query, scraped_sites)
        await stream_output("logs", f"📃 {content}", self.websocket)
        return content

    async def get_new_urls(self, url_set_input):
        """ Gets the new urls from the given url set.
        Args: url_set_input (set[str]): The url set to get the new urls from
        Returns: list[str]: The new urls from the given url set
        """

        new_urls = []
        for url in url_set_input:
            if url not in self.visited_urls:
                await stream_output("logs", f"✅ Adding source url to research: {url}\n", self.websocket)

                self.visited_urls.add(url)
                new_urls.append(url)

        return new_urls

    async def scrape_sites_by_query(self, sub_query):
        """
        Runs a sub-query
        Args:
            sub_query:

        Returns:
            Summary
        """
        # Get Urls
        path = Path(os.environ["CACHE_PATH"]) / "sub_query_search" / f"{sub_query}.json"
        if os.environ["USE_CACHED"] != "True":
            # get search results
            retriever = self.retriever(sub_query)
            search_results = retriever.search(max_results=self.cfg.max_search_results_per_query)
            # save to cache
            path.write_text(json.dumps(search_results, indent=4))
        else:
            # load from cache
            search_results = json.loads(path.read_text())

        new_search_urls = await self.get_new_urls([url.get("href") for url in search_results])

        # Scrape Urls
        # await stream_output("logs", f"📝Scraping urls {new_search_urls}...\n", self.websocket)
        await stream_output("logs", f"🤔Researching for relevant information...\n", self.websocket)
        scraped_content_results = scrape_urls(new_search_urls, self.cfg)
        return scraped_content_results

    async def get_similar_content_by_query(self, query, pages):
        await stream_output("logs", f"📃 Getting relevant content based on query: {query}...", self.websocket)
        # Summarize Raw Data
        context_compressor = ContextCompressor(documents=pages, embeddings=self.memory.get_embeddings())
        # Run Tasks
        return context_compressor.get_context(query, max_results=8)

