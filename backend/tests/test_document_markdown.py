import pytest

from app.domains.document.components import markdown_assets as markdown_module


def test_parse_markdown_image_references_captures_supported_inline_images():
    parse_markdown_image_references = getattr(
        markdown_module,
        "parse_markdown_image_references",
        None,
    )
    markdown = "\n".join(
        [
            "![](images/page-1.png)",
            "![chart](images/page-2.png)",
            "![remote](https://example.com/image.png)",
        ]
    )

    assert parse_markdown_image_references is not None
    references = parse_markdown_image_references(markdown)

    assert [(reference.alt, reference.target) for reference in references] == [
        ("", "images/page-1.png"),
        ("chart", "images/page-2.png"),
        ("remote", "https://example.com/image.png"),
    ]


@pytest.mark.parametrize(
    "markdown",
    [
        '![chart](images/page-1.png "title")',
        "![chart](<images/page-1.png>)",
        r"![chart\]](images/page-1.png)",
        "![chart](images/(page-1).png)",
    ],
)
def test_parse_markdown_image_references_ignores_unsupported_commonmark_forms(markdown):
    parse_markdown_image_references = getattr(
        markdown_module,
        "parse_markdown_image_references",
        None,
    )

    assert parse_markdown_image_references is not None
    assert parse_markdown_image_references(markdown) == []


def test_rewrite_markdown_image_links_uses_supported_parser_scope():
    markdown = "\n".join(
        [
            '![titled](images/page-1.png "title")',
            "![chart](images/page-2.png)",
        ]
    )

    rewritten = markdown_module.rewrite_markdown_image_links(
        markdown,
        {"images/page-2.png": "https://files.example.com/page-2.png"},
        image_descriptions={"images/page-2.png": "generated chart"},
    )

    assert rewritten == "\n".join(
        [
            '![titled](images/page-1.png "title")',
            "![generated chart](https://files.example.com/page-2.png)",
        ]
    )


def test_rewrite_markdown_image_links_uses_generated_description_not_placeholder():
    rewritten = markdown_module.rewrite_markdown_image_links(
        "\n".join(
            [
                "![](images/page-1.png)",
                "![remote alt](https://example.com/image.png)",
            ]
        ),
        {"images/page-1.png": "https://files.example.com/page-1.png"},
        image_descriptions={"images/page-1.png": "generated page"},
    )

    assert rewritten == "\n".join(
        [
            "![generated page](https://files.example.com/page-1.png)",
            "![remote alt](https://example.com/image.png)",
        ]
    )
    assert "图片描述" not in rewritten


def test_rewrite_markdown_image_links_marks_missing_description_result_as_parse_error():
    rewritten = markdown_module.rewrite_markdown_image_links(
        "![](images/page-1.png)",
        {"images/page-1.png": "https://files.example.com/page-1.png"},
        image_descriptions={},
    )

    assert rewritten == "![图片解析错误](https://files.example.com/page-1.png)"
