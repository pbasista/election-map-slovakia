from election_map_slovakia import output


def test_gzip_sizes_are_measured_once_per_content_and_compressor(tmp_path, monkeypatch):
    memo = tmp_path / output.GZIP_MEMO_DIR / "build.json"
    blobs = [b"a" * 1000, b"b" * 10, b"a" * 1000]
    size = output.gzip_size
    measured: list[bytes] = []

    def counted(data: bytes) -> int:
        measured.append(data)
        return size(data)

    monkeypatch.setattr(output, "gzip_size", counted)
    sizes = output.gzip_sizes(blobs, memo)
    assert sizes == [size(b) for b in blobs]
    assert sorted(measured) == sorted(set(blobs))
    measured.clear()
    assert output.gzip_sizes(blobs, memo) == sizes
    assert measured == []
    # Sizes kept by another compressor are measured again.
    monkeypatch.setattr(output, "GZIP", "zlib -9")
    assert output.gzip_sizes(blobs, memo) == sizes
    assert sorted(measured) == sorted(set(blobs))
