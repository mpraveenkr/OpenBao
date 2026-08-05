from ingestion_framework.normalizers.columns import ColumnNormalizer


def test_column_normalization_examples():
    normalizer = ColumnNormalizer()

    assert normalizer.normalize_one("Customer ID") == "customer_id"
    assert normalizer.normalize_one("Customer-Name") == "customer_name"
    assert normalizer.normalize_one("Created Date") == "created_date"


def test_column_normalization_handles_duplicates_and_empty_names():
    normalizer = ColumnNormalizer()

    assert normalizer.normalize([" A ", "A", "!!!"]) == ["a", "a_2", "unnamed_column"]
