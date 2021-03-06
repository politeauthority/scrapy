"""BaseCarpetBag

"""
from datetime import datetime, timedelta
import json
import logging
import os
import time
import urllib3
from urllib3.exceptions import InsecureRequestWarning

import arrow
import requests
from requests.exceptions import ChunkedEncodingError
from requests.exceptions import ConnectionError

from . import carpet_tools as ct
from . import errors


class BaseCarpetBag(object):

    __version__ = "0.0.4d01"

    def __init__(self):
        """
        CarpetBag constructor. Here we set the default, user changeable class vars.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__init__

        :class param headers: Any extra headers to add to the response. This can be manipulated at any time and applied
            just before each request made.
        :class type headers: dict

        :class param user_agent: User selected User Agent to send on every request. This can be updated at any time.
        :class type user_agent: str

        :class param random_user_agent: Setting to decide whether or not to use a random user agent string.
        :class type random_user_agent: bool

        :class param ssl_verify : Skips the SSL cert verification if set False. Sometimes this is needed when hitting
            certs given out by LetsEncrypt.
        :class type ssl_verify: bool

        :class param mininum_wait_time: Minimum amount of time to wait before allowing the next request to go out.
        :class type mininum_wait_time: int

        :class param wait_and_retry_on_connection_error: Time to wait and then retry when a connection error has been
            hit.
        :class type wait_and_retry_on_connection_error: int

        :class param retries_on_connection_failure: Amount of retry attempts to make when a connection_error has been
            hit.
        :class type retries_on_connection_failure: int

        :class param max_content_length: The maximum content length to download with the CarpetBag "save" method, with
            raise as exception if it has surpassed that limit. (@todo This needs to be done still.)
        :class type max_content_length: int

        :class param proxy: Proxy to be used for the connection.
        :class type proxy: dict

        Everything below is still to be implemented!
        :class param change_user_interval: Changes identity every x requests. @todo: Implement the changing.

        :class param username: User name to use when needing to authenticate a request. @todo Authentication needs to
            be implemented.

        :class param password: Password to use when needing to authenticate a request. @todo Authentication needs to
            be implemented.

        :class param auth_type: Authentication class to use when needing to authenticate a request. @todo
            Authentication needs to be implemented.
        """
        self.headers = {}
        self.user_agent = "CarpetBag v%s" % self.__version__
        self.random_user_agent = False
        self.mininum_wait_time = 0  # Sets the minimum wait time per domain to make a new request in seconds.
        self.wait_and_retry_on_connection_error = 0
        self.retries_on_connection_failure = 5
        self.max_content_length = 200000000  # Sets the maximum download size, default 200 MegaBytes, in bytes.
        self.username = None
        self.password = None
        self.auth_type = None
        self.change_identity_interval = 0
        # self.remote_service_api = "https://www.bad-actor.services/api"
        self.remote_service_api = "https://bas.bitgel.com/api"
        self.public_proxies_max_last_test_weeks = 5
        self.paginatation_map = {
            "field_name_page": "page",
            "field_name_total_pages": "total_pages",
            "field_name_data": "objects",
        }

        # These are private reserved class vars, don"t use these!
        self.outbound_ip = None
        self.request_count = 0
        self.request_total = 0
        self.last_request_time = None
        self.last_response = None
        self.manifest = []
        self.proxy = {}
        self.proxy_bag = []
        self.proxy_current = {}
        self.random_proxy_bag = False
        self.send_user_agent = ""
        self.ssl_verify = True
        self.force_skip_ssl_verify = False
        self.send_usage_stats_val = False
        self.usage_stats_api_key = ""
        self.retry_on_proxy_failure = True

        self.one_time_headers = []
        self.logger = logging.getLogger(__name__)

    def __repr__(self):
        """
        CarpetBag's representation.
        Normally like, <CarpetBag>
        With a selected proxy in use, <CarpetBag Proxy:https://66.98.56.237:8080>
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__repr__

        """
        proxy = ""
        if self.proxy.get("http"):
            proxy = " Proxy:%s" % self.proxy.get("http")
        elif self.proxy.get("https"):
            proxy = " Proxy:%s" % self.proxy.get("https")

        return "<CarpetBag%s>" % proxy

    def _make_request(self, method, url, payload={}):
        """
        Makes the URL request, over your chosen HTTP verb.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__make_request

        :param method: The method for the request action to use. "GET", "POST", "PUT", "DELETE"
        :type method: string
        :param url: The url to fetch/ post to.
        :type: url: str
        :param payload: The payload to be sent, if we"re making a post request.
        :type payload: dict
        :returns: A Requests module instance of the response.
        :rtype: <Requests.response> obj
        """
        ts_start = int(round(time.time() * 1000))
        url = ct.url_add_missing_protocol(url)
        headers = self.headers
        urllib3.disable_warnings(InsecureRequestWarning)
        self._start_request_manifest(method, url, payload)
        self._increment_counters()
        self._handle_sleep(url)

        response = self._make(method, url, headers, payload)
        if response.status_code >= 500:
            self.logger.warning("URL %s Received a server error response <%s>" % (url, response.status_code))
            self.logger.debug(response.text)

        roundtrip = self._after_request(ts_start, url, response)
        response.roundtrip = roundtrip

        self._end_manifest(response, response.roundtrip)
        self.logger.debug("Response took %s for %s" % (roundtrip, url))

        self._cleanup_one_time_headers()
        self._send_usage_stats()

        return response

    def _handle_sleep(self, url):
        """
        Sets CarpetBag to sleep if we are making a request to the same server in less time then the value of
        self.mininum_wait_time allows for.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__handle_sleep

        :param url: The url being requested.
        :type url: str
        :returns: True if sleep runs successfully.
        :rtype: bool
        """
        if not self.mininum_wait_time:
            return True

        if not self.last_request_time:
            return True

        # Checks that the next server we're making a request to is the same as the previous request.
        # tld.get_fld(self.last_response.url)

        if self.last_response and self.last_response.domain != ct.url_domain(url):
            return True

        # Checks the time of the last request and sets the sleep timer for the difference.
        diff_time = datetime.now() - self.last_request_time
        if diff_time.seconds < self.mininum_wait_time:
            sleep_time = self.mininum_wait_time - diff_time.seconds
            self.logger.debug("Sleeping %s seconds before next request.")
            time.sleep(sleep_time)

        return True

    def _get_headers(self):
        """
        Gets headers for the request, checks for user values in self.headers and then creates the rest.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__get_headers

        :returns: The headers to be sent in the request.
        :rtype: dict
        """
        send_headers = {}
        self._set_user_agent()
        if self.send_user_agent:
            send_headers["User-Agent"] = self.send_user_agent

        for key, value in self.headers.items():
            send_headers[key] = value

        return send_headers

    def _validate_continents(self, requested_continents):
        """
        Checks that the user selected continents are usable strings, not just some garbage.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__validate_continents

        :param requested_continents: User selected list of continents.
        :type requested_continents: list
        :returns: Success if supplied continent list is valid.
        :rtype: bool
        :raises: carpetbag.errors.InvalidContinent
        """
        valid_continents = ["North America", "South America", "Asia", "Europe", "Africa", "Australia", "Antarctica"]
        for continent in requested_continents:
            if continent not in valid_continents:
                self.logger.error("Unknown continent: %s" % continent)
                raise errors.InvalidContinent(continent)

        return True

    def _set_user_agent(self):
        """
        Sets a user agent to the class var if it is being used, otherwise if it"s the 1st or 10th request, fetches a new
        random user agent string.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__set_user_agent

        :returns: The user agent string to be used in the request.
        :rtype: str
        """
        if self.user_agent:
            self.send_user_agent = self.user_agent

        return True

    def _fmt_request_args(self, method, headers, url, payload={}, retry=0, internal=False):
        """
        Formats args to be sent to the requests.request()
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__fmt_request_args

        :param method: HTTP verb to use.
        :type method: str
        :param headers: The headers to be sent on the request.
        :type: headers: dict
        :param url: The url to fetch/ post to.
        :type: url: str
        :param payload: The data to be sent over the POST request.
        :type payload: dict
        :param retry: The current attempt number for the request.
        :type retry: int
        :param internal: Set True if hitting a bad-actor.services API, this will disable SSL certificate verification.
        :type internal: bool
        :returns: Formatted arguments to send to the Requests module.
        :rtype: dict
        """
        request_args = {
            "allow_redirects": True,
            "method": method,
            "url": url,
            "headers": headers,
        }

        if method == "GET":
            request_args["stream"] = True

        if internal:
            request_args["verify"] = False
        else:
            if retry == 0:
                request_args["verify"] = True
            else:
                request_args["verify"] = self.ssl_verify

        if self.force_skip_ssl_verify:
            request_args["verify"] = False

        # Setup Proxy if we have one, and we're not sending an "internal" to bad-actor.services request.
        if self.proxy and not internal:
            request_args["proxies"] = self.proxy

        # Setup payload if we have it.
        if payload:
            if method == "GET":
                request_args["params"] = payload
            elif method in ["PUT", "POST"]:
                request_args["data"] = payload
        return request_args

    def _make(self, method, url, headers, payload={}, retry=0):
        """
        Just about every CarpetBag request comes through this method. It makes the request and handles different
        errors that may come about.
        @todo: rework arg list to be url, payload, method,
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__make

        self.wait_and_retry_on_connection_error can be set to add a wait and retry in seconds.

        :param method: HTTP verb to use.
        :type method: str
        :param url: The url to fetch/ post to.
        :type: url: str
        :param headers: The headers to be sent on the request.
        :type: headers: dict
        :param payload: The data to be sent over the POST request.
        :type payload: dict
        :param retry: The current attempt number for the request.
        :type retry: int
        :returns: A Requests module instance of the response.
        :rtype: <Requests.response> obj
        """
        self.logger.debug("Making request: %s" % url)

        request_args = self._fmt_request_args(
            method=method,
            headers=headers,
            url=url,
            payload=payload,
            retry=retry)
        self.manifest[0]["request_args"] = request_args

        try:
            self.logger.debug("Request args: %s" % str(request_args))
            response = requests.request(**request_args)

        # Catch Connection Refused Error. This is probably happening because of a bad proxy.
        # Catch an error with the connection to the Proxy
        except requests.exceptions.ProxyError:
            if self.random_proxy_bag:
                self.logger.debug("Hit a proxy error, picking a new one from proxy bag and continuing.")
                self.manifest[0]["errors"].append("ProxyError")
                if self.send_usage_stats_val:
                    self._send_usage_stats(False)
                    raise requests.exceptions.ProxyError
            else:
                self.logger.debug("Hit a proxy error, sleeping for %s and continuing." % 5)
                time.sleep(5)

            if not self.retry_on_proxy_failure:
                raise requests.exceptions.ProxyError

            if self.random_proxy_bag:
                self.reset_proxy_from_bag()

            retry += 1

            return self._make(method, url, headers, payload, retry)

        # # Catch ConnectionRefused Error, right now we'll handle it the same way we handle ProxyErrors
        # except requests.exceptions.ConnectionRefusedError:
        #     retry += 1
        #     if self.random_proxy_bag:
        #         self.logger.warning("Hit a proxy error, picking a new one from proxy bag and continuing.")
        #         self.manifest[0]["errors"].append("ProxyError")
        #         self._send_usage_stats(False)
        #         self.reset_proxy_from_bag()
        #     else:
        #         self.logger.warning("Hit a proxy error, sleeping for %s and continuing." % 5)
        #         time.sleep(5)

        #     retry += 1
        #     if not self.retry_on_proxy_failure:
        #         raise requests.exceptions.ProxyError

        #     return self._make(method, url, headers, payload, retry)

        # Catch an SSLError, seems to crop up with LetsEncypt certs.
        except requests.exceptions.SSLError:
            self.logger.warning("Received an SSL Error from %s" % url)
            if not self.ssl_verify:
                self.logger.warning("Re-running request without SSL cert verification.")
                retry += 1
                return self._make(method, url, headers, payload, retry)
            else:
                msg = """There was an error with the SSL cert, this happens a lot with LetsEncrypt certificates."""
                msg += """ Use the carpetbag.use_skip_ssl_verify() method to enable skipping of SSL Certificate """
                msg += """checks"""
                self.logger.error(msg)
                raise requests.exceptions.SSLError

        # Catch the server unavailble exception, and potentially retry if needed.
        except requests.exceptions.ConnectionError:
            retry += 1
            response = self._handle_connection_error(method, url, headers, payload, retry)

        # Catch a ChunkedEncodingError, response when the expected byte size is not what was recieved, probably a
        # bad proxy
        except ChunkedEncodingError:
            if self.random_proxy_bag:
                self.logger.warning("Hit a ChunkedEncodingError, proxy might be running to slow resetting proxy.")
                self.reset_proxy_from_bag()
            else:
                raise ChunkedEncodingError

        return response

    def _make_internal(self, uri_segment, payload={}, page=1):
        """
        Makes requests to bad-actor.services. For getting data like current_ip, proxies and sending usage data if
        enabled and you have an API key.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__make_internal

        :param uri_segment: The url to fetch/ post to.
        :type: uri_segment: str
        :param payload: The data to be sent over the POST request.
        :type payload: dict
        :returns: The response from bad-actor.services
        :rtype: <Response> obj
        """
        # This is a hack because BadActor does not have the IP /api route set up yet.
        if uri_segment == "ip":
            api_url = ct.url_join(self.remote_service_api.replace("api", "ip"))
        else:
            api_url = ct.url_join(self.remote_service_api, uri_segment)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CarpetBag v%s" % self.__version__
        }
        if self.send_usage_stats_val and self.usage_stats_api_key:
            headers["Api-Key"] = self.usage_stats_api_key

        method = "GET"
        # Get Bad-Actor.Services proxies
        if uri_segment == "proxies":
            send_payload = self._internal_proxies_params(payload)

        # Submit a proxy peport
        elif uri_segment == "proxy_reports":
            method = "POST"
            send_payload = json.dumps(payload)
        else:
            send_payload = payload

        request_args = self._fmt_request_args(
            method=method,
            headers=headers,
            url=api_url,
            payload=send_payload,
            internal=True)

        try:
            urllib3.disable_warnings(InsecureRequestWarning)
            response = requests.request(**request_args)
        except requests.exceptions.ConnectionError:
            raise errors.NoRemoteServicesConnection("Cannot connect to bad-actor.services API")

        return response

    def _internal_proxies_params(self, payload):
        """
        Creates the params to query bad-actor.services for ranked proxies.
        @unit-tested: carpetbag/tests/test_base_carpetbag.py.test__make_internal_proxies_params
        @todo: Create unit test coverage!

        :param payload: The data to be sent over the POST request.
        :type payload: dict
        :returns: The GET query parameters to be sent to bad-actor.services for proxies.
        :rtype: dict
        """
        params = {"q": {}}
        if payload:
            params["q"]["filters"] = []

            # Add continent filter
            if payload.get("continent"):
                params["q"]["filters"].append(self._internal_proxies_filter_continent_param(payload))

            # Add filter for proxies tested within the last x weeks
            params["q"]["filters"].append(self._internal_proxies_filter_last_test_param(payload))

            # Add filter for proxies with a quality greater than x.
            params["q"]["filters"].append(self._internal_proxies_filter_quality_param(payload))

        # Add the order by query portion, ordering by the quality.
        params["q"]["order_by"] = [{"field": "quality", "direction": "desc"}]

        # params["q"]["limit"] = 100
        # if page != 1:
        #     params["q"]["page"] = page
        params["q"] = json.dumps(params["q"])

        return params

    def _internal_proxies_filter_continent_param(self, payload):
        """
        Creates the filter arguments for continent filtering to be sent to https://www.bad-actor.services/api/proxies/

        :param payload: The query payload to build args from. Not all params need this, but it's always
                        passed regardless
        :type payload: dict
        :returns: FlaskRestless style query filter.
        :rtype: dict
        """
        return dict(
            name="continent",
            op="eq",
            val=payload.get("continent"))

    def _internal_proxies_filter_last_test_param(self, payload):
        """
        Creates the filter arguments for last_test filtering to be sent to https://www.bad-actor.services/api/proxies/
        Will create a search with the last_test being self.public_proxies_max_last_test_weeks, currently defaulted to
        5 weeks.

        :param payload: The query payload to build args from. Not all params need this, but it's always
                        passed regardless
        :type payload: dict
        :returns: FlaskRestless style query filter.
        :rtype: dict
        """
        one_week_ago = ct.date_to_json(
            arrow.utcnow().datetime - timedelta(weeks=self.public_proxies_max_last_test_weeks))
        return dict(
            name="last_tested",
            op=">",
            val=one_week_ago)

    def _internal_proxies_filter_quality_param(self, payload):
        """
        Creates the filter arguments for quality filtering to be sent to https://www.bad-actor.services/api/proxies/

        :param payload: The query payload to build args from. Not all params need this, but it's always
                        passed regardless
        :type payload: dict
        :returns: FlaskRestless style query filter.
        :rtype: dict
        """
        return dict(
            name="quality",
            op=">",
            val=0)

    def _handle_connection_error(self, method, url, headers, payload, retry):
        """
        Handles a connection error. If self.wait_and_retry_on_connection_error has a value other than 0 we will wait
        that long until attempting to retry the url again.

        :param url: The url to fetch/ post to.
        :type: url: str
        :param headers: The headers to be sent on the request.
        :type: headers: dict
        :param payload: The data to be sent over the POST request.
        :type payload: dict
        :param retry: Number of attempts that have already been performed for this request.
        :type retry: int
        :returns: A Requests module instance of the response.
        :rtype: <Requests.response> obj or None
        """
        self.logger.error("Unable to connect to: %s" % url)

        if self.random_proxy_bag:
            self.reset_proxy_from_bag()

        if not self.retries_on_connection_failure:
            raise ConnectionError

        if retry >= self.retries_on_connection_failure:
            raise ConnectionError

        # Go to sleep and try again
        self.logger.warning(
            "Attempt %s of %s. Sleeping and retrying url in %s seconds." % (
                str(retry),
                self.retries_on_connection_failure,
                self.wait_and_retry_on_connection_error))
        if self.wait_and_retry_on_connection_error:
            time.sleep(self.wait_and_retry_on_connection_error)

        return self._make(method, url, headers, payload, retry)

    def _after_request(self, ts_start, url, response):
        """
        Runs after request operations, sets counters and run times. This Should be called before any raised known
        exceptions.

        :param ts_start: The start of the request.
        :type st_start: int
        :param url: The url being requested.
        :type url: str
        :param response: The <Response> object from <Requests>
        :type response: <Response> object
        :returns: The round trip time from the request in milliseconds.
        :type: float
        """
        self.last_response = response
        ts_end = int(round(time.time() * 1000))
        roundtrip = ts_end - ts_start
        self.last_request_time = datetime.now()
        if response:
            response.roundtrip = roundtrip
            response.domain = ct.url_domain(response.url)
        self.ts_start = None

        return roundtrip

    def _increment_counters(self):
        """
        Add one to each request counter after a request has been made.

        """
        self.request_count += 1
        self.request_total += 1

    def _start_request_manifest(self, method, url, payload={}):
        """
        Starts a new manifest for the url being requested, and saves it into the self.manifest var.

        :param method: The method for the request action to use. "GET", "POST", "PUT", "DELETE"
        :type method: string
        :param url: The url to fetch/ post to.
        :type: url: str
        :param payload: The payload to be sent, if we"re making a post request.
        :type payload: dict
        :returns: The newly created manifest record.
        :type: dict
        """
        new_manifest = {
            "method": method,
            "url": url,
            "payload_size ": 0,
            "date_start": arrow.utcnow().datetime,
            "date_end": None,
            "roundtrip": None,
            "response": None,
            "attempt_count": 1,
            "errors": [],
            "response_args": {},
            "success": None
        }
        self.manifest.insert(0, new_manifest)
        return new_manifest

    def _end_manifest(self, response, roundtrip, success=True):
        """
        Ends the manifest for a requested url with end times and run times.

        :param response: The response pulled from the request.
        :rtype response: <Response> obj
        :param roundtrip: The time it took to get the response.
        :type roundtrip: float
        :param success: The success or failure of a request that we are sending data about.
        :type success: bool
        :returns: True if everything worked.
        :type: bool
        """
        if success:
            self.manifest[0]["date_end"] = arrow.utcnow().datetime
            self.manifest[0]["roundtrip"] = roundtrip
            self.manifest[0]["response"] = response

        self.manifest[0]["success"] = success

        return True

    def _cleanup_one_time_headers(self):
        """
        Handles the one time headers by removing them after the request has gone through successfully.
        @todo: Unit test!

        :returns: Success if it happens.
        :rtype: True
        """
        for header in self.one_time_headers:
            if header in self.headers:
                self.headers.pop(header)
        self.one_time_headers = []

        return True

    def _send_usage_stats(self, success=True):
        """
        Sends the usage stats to bad-actor.services if sending usage stats is enabled, and the user has an API key
        ready to go.

        :param success: The success or failure of a request that we are sending data about.
        :type success: bool
        """
        if not self.random_proxy_bag:
            self.logger.debug("USAGE STATS: Not using random public proxy, not sending usage metrics.")
            return False

        usage_payload = {
            "proxy_id": self.proxy_bag[0]["id"],
            "request_url": self.manifest[0]["url"],
            # "request_payload_size": self.manifest[0]["payload_size"],
            "request_method": self.manifest[0]["method"],
            "response_time": None,
            # "response_payload_size": 0,
            "response_success": success,
            # "response_ip": "",
            "user_ip": self.non_proxy_user_ip,
            "score": 0
        }

        proxy_quality = self.proxy_bag[0]["quality"]
        if not proxy_quality:
            proxy_quality = 0

        proxy_score = 0
        if success:
            proxy_score = proxy_quality + 1
            usage_payload["response_time"] = (self.manifest[0]["date_end"] - self.manifest[0]["date_start"]).seconds

        usage_payload["score"] = proxy_score

        internal_request = self._make_internal("proxy_reports", usage_payload)
        if internal_request.status_code in [200, 201]:
            self.logger.debug("Saved request to bad-actor")
        else:
            self.logger.error("Had an issue saving response: %s" % internal_request.json())

    def _determine_save_file_name(self, url, content_type, destination):
        """
        Determines the local file name, based on the url, the content_type and the user requested destination.

        :param url: The url to fetch.
        :type: url: str
        :param content_type: The content type header from the response.
        :type content_type: str
        :param destination: Where on the local file system to store the image.
        :type: destination: str
        :returns: The absolute path for the file.
        :rtype: str
        """
        # Figure out the save directory
        if os.path.isdir(destination):
            destination_dir = destination

        elif destination[len(destination) - 1] == "/":
            destination_dir = destination
        else:
            destination_dir = destination[:destination.rfind("/")]
        destination_last = destination[destination.rfind("/") + 1:]
        self._prep_destination(destination_dir)

        # Decide the file name.
        file_extension = ct.content_type_to_extension(content_type)
        url_disect = ct.url_disect(url)

        # If the chosen destination is a directory, find a name for the file.
        if os.path.isdir(destination):
            phile_name = url_disect["last"]
            if "." not in phile_name:
                if file_extension:
                    full_phile_name = os.path.join(destination, "%s.%s" % (phile_name, file_extension))

            elif "." in url_disect["last"]:
                file_extension = url_disect["uri"][:url_disect["uri"].rfind(".") + 1]
                phile_name = url_disect["last"]
                full_phile_name = os.path.join(destination, phile_name)

        else:
            # If the chosen drop is not a directory, use the name given.
            if "." in destination_last:
                full_phile_name = os.path.join(destination_dir, destination_last)

            elif "." in url_disect["last"]:
                phile_name = url_disect["last"][:url_disect["last"].rfind(".")]
                file_extension = url_disect["last"][url_disect["last"].rfind(".") + 1:]

                full_phile_name = destination_dir + "%s.%s" % (phile_name, file_extension)

        return full_phile_name

    def _prep_destination(self, destination):
        """
        Attempts to create the destination directory path if needed.

        :param destination:
        :type destination: str
        :returns: Success or failure of pepping destination.
        :rtype: bool
        """
        if os.path.exists(destination):
            return True

        try:
            os.makedirs(destination)
            return True
        except Exception:
            self.logger.error("Could not create directory: %s" % destination)
            return False

# EndFile: carpetbag/carpetbag/base_carpetbag.py
