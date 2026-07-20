import json

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response
from markupsafe import Markup

templates = Jinja2Templates(directory="app/templates")
templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}


def _tojson(value) -> Markup:
    return Markup(json.dumps(value, ensure_ascii=False))


templates.env.filters["tojson"] = _tojson


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200) -> Response:
    return templates.TemplateResponse(request, name, context or {}, status_code=status_code)
