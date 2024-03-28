from concurrent.futures.thread import ThreadPoolExecutor
from functools import partial
import os
from pathlib import Path

import requests

from gpt_researcher.scraper import (
    ArxivScraper,
    BeautifulSoupScraper,
    NewspaperScraper,
    PyMuPDFScraper,
    WebBaseLoaderScraper,
)


class Scraper:
    """
    Scraper class to extract the content from the links
    """

    def __init__(self, urls, user_agent, scraper):
        """
        Initialize the Scraper class.
        Args:
            urls:
        """
        self.urls = urls
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.scraper = scraper

    def run(self):
        """
        Extracts the content from the links
        """
        partial_extract = partial(self.extract_data_from_link, session=self.session)
        with ThreadPoolExecutor(max_workers=20) as executor:
            contents = executor.map(partial_extract, self.urls)
        res = [content for content in contents if content["raw_content"] is not None]
        return res

    def extract_data_from_link(self, link, session):
        """
        Extracts the data from the link
        """
        content = ""


        filename = link.replace("/", "_").replace(":", "_").replace(".", "_")
        path = Path(os.environ["CACHE_PATH"]) / "scraped" / f"{filename}.txt"
        if os.environ["USE_CACHED"] != "True":
            # scrape
            try:
                Scraper = self.get_scraper(link)
                scraper = Scraper(link, session)
                content = scraper.scrape()
            except Exception as e:
                content = ""
            if len(content) < 100:
                content = ""

            # save to cache
            path.write_text(content)
        else:
            # load from cache
            assert path.exists(), f"File {path} does not exist."
            content = path.read_text()

        return {"url": link, "raw_content": content if content else None}

    def get_scraper(self, link):
        """
        The function `get_scraper` determines the appropriate scraper class based on the provided link
        or a default scraper if none matches.

        Args:
          link: The `get_scraper` method takes a `link` parameter which is a URL link to a webpage or a
        PDF file. Based on the type of content the link points to, the method determines the appropriate
        scraper class to use for extracting data from that content.

        Returns:
          The `get_scraper` method returns the scraper class based on the provided link. The method
        checks the link to determine the appropriate scraper class to use based on predefined mappings
        in the `SCRAPER_CLASSES` dictionary. If the link ends with ".pdf", it selects the
        `PyMuPDFScraper` class. If the link contains "arxiv.org", it selects the `ArxivScraper
        """

        SCRAPER_CLASSES = {
            "pdf": PyMuPDFScraper,
            "arxiv": ArxivScraper,
            "newspaper": NewspaperScraper,
            "bs": BeautifulSoupScraper,
            "web_base_loader": WebBaseLoaderScraper,
            # "truth": TruthScraper,
        }

        scraper_key = None

        if link.endswith(".pdf"):
            scraper_key = "pdf"
        elif "arxiv.org" in link:
            scraper_key = "arxiv"
        # elif "truth.com" in link:
            # scraper_key = "truth"
        else:
            scraper_key = self.scraper

        scraper_class = SCRAPER_CLASSES.get(scraper_key)
        if scraper_class is None:
            raise Exception("Scraper not found.")

        return scraper_class
