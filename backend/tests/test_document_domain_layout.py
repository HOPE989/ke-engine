def test_document_domain_exposes_layered_import_paths():
    from app.domains.document.components.converters import DocumentConverterFactory
    from app.domains.document.components.splitters import DocumentSplitterFactory
    from app.domains.document.repositories.document_repository import DocumentRepository
    from app.domains.document.services.chunking import chunk_document
    from app.domains.document.services.upload import upload_document
    from app.domains.document.services.vectorization import store_document_vectors
    from app.domains.document.shared.models import KnowledgeDocument

    assert DocumentConverterFactory.__name__ == "DocumentConverterFactory"
    assert DocumentSplitterFactory.__name__ == "DocumentSplitterFactory"
    assert DocumentRepository.__name__ == "DocumentRepository"
    assert callable(chunk_document)
    assert callable(upload_document)
    assert callable(store_document_vectors)
    assert KnowledgeDocument.__name__ == "KnowledgeDocument"
