# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Form models: the multipart upload route.

FastAPI cannot combine a ``Form()`` model with an ``UploadFile`` parameter (the model would be
looked up as an embedded body field and every request answers 422 ``body.form`` missing), so the
route takes ``UploadFormDep``: a dependency that reads the loose ``overwrite`` form field and
hands over an ``UploadForm``. The dependency also looks at the other parts of the request: a field
the form does not know (a typo such as ``overwite``) is a 422 on ``body.<name>``, never ignored.

    async def upload(file: UploadFile, form: UploadFormDep, services: ServicesDep) -> ...:
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Form, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError

__all__ = ["UPLOAD_FILE_FIELD", "UploadForm", "UploadFormDep", "upload_form"]

#: The multipart part that carries the file; every other part must be a field of ``UploadForm``.
UPLOAD_FILE_FIELD = "file"


class UploadForm(BaseModel):
    """The form field next to the file part of ``POST /sources/files``."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    #: Replace a file of the same name instead of answering 409.
    overwrite: bool = False


async def upload_form(request: Request, overwrite: Annotated[bool, Form()] = False) -> UploadForm:
    """Dependency: the multipart ``overwrite`` field as an ``UploadForm``.

    Raises ``RequestValidationError`` (422, ``loc`` = ``("body", name)``) for any other part than
    the file, so a misspelt ``overwite=true`` cannot silently keep the safe default.
    """
    form = await request.form()
    unknown = dict.fromkeys(key for key in form if key != UPLOAD_FILE_FIELD)
    try:
        return UploadForm.model_validate({**unknown, "overwrite": overwrite})
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in errors]
        ) from None


UploadFormDep = Annotated[UploadForm, Depends(upload_form)]
