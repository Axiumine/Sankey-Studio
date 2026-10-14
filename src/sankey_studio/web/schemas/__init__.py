"""Request and response models of the web API (``from sankey_studio.web.schemas import ...``).

``queries`` holds the query-string models, ``forms`` the multipart form, ``folders`` the library
folder wire models, ``settings`` the settings wire models and ``merge_settings``. The names are
re-exported here so the import path stays stable.
"""

from __future__ import annotations

from sankey_studio.web.schemas.folders import MOVE_IDS_MAX, FolderList, MoveGraphsIn
from sankey_studio.web.schemas.forms import (
    UPLOAD_FILE_FIELD,
    UploadForm,
    UploadFormDep,
    upload_form,
)
from sankey_studio.web.schemas.queries import (
    COMPARE_IDS_MAX,
    EXPORT_IDS_MAX,
    IMAGE_SIDE_MAX,
    LIST_LIMIT_MAX,
    CollectionsQuery,
    CompareQuery,
    CreateQuery,
    EntriesQuery,
    ExportChart,
    ExportFormat,
    ExportQuery,
    IdsQuery,
    ListQuery,
    RenderQuery,
    SampleQuery,
    ScopeQuery,
    ThemeQuery,
    split_ids,
)
from sankey_studio.web.schemas.settings import (
    BootstrapOut,
    ConnectionOut,
    CopyReportOut,
    MongoConnectionIn,
    SettingsIn,
    SettingsOut,
    SettingsSaved,
    bootstrap_out,
    connection_out,
    merge_settings,
    settings_out,
    settings_saved,
)

__all__ = [
    "COMPARE_IDS_MAX",
    "EXPORT_IDS_MAX",
    "IMAGE_SIDE_MAX",
    "LIST_LIMIT_MAX",
    "MOVE_IDS_MAX",
    "UPLOAD_FILE_FIELD",
    "BootstrapOut",
    "CollectionsQuery",
    "CompareQuery",
    "ConnectionOut",
    "CopyReportOut",
    "CreateQuery",
    "EntriesQuery",
    "ExportChart",
    "ExportFormat",
    "ExportQuery",
    "FolderList",
    "IdsQuery",
    "ListQuery",
    "MongoConnectionIn",
    "MoveGraphsIn",
    "RenderQuery",
    "SampleQuery",
    "ScopeQuery",
    "SettingsIn",
    "SettingsOut",
    "SettingsSaved",
    "ThemeQuery",
    "UploadForm",
    "UploadFormDep",
    "bootstrap_out",
    "connection_out",
    "merge_settings",
    "settings_out",
    "settings_saved",
    "split_ids",
    "upload_form",
]
