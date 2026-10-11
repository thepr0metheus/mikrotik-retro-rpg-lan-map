"""The map's own routes, described for whoever calls them: OpenAPI 3.1 at /openapi.json.

The description is read off the very table the server answers by, RequestHandler.ROUTES, and
off the handlers themselves. The first paragraph of a handler's docstring says what the route
does; its code says which questions it reads, what it answers with and whom it turns away. The
pages are the HTML files beside the scripts, named by their own titles. Nothing here is a list
kept by hand: a list kept by hand falls behind the table it copies.

What is not described yet says so in words. An empty schema reads as "no body", and that would
be a lie.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path


class ApiSpec:
    """One description of the map's routes, made from the handler class and the page files."""

    OPENAPI = "3.1.0"
    ABOUT = ("The home network map: a snapshot of the router's tables, read-only. Nobody logs in: "
             "who may read and who may change the map is decided by the address a request comes "
             "from. A reading from outside the networks the map is shown to gets 403, and a change "
             "must also come from the map's own page, as JSON. A refusal is JSON, "
             "{\"error\": \"…\"}, said in the language of ?lang=. The pages' own files — scripts, "
             "styles, pictures and the dictionaries at /lang/<code>.json — are served beside the "
             "pages and are not listed.")
    #: What the questions a route reads mean. When the code reads one that has no words here,
    #: the description says so, and the tests say it out loud.
    QUESTIONS = {
        "lang": "the language of the answer, by its dictionary's code (en, ru); without it the "
                "browser's Accept-Language decides, and failing that it is English",
        "at": "a kept snapshot, by its name from /api/history; without it, the latest one",
    }
    NOT_DESCRIBED = "not described yet"
    #: A handler reads a question as self.asked("at"), and the language through self.tongue().
    ASKED = re.compile(r"""self\.asked\(\s*["']([a-z_]+)["']""")
    #: What a handler's code says about its answers: a call in it, the status it means, and the
    #: words for that status. A later line for the same status replaces an earlier one.
    ANSWERS = (
        ("self.send_json(200", "200", {"description": "JSON; its fields are not described here yet.",
                                       "content": {"application/json": {}}}),
        ('self.send_body(200, "text/markdown', "200", {"description": "Markdown text.",
                                                      "content": {"text/markdown": {}}}),
        ("self.read_json()", "400", {"description": "The body lacks what this route needs."}),
        ("self.watch()", "403", {"description": "Asked from outside the networks the map is shown to."}),
        ("self.allow_write(", "403", {"description": "Not from the map's own page, or from an address "
                                                     "that may not change the map."}),
        ("self.allow_write(", "415", {"description": "Not sent as JSON: Content-Type must be "
                                                     "application/json."}),
    )
    TITLE = re.compile(r"<title[^>]*>([^<]*)</title>")

    def __init__(self, handler: type, web_dir: Path, version: str | None):
        self.handler = handler
        self.web_dir = Path(web_dir)
        #: A working copy holds no commit, and /healthz says null; here the field must be a
        #: string, so it says that it does not know.
        self.version = version or "unknown"

    def document(self) -> dict:
        paths: dict = {}
        for (method, path), name in self.handler.ROUTES.items():
            paths.setdefault(path, {})[method.lower()] = self.operation(getattr(self.handler, name))
        for path, title in self.pages():
            paths.setdefault(path, {})["get"] = self.page(title)
        # Nobody logs in, so there is no scheme to name, and every route is open: security [].
        return {"openapi": self.OPENAPI,
                "info": {"title": "lan-map", "version": self.version, "description": self.ABOUT},
                "paths": dict(sorted(paths.items())),
                "components": {"securitySchemes": {}}}

    def operation(self, handler) -> dict:
        """One route, as its handler tells it: the docstring in words, the code in facts."""
        source = inspect.getsource(handler)
        summary, more = self.told(handler)
        operation = {"summary": summary, "security": [],
                     "responses": {status: answer for mark, status, answer in self.ANSWERS if mark in source}}
        if more:
            operation["description"] = more
        questions = self.ASKED.findall(source) + (["lang"] if "self.tongue()" in source else [])
        if questions:
            operation["parameters"] = [
                {"name": name, "in": "query", "required": False, "schema": {"type": "string"},
                 "description": self.QUESTIONS.get(name, self.NOT_DESCRIBED)}
                for name in dict.fromkeys(questions)]
        if "self.read_json()" in source:
            operation["requestBody"] = {"required": True,
                                        "description": "JSON; its fields are not described here yet.",
                                        "content": {"application/json": {}}}
        return operation

    @staticmethod
    def told(handler) -> tuple:
        """A docstring's first paragraph, and the rest of it, each said on one line."""
        first, _, rest = (inspect.getdoc(handler) or "").partition("\n\n")
        return " ".join(first.split()), " ".join(rest.split())

    def pages(self) -> list:
        """Every HTML file beside the scripts: its address, and the title it gives itself."""
        found = []
        for file in sorted(self.web_dir.glob("*.html")):
            title = self.TITLE.search(file.read_text(encoding="utf-8"))
            found.append(("/" if file.name == "index.html" else f"/{file.name}",
                          title.group(1).strip() if title else ""))
        return found

    @staticmethod
    def page(title: str) -> dict:
        """A page for people. One with no title says nothing, and the tests notice."""
        return {"summary": f"A page for people: {title}." if title else "", "security": [],
                "responses": {"200": {"description": "HTML.", "content": {"text/html": {}}}}}
