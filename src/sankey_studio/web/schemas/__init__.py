"""Request and response models of the web API (``from sankey_studio.web.schemas import ...``).

``queries`` holds the query-string models, ``forms`` the multipart form, ``settings`` the settings
wire models and ``merge_settings``. The names are re-exported here so the import path stays stable.
"""

from __future__ import annotations

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
    EntriesQuery,
    ExportChart,
    ExportFormat,
    ExportQuery,
    IdsQuery,
    ListQuery,
    SampleQuery,
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
    "UPLOAD_FILE_FIELD",
    "BootstrapOut",
    "CollectionsQuery",
    "CompareQuery",
    "ConnectionOut",
    "CopyReportOut",
    "EntriesQuery",
    "ExportChart",
    "ExportFormat",
    "ExportQuery",
    "IdsQuery",
    "ListQuery",
    "MongoConnectionIn",
    "SampleQuery",
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
