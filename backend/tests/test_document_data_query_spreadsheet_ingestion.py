from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook


def make_workbook(sheets: list[tuple[str, list[list[object | None]]]]) -> bytes:
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    for title, rows in sheets:
        sheet = workbook.create_sheet(title=title)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_parser_accepts_one_data_sheet_and_ignores_empty_extra_sheets():
    from app.modules.document.data_query_spreadsheet import parse_data_query_spreadsheet
    from app.modules.document.file_types import DocumentFileType

    dataset = parse_data_query_spreadsheet(
        file_type=DocumentFileType.EXCEL.value,
        content=make_workbook(
            [
                ("Empty", []),
                ("Sales", [["Customer", "Amount"], ["Alice", 10], ["Bob", None]]),
                ("Also Empty", []),
            ]
        ),
    )

    assert dataset.original_sheet_name == "Sales"
    assert dataset.headers == ["Customer", "Amount"]
    assert dataset.rows == [["Alice", "10"], ["Bob", ""]]


@pytest.mark.parametrize(
    ("workbook_bytes", "reason"),
    [
        (make_workbook([("Empty", [])]), "empty workbook"),
        (make_workbook([("HeaderOnly", [["Customer", "Amount"]])]), "header-only sheet"),
        (
            make_workbook(
                [
                    ("Sales", [["Customer"], ["Alice"]]),
                    ("Refunds", [["Customer"], ["Bob"]]),
                ]
            ),
            "multiple data sheets",
        ),
    ],
)
def test_excel_parser_rejects_empty_header_only_or_multiple_data_sheets(
    workbook_bytes,
    reason,
):
    from app.modules.document.data_query_spreadsheet import (
        DataQuerySpreadsheetInvalid,
        parse_data_query_spreadsheet,
    )
    from app.modules.document.file_types import DocumentFileType

    with pytest.raises(DataQuerySpreadsheetInvalid, match=reason):
        parse_data_query_spreadsheet(
            file_type=DocumentFileType.EXCEL.value,
            content=workbook_bytes,
        )


def test_excel_parser_rejects_header_only_sheet_even_with_data_sheet():
    from app.modules.document.data_query_spreadsheet import (
        DataQuerySpreadsheetInvalid,
        parse_data_query_spreadsheet,
    )
    from app.modules.document.file_types import DocumentFileType

    with pytest.raises(DataQuerySpreadsheetInvalid, match="header-only sheet"):
        parse_data_query_spreadsheet(
            file_type=DocumentFileType.EXCEL.value,
            content=make_workbook(
                [
                    ("Sales", [["Customer"], ["Alice"]]),
                    ("HeaderOnly", [["Notes"]]),
                ]
            ),
        )


def test_csv_parser_returns_single_data_table():
    from app.modules.document.data_query_spreadsheet import parse_data_query_spreadsheet
    from app.modules.document.file_types import DocumentFileType

    dataset = parse_data_query_spreadsheet(
        file_type=DocumentFileType.CSV.value,
        content=b"Customer,Amount\nAlice,10\nBob,\n",
    )

    assert dataset.original_sheet_name == "Data"
    assert dataset.headers == ["Customer", "Amount"]
    assert dataset.rows == [["Alice", "10"], ["Bob", ""]]


@pytest.mark.parametrize("content", [b"", b"Customer,Amount\n"])
def test_csv_parser_rejects_files_without_data_rows(content):
    from app.modules.document.data_query_spreadsheet import (
        DataQuerySpreadsheetInvalid,
        parse_data_query_spreadsheet,
    )
    from app.modules.document.file_types import DocumentFileType

    with pytest.raises(DataQuerySpreadsheetInvalid, match="data rows"):
        parse_data_query_spreadsheet(
            file_type=DocumentFileType.CSV.value,
            content=content,
        )


