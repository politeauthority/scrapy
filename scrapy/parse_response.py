"""Parse Response
Handles parsing various html pages. This module is pretty expiremental right now and may prove not necisarry later on.

"""
from bs4 import BeautifulSoup
import tld


class ParseResponse(object):

    def __init__(self, response=None):
        """
        Creates a new respose parser.

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
        Grabs all anchor links for the content and orgainizes it by local or remote.

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
                    "url": self.add_missing_protocol(link.find("a", {"class": "result__url"}).text.strip())
                }
            )
        return results

    def freeproxylistdotnet(self, continents=[]):
        """
        Parses the proxies available from free-proxy-list.net

        :returns: List of Proxies and related info.
        :rtype: list
        """
        proxies = self._parse_free_proxy_list()

        return proxies

    def _parse_free_proxy_list(self):
        """
        Parses the html response from free-proxy-list.net
        Each item in the list contains the following.
        {
            "ip": '129.145.123.151',
            "location": "Bulgaria",
            "ssl": True
        }

        :returns: List of Proxies and related info.
        :rtype: list
        """
        proxies = []
        for prx in self.soup.findAll("tr")[1:]:
            row = prx.findAll("td")
            if len(row) < 6:
                continue
            proxy = {}
            proxy["ip"] = "%s:%s" % (row[0].text, row[1].text)
            proxy["country"] = row[3].text
            proxy["continent"] = self._get_continent_from_country(proxy["country"])
            if proxy["continent"]:
                proxy["location"] = "%s / %s" % (proxy["continent"], proxy["country"])
            else:
                proxy["location"] = proxy["country"]
            proxy["ssl"] = False
            if row[6].text == "yes":
                proxy["ssl"] = True
            proxies.append(proxy)
        return proxies

    @staticmethod
    def add_missing_protocol(url):
        """
        Adds the protocol "http://" if a protocal is not present.

        :param url: The url that may or may not be missing a protocol.
        :type url: str
        :returns: Safe url with protocal.
        :rtype: str
        """
        if url[:8] == "https://" or url[:7] == "http://":
            return url
        else:
            return "%s%s" % ("http://", url)

    @staticmethod
    def remove_protocol(url):
        """
        Adds the protocol "http://" if a protocal is not present.

        :param url: The url that may or may not be missing a protocol.
        :type url: str
        :returns: Safe url with protocal.
        :rtype: str
        """
        url = url.replace("https", "")
        url = url.replace("http", "")
        url = url.replace("://", "")
        if "/" in url:
            url = url[: url.find("/")]
        return url

    def _make_soup(self):
        """
        Converts the self.content var into soup.

        """
        self.content = self.response.text
        self.domain = tld.get_tld(self.response.url)
        return BeautifulSoup(self.content, "html.parser")

    @staticmethod
    def _get_continent_from_country(country):
        """
        Gets a countries continent from the country string

        :param country:
        :type country: str
        :returns:
        :rtype: str
        """
        if not country:
            return 'Unknown'
        country = country.lower()

        north_america = ["united states", "canada", "mexico"]
        south_america = ["brazil", "colombia", "ecuador", "venezuela"]
        europe = ["bulgaria", "france", "russian federation"]
        asia = ["bangladesh", "indonesia", "thailand", "india", "japan", "ukraine"]
        africa = []
        austrailia = ["Austrailia"]
        continent = ''

        if country in north_america:
            continent = "North America"
        elif country in south_america:
            continent = "South America"
        elif country in europe:
            continent = "Europe"
        elif country in asia:
            continent = "Asia"
        elif country in africa:
            continent = "Africa"
        elif country in austrailia:
            continent = "Austrailia"

        else:
            continent = "Unknown"

        return continent

# EndFile: scrapy/scrapy/parse_response.py
