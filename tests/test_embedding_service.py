import uuid
from unittest.mock import MagicMock, patch

import numpy as np


def test_generate_embedding_returns_list():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros(384, dtype="float32")
    with patch("app.services.embedding_service._load_model", return_value=mock_model):
        from app.services.embedding_service import generate_embedding

        result = generate_embedding("revenue metric")
    assert isinstance(result, list)
    assert len(result) == 384


def test_upsert_creates_new_record():
    fake_embedding = [0.0] * 384
    with patch("app.services.embedding_service.generate_embedding", return_value=fake_embedding):
        from app.services.embedding_service import upsert_embedding

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        upsert_embedding(db, uuid.uuid4(), "business_term", "churn", "Customer churn rate")
        db.add.assert_called_once()
        db.commit.assert_called_once()


def test_upsert_updates_existing_record():
    fake_embedding = [0.1] * 384
    existing = MagicMock()
    with patch("app.services.embedding_service.generate_embedding", return_value=fake_embedding):
        from app.services.embedding_service import upsert_embedding

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        upsert_embedding(db, uuid.uuid4(), "business_term", "churn", "Updated definition")
        assert existing.content == "Updated definition"
        assert existing.embedding == fake_embedding
        db.add.assert_not_called()
