"""Parse Response
Handles parsing various html pages. This module is pretty experimental right now and may prove not necessary later on.

"""
from bs4 import BeautifulSoup
import tld

from . import carpet_tools as ct


class ParseResponse(object):

    def __init__(self, response=None):
        """
        Creates a new response parser.

        :param response: The response from the Requests module
        :type response: <Requests>
        """
        self.response = response
        self.content = None
        self.domain = None
        self.soup = self._make_soup()

    def __repr__(self):
        return "<Parsed %s>" % self.response.url

    def get_title(self):
        """
        Gets the title of the current content

        :returns: The page"s title.
        :rtype: str
        """
        if not self.soup:
            return ""
        elif not self.soup.title:
            return ""
        elif not self.soup.title.string:
            return ""
        return self.soup.title.string.strip()

    def get_links(self, content=None):
        """
        Grabs all anchor links for the content and organizes it by local or remote.

        :param content: A partial piece of content, optional, otherwise scans the entire segment.
        :type content: str
        """
        if content:
            soup = content
        else:
            soup = self.soup

        anchors = soup.findAll("a")

        ret = {
            "local": [],
            "remote": []
        }
        for anchor in anchors:
            if not anchor.get("href"):
                continue
            if anchor["href"][0] == "#":
                continue

            if self._get_remote_links(anchor["href"]):
                if anchor["href"] not in ret["remote"]:
                    ret["remote"].append(anchor["href"])
                    continue

            ret["local"].append(anchor["href"])
        return ret

    def _get_remote_links(self, anchor):
        """
        Looks for anchors that are linking to other sites.

        :param anchor: Url to inspect for local or remote url.
        :type anchor: str
        """
        if anchor[:7] == "http://" or anchor[:8] == "https://":
            return True
        return False

    def duckduckgo_results(self):
        """
        Parses a search result page from duckduckgo.com

        """
        links = self.soup.findAll("div", {"class": "result"})
        results = []
        for link in links:
            results.append(
                {
                    "title": link.h2.text.strip(),
                    "description": link.find("a", {"class": "result__snippet"}).text.strip(),
                    "url": ct.url_add_missing_protocol(link.find("a", {"class": "result__url"}).text.strip())
                }
            )
        return results

    def _make_soup(self):
        """
        Converts the self.content var into soup.

        """
        self.content = self.response.text
        self.domain = tld.get_tld(self.response.url)
        return BeautifulSoup(self.content, "html.parser")

# EndFile: carpetbag/carpetbag/parse_response.py