def test_data_query_table_plan_generates_safe_names_columns_metadata_and_sql():
    from app.modules.document.data_query_spreadsheet import (
        ParsedDataQueryTable,
        build_create_table_sql,
        build_data_query_table_plan,
        build_insert_sql_and_params,
    )

    dataset = ParsedDataQueryTable(
        original_sheet_name="Sales",
        headers=["Customer Name", "Amount"],
        rows=[["Alice", "10"]],
    )

    plan = build_data_query_table_plan(
        namespace="alice@example.com",
        table_name="sales_2026",
        dataset=dataset,
    )

    assert plan.physical_table_name.startswith("dq_")
    assert plan.physical_table_name.endswith("_sales_2026")
    assert "alice@example.com" not in plan.physical_table_name
    assert plan.columns_info == {
        "originalSheetName": "Sales",
        "physicalTableName": plan.physical_table_name,
        "columns": [
            {"ordinal": 1, "header": "Customer Name", "columnName": "col_001", "type": "TEXT"},
            {"ordinal": 2, "header": "Amount", "columnName": "col_002", "type": "TEXT"},
        ],
    }
    assert "sheets" not in plan.columns_info
    assert plan.create_sql == build_create_table_sql(
        physical_table_name=plan.physical_table_name,
        column_names=["col_001", "col_002"],
    )
    assert '"col_001" TEXT' in plan.create_sql
    assert '"col_002" TEXT' in plan.create_sql

    insert_sql, params = build_insert_sql_and_params(
        physical_table_name=plan.physical_table_name,
        column_names=["col_001", "col_002"],
        row=["Alice", "10"],
    )
    assert "Alice" not in insert_sql
    assert ":col_001" in insert_sql
    assert params == {"col_001": "Alice", "col_002": "10"}


def test_physical_table_name_rejects_logical_name_that_exceeds_postgres_identifier_limit():
    from app.modules.document.data_query_spreadsheet import build_physical_table_name

    with pytest.raises(ValueError, match="invalid table name"):
        build_physical_table_name(namespace="alice", table_name="a" * 48)


class RecordingStorage:
    def __init__(self, downloads):
        self.downloads = downloads
        self.download_calls = []

    async def download_bytes(self, *, object_key):
        self.download_calls.append(object_key)
        return self.downloads[object_key]


class RecordingRepository:
    def __init__(self, table_meta):
        self.table_meta = table_meta
        self.import_calls = []

    async def get_table_meta_by_document(self, *, document_id):
        return self.table_meta

    async def import_data_query_table(self, **kwargs):
        self.import_calls.append(kwargs)


@pytest.mark.asyncio
async def test_ingestion_workflow_builds_plan_and_imports_single_table_metadata():
    from app.modules.document.data_query_spreadsheet import ingest_data_query_spreadsheet_document
    from app.modules.document.file_types import DocumentFileType
    from app.modules.document.models import DocumentStatus, KnowledgeBaseType

    content = b"Customer,Amount\nAlice,10\n"
    document = SimpleNamespace(
        doc_id=42,
        doc_title="sales.csv",
        upload_user="alice",
        knowledge_base_type=KnowledgeBaseType.DATA_QUERY.value,
        file_type=DocumentFileType.CSV.value,
        status=DocumentStatus.UPLOADED.value,
        extension={"tableName": "sales"},
    )
    repository = RecordingRepository(
        table_meta=SimpleNamespace(
            document_id=42,
            namespace="alice",
            table_name="sales",
        )
    )
    storage = RecordingStorage({"documents/42/original/sales.csv": content})

    await ingest_data_query_spreadsheet_document(
        document=document,
        document_repository=repository,
        storage=storage,
    )

    assert storage.download_calls == ["documents/42/original/sales.csv"]
    import_call = repository.import_calls[0]
    assert import_call["document_id"] == 42
    assert import_call["physical_table_name"].startswith("dq_")
    assert import_call["column_names"] == ["col_001", "col_002"]
    assert import_call["rows"] == [["Alice", "10"]]
    assert import_call["columns_info"]["originalSheetName"] == "Data"
    assert import_call["columns_info"]["physicalTableName"] == import_call["physical_table_name"]
    assert import_call["columns_info"]["columns"][0] == {
        "ordinal": 1,
        "header": "Customer",
        "columnName": "col_001",
        "type": "TEXT",
    }
    assert import_call["create_sql"].startswith('CREATE TABLE "')
