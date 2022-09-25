from sanic import Sanic
from sanic.response import json
import re
import cloudscraper
import base64
from scrapy.selector import Selector
from typing import Iterable
from collections import defaultdict
from typing import Dict, FrozenSet

from sanic import Sanic, response
from sanic.router import Route


def _add_cors_headers(response, methods: Iterable[str]) -> None:
    allow_methods = list(set(methods))
    if "OPTIONS" not in allow_methods:
        allow_methods.append("OPTIONS")
    headers = {
        "Access-Control-Allow-Methods": ",".join(allow_methods),
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": (
            "origin, content-type, accept, "
            "authorization, x-xsrf-token, x-request-id"
        ),
    }
    response.headers.extend(headers)


def add_cors_headers(request, response):
    if request.method != "OPTIONS":
        methods = [method for method in request.route.methods]
        _add_cors_headers(response, methods)


def _compile_routes_needing_options(
    routes: Dict[str, Route]
) -> Dict[str, FrozenSet]:
    needs_options = defaultdict(list)
    # This is 21.12 and later. You will need to change this for older versions.
    for route in routes.values():
        if "OPTIONS" not in route.methods:
            needs_options[route.uri].extend(route.methods)

    return {
        uri: frozenset(methods) for uri, methods in dict(needs_options).items()
    }


def _options_wrapper(handler, methods):
    def wrapped_handler(request, *args, **kwargs):
        nonlocal methods
        return handler(request, methods)

    return wrapped_handler


async def options_handler(request, methods) -> response.HTTPResponse:
    resp = response.empty()
    _add_cors_headers(resp, methods)
    return resp


def setup_options(app: Sanic, _):
    app.router.reset()
    needs_options = _compile_routes_needing_options(app.router.routes_all)
    for uri, methods in needs_options.items():
        app.add_route(
            _options_wrapper(options_handler, methods),
            uri,
            methods=["OPTIONS"],
        )
    app.router.finalize()


app = Sanic("cloudscraper-proxy")
scraper = cloudscraper.create_scraper()
pattern = re.compile(
    '^(((ht|f)tps?)://)?[\w-]+(\.[\w-]+)+([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?$')


def _lowercase(obj):
    if isinstance(obj, dict):
        return {k.lower(): _lowercase(v) for k, v in obj.items()}
    elif isinstance(obj, (list, set, tuple)):
        t = type(obj)
        return t(_lowercase(o) for o in obj)
    elif isinstance(obj, str):
        return obj.lower()
    else:
        return obj


@app.route('/', methods=["POST"])
async def index(request, path=""):
    body = request.json
    if not 'method' in body:
        return json({"error": True, "errorMessage": "Missing method.", "success": False})
    if body["method"] == "GET":
        url = body["url"]
        if url:
            if pattern.match(url):
                r = scraper.get(url, headers=body['headers'])
                headers = _lowercase(dict(r.headers))
                data = r.text
                if 'selector' in body and headers['content-type'].startswith("text/html"):
                    selector = body['selector']
                    # try:
                    # print(data)
                    elem = Selector(text=data).css(selector).get()
                    if elem == None:
                        return json({"error": True, "errorMessage": "Element with selector '{}' not found.".format(selector), "success": False})

                    # except:
                    #    return json({"error": True, "errorMessage": "Error selecting element '{}'.".format(selector), "success": False})
                data = elem or data
                if body['wantsBinary']:
                    data = base64.b64encode(
                        data.encode('utf-8')).decode("utf-8")
                res = {
                    "status": r.status_code,
                    "success": True,
                    "data": data,
                    "headers": headers,
                    "statusText": "OK",
                    "isBinary": True
                }
                return json(res)
            else:
                return json({"error": True, "errorMessage": "Malformatted url.", "success": False})
        else:
            return json({"error": True, "errorMessage": "Missing url.", "success": False})
    else:
        return json({"error": True, "errorMessage": "Unsopported method.", "success": False})


@ app.route('/<path:path>')
async def notFound(request, path=""):
    return json({"error": True, "errorMessage": "404: Endpoint '{}' not found.".format(path)})

app.register_listener(setup_options, "before_server_start")

app.register_middleware(add_cors_headers, "response")

if __name__ == '__main__':
    app.run(debug=True)
