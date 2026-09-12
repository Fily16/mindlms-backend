"""Tests unitarios para el pipeline de datos."""

import os
import tempfile
import pytest
import pandas as pd

from ml.data.pipeline.download_datasets import (
    generate_synthetic_dataset,
    _augment_text,
    _synonym_replace,
    _random_insert_filler,
    _sentence_reorder,
    SYNTHETIC_SAMPLES,
)


class TestSyntheticDataset:
    def test_generates_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_synthetic_dataset(tmpdir, n_augment=1)
            assert os.path.exists(path)
            df = pd.read_csv(path)
            assert len(df) > 0
            assert "text" in df.columns
            assert "label" in df.columns

    def test_all_labels_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_synthetic_dataset(tmpdir, n_augment=1)
            df = pd.read_csv(path)
            assert set(df["label"].unique()) == {0, 1, 2}

    def test_augmentation_increases_samples(self):
        total_original = sum(len(v) for v in SYNTHETIC_SAMPLES.values())
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_synthetic_dataset(tmpdir, n_augment=3)
            df = pd.read_csv(path)
            assert len(df) == total_original * 4  # original + 3 augmented


class TestAugmentation:
    def test_synonym_replace_returns_string(self):
        result = _synonym_replace("estoy triste y solo")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_filler_insert_returns_string(self):
        result = _random_insert_filler("me siento mal con todo esto hoy")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sentence_reorder_returns_string(self):
        result = _sentence_reorder("Primera oración. Segunda oración. Tercera oración.")
        assert isinstance(result, str)
        assert "oración" in result

    def test_augment_text_returns_different(self):
        original = "Estoy muy triste y solo, no puedo más con esta situación"
        results = set()
        for _ in range(20):
            results.add(_augment_text(original))
        # Al menos alguna variación
        assert len(results) > 1
