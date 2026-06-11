import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_model():
    import numpy as np

    model = MagicMock()
    model.encode.return_value = np.zeros(768, dtype="float32")
    return model


def test_generate_embedding_document_prefix(mock_model):
    with patch("app.services.embedding_service._load_model", return_value=mock_model):
        from app.services.embedding_service import generate_embedding

        generate_embedding("revenue metric", mode="document")
        mock_model.encode.assert_called_once_with("search_document: revenue metric")


def test_generate_embedding_query_prefix(mock_model):
    with patch("app.services.embedding_service._load_model", return_value=mock_model):
        from app.services.embedding_service import generate_embedding

        generate_embedding("revenue metric", mode="query")
        mock_model.encode.assert_called_once_with("search_query: revenue metric")


def test_upsert_creates_new_record(mock_model):
    with patch("app.services.embedding_service._load_model", return_value=mock_model):
        from app.services.embedding_service import upsert_embedding

        db = MagicMock()
        db.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None

        tenant_id = uuid.uuid4()
        upsert_embedding(db, tenant_id, "business_term", "churn", "Customer churn rate definition")

        db.add.assert_called_once()
        db.commit.assert_called_once()
