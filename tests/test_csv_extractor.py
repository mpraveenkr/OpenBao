from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.connectors.file_csv import CsvFileExtractor


def test_csv_extractor_reads_sample_csv_and_adds_metadata_columns():
    config = ConfigLoader().load_source("configs/sources/sample_csv_customers.yaml")

    frame = CsvFileExtractor(config.extraction).extract()

    assert len(frame) == 2
    assert "_source_file_path" in frame.columns
    assert "_source_file_name" in frame.columns
    assert "_source_file_size_bytes" in frame.columns
    assert "_source_file_modified_timestamp" in frame.columns
